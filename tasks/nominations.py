import os
import os.path
import logging
import re
from lxml.html import fromstring
import us
import json
import traceback

from tasks import Task, current_congress, format_datetime, ordinalize, neighborhood


class Nominations(Task):

    SCRAPE_BASE_URL = 'https://www.congress.gov/nomination/'

    def __init__(self, options=None, config=None):
        super(Nominations, self).__init__(options, config)
        self.congress = self.options.get('congress', current_congress())
        self.nomination_id = self.options.get('nomination_id', None)
        self.error_dict = {}

    def run(self):

        if self.nomination_id and self.congress:
            self.scrape(self.nomination_id)
        elif self.congress:
            for nom_id in self.collect_nomination_ids(self.congress):
                self.scrape(nom_id)
        else:
            for congress in range(97, current_congress()+1):
                for nom_id in self.collect_nomination_ids(congress):
                    self.scrape(nom_id)

        # TODO report error_dictionary

    def collect_nomination_ids(self, congress):
        url = 'https://www.congress.gov/search?q={"source":"nominations","congress":%s}&pageSize=250' % congress
        nomination_ids = []
        i = 1
        while True:
            body = self.download(url + '&page=' + str(i))
            doc = fromstring(body)
            for id_ele in doc.xpath('//ol[@class="results_list"]/li/h2/a'):
                nomination_ids.append(id_ele.text + '-' + str(congress))
            total = doc.xpath('//span[@class="results-number"]/strong')[0].text.split('-')[1].replace(',', '').strip()
            of = doc.xpath('//span[@class="results-number"]/text()')[1].replace('of', '').replace(',', '').strip()
            if int(total) == int(of):
                break
            i += 1

        logging.info("Found {0} nominations for {1} congress".format(len(nomination_ids), ordinalize(int(congress))))
        return nomination_ids

    def scrape(self, nomination_id):

        # create necessary directories for cache and download HTML
        cache_file = self.nomination_cache_for(nomination_id, "information.html")

        body = self.download(self.nomination_url_for(nomination_id), cache_file, self.options)

        if not body:
            return {'saved': False, 'ok': False, 'reason': "failed to download"}

        if self.options.get("download_only", False):
            return {'saved': False, 'ok': True, 'reason': "requested download only"}

        # TODO:
        #   detect group nominations, particularly for military promotions
        #   detect when a group nomination is split into subnominations
        #
        # Also, the splitting process is nonsense:
        # http://thomas.loc.gov/home/PN/split.htm

        if "split into two or more parts" in body:
            return {'saved': False, 'ok': True, 'reason': 'was split'}

        try:
            self.output_nomination(self.parse_nomination(nomination_id, body))
        except:
            self.error_dict[nomination_id] = traceback.format_exc()

    def parse_nomination(self, nomination_id, body):
        """
        This does the meat of extracting relevant fields from the HTML.

        @param nomination_id:
        @type nomination_id:
        @param body:
        @type body:
        @return:
        @rtype:
        """

        body = re.sub("<!--.+?-->", "", body)

        doc = fromstring(body)
        for br in doc.xpath("*//br"):
            br.tail = "\n" + br.tail if br.tail else "\n"

        nomination_type, number, congress = self.split_nomination_id(nomination_id)

        info = {
            'nomination_id': nomination_id,
            'actions': [],
            'congress': congress,
            'referred_to': [],
            'referred_to_names': [],
            'nominees': []
        }

        def overview_getter(text):
            titles = doc.xpath('//div[@class="overview"]//h2[contains(text(),"{0}")]'.format(text))[0].getnext().xpath('li')
            return False if len(titles) > 1 else titles[0].text_content().strip()

        def get_actions(_doc, _info):

            if _doc.xpath('//table[@class="item_table"]/thead/tr/th')[0].text == 'Date':
                for row in _doc.xpath('//table[@class="item_table"]/tbody/tr'):
                    text = row.xpath('td[@class="actions"]')[0].text
                    _info['actions'].append({
                        'type': 'action',
                        'location': 'committee' if 'Committee' in text else 'floor',
                        'acted_at': row.xpath('td[@class="date"]')[0].text,
                        'text': text.strip()
                    })

        info['organization'] = overview_getter('Organization')
        info['received_on'] = overview_getter('Date Received from President')
        info['reported_by'] = overview_getter('Committee')
        info['referred_to_names'] = [overview_getter('Committee')]
        # TODO referred_to abbreviations

        # list of nominees, probably routine military such as PN1568-114
        if doc.xpath('//table[contains(@class, "item_table")]/thead/tr//th')[0].text == 'Nominee':

            # check if position name is in table with nominees and if not use single position in overview div
            if len(doc.xpath('//table[contains(@class, "item_table")]/thead/tr/th')) > 1:
                position = 'in_table'
            else:
                position = re.sub('to be', '', overview_getter('Position'), flags=re.I).strip()

            info['nominees'] = []
            for row in doc.xpath('//table[contains(@class, "item_table")]/tbody/tr'):
                info['nominees'].append({
                    'name': row.xpath('td')[0].text,
                    'position': row.xpath('td')[1].text if position == 'in_table' else position
                })

            # Some nominations have separate links for action
            action_url = "{0}/actions".format(self.nomination_url_for(nomination_id))
            if body.find(action_url) != -1:
                get_actions(fromstring(self.download(action_url)), info)
            else:
                only_action = overview_getter('Latest Action').split('-')

                info['actions'].append({
                    'type': 'action',
                    'location': 'committee' if 'Committee' in only_action[1].strip() else 'floor',
                    'acted_at': only_action[0].strip(),
                    'text': only_action[1].strip()
                })
        else:
            get_actions(doc, info)

            data = overview_getter('Description').strip()

            # check to see if there is a list of nominations in the description
            if re.search('\\nTo be ([a-z. ]+)\\n', data, flags=re.I):
                for _prev, _item, _next in neighborhood(re.finditer('\\nTo be ([a-z. ]+)\\n', data, flags=re.I)):
                    position = _item.group(1).strip()
                    end_index = _next.start(0) if _next else len(data)-1
                    names = data[_item.end(0):end_index].strip().split('\n')
                    for name in names:
                        info["nominees"].append({
                            "name": name,
                            'position': position,
                            'state': None
                        })
            # hopefully only one well-formed nominee
            else:
                multiple_description = {
                    'For appointment as': r'For appointment as ([a-z. ]+),',
                    'The following-named': r'class indicated: ([a-z., ]+),'
                }

                standard_format = True
                for startswith, regexp in multiple_description.iteritems():
                    if data.startswith(startswith):
                        position = re.search(regexp, data, flags=re.I).group(1)
                        for name in filter(None, data.split('\n'))[1:]:
                            info["nominees"] = [{
                                "name": name,
                                "position": position,
                                "state": None
                            }]
                        standard_format = False

                if standard_format:

                    data = data.split(", vice")[0].split(',')
                    name = data[0].strip()
                    try:
                        state = us.states.lookup(unicode(data[1].replace('of', '').strip())).abbr
                    except AttributeError:
                        state = None
                    position = re.sub('to be', '', data[2], flags=re.I).strip()

                    info["nominees"] = [{
                        "name": name,
                        "position": position,
                        "state": state
                    }]

        return info

    def output_nomination(self, nomination):
        logging.info("[%s] Writing to disk..." % nomination['nomination_id'])
        path = self.output_for_nomination(nomination['nomination_id'], 'json')
        self.storage.mkdir_p(os.path.dirname(path))
        with self.storage.fs.open(path, 'w') as json_file:
            json_file.write(unicode(json.dumps(nomination, indent=2, default=format_datetime)))

    def nomination_url_for(self, nomination_id):
        nomination_type, number, congress = self.split_nomination_id(nomination_id)
        return self.SCRAPE_BASE_URL + "{0}-congress/{1}".format(ordinalize(int(congress)), '/'.join(number.split('-')))

    @staticmethod
    def split_nomination_id(nomination_id):
        try:
            return re.match("^([A-z]{2})([\d-]+)-(\d+)$", nomination_id).groups()
        except Exception, e:
            logging.error("Unabled to parse %s" % nomination_id)
            return None, None, None

    def output_for_nomination(self, nomination_id, format):
        nomination_type, number, congress = self.split_nomination_id(nomination_id)
        return os.path.join(self.storage.data_dir, congress, 'nominations', number, 'data.%s' % format)

    def nomination_cache_for(self, nomination_id, file):
        nomination_type, number, congress = self.split_nomination_id(nomination_id)
        return os.path.join(congress, 'nominations', number, file)
