import os
import os.path
import re
import xmltodict
import json
import logging
from lxml import etree
from datetime import datetime
import copy
from collections import defaultdict

import tasks
from tasks import Task, make_node as parent_make_node, current_congress, format_datetime, unescape
from tasks.fdsys import Fdsys


class Bills(Task):

    BILL_TYPES = {
        'hr': ('HR', 'H.R.'),
        'hres': ('HE', 'H.RES.'),
        'hjres': ('HJ', 'H.J.RES.'),
        'hconres': ('HC', 'H.CON.RES.'),
        's': ('SN', 'S.'),
        'sres': ('SE', 'S.RES.'),
        'sjres': ('SJ', 'S.J.RES.'),
        'sconres': ('SC', 'S.CON.RES.'),
    }

    SOURCE_SYSTEM = {
        0: 'Senate',
        1: 'House committee actions',
        2: 'House floor actions',
        9: 'Library of Congress',
        # TODO add remaining sources
    }

    def __init__(self, options=None, config=None):
        super(Bills, self).__init__(options, config)
        self.bill_types = filter(None, set(self.options.get("bill_types", '').split(","))) or self.BILL_TYPES.keys()
        self.congress = self.options.get('congress', current_congress())
        self.bill_id = self.options.get('bill_id', None)
        self.committees = self._load_committees_systemCodes()

    def run(self):
        if self.bill_id:
            return self.write_legacy_dict_to_disk(self.bill_id, self.options.get('amendments', True))
        else:
            for bill_id in self.scan_for_bills_to_process():
                self.write_legacy_dict_to_disk(bill_id, self.options.get('amendments', True))

    def _path_to_billstatus_file(self, bill_id):
        bill_type, bill_number, congress = self.split_bill_id(bill_id)
        return os.path.join(self.storage.data_dir, congress, 'bills',
                            bill_type, bill_type + bill_number, Fdsys.BULK_BILLSTATUS_FILENAME)

    def write_legacy_dict_to_disk(self, bill_id, amendments=True):
        # Read FDSys bulk data file.
        xml_as_dict = self.convert_bulk_xml_to_dict(bill_id)
        legacy_dict = self.convert_bulk_to_legacy_dict(xml_as_dict)

        # Convert and write out data.json and data.xml.
        path = os.path.dirname(self._path_to_billstatus_file(bill_id))
        logging.info("[%s] Writing to %s..." % (bill_id, path))
        with self.storage.fs.open(path + '/data.json', 'w') as json_file:
            json_file.write(unicode(json.dumps(legacy_dict, indent=2, sort_keys=True)))

        from bill_info import create_govtrack_xml
        with self.storage.fs.open(path + '/data.xml', 'wb') as xml_file:
            xml_file.write(create_govtrack_xml(legacy_dict, self, self.options))

        if amendments:
            from tasks.amendments import Amendments
            Amendments(self.options, self.config).extract_all_amendments(xml_as_dict)

        # Mark this bulk data file as processed by saving its lastmod
        # file under a new path.
        self.storage.write(
            self.storage.read(self._path_to_billstatus_file(bill_id).replace(".xml", "-lastmod.txt")),
            os.path.join(path, "data-fromfdsys-lastmod.txt"))

    def convert_bulk_xml_to_dict(self, bill_id):
        with self.storage.fs.open(self._path_to_billstatus_file(bill_id)) as fdsys_billstatus:
            return xmltodict.parse(fdsys_billstatus.read(), force_list=('item', 'amendment',))

    def convert_bulk_to_legacy_dict(self, xml_as_dict):
        """
        Handles converting a government bulk XML file to legacy dictionary form.

        @param bill_id: id of the bill in format [type][number]-[congress] e.x. s934-113
        @type bill_id: str
        @return: dictionary of bill attributes
        @rtype: dict
        """

        bill_dict = xml_as_dict['billStatus']['bill']
        bill_id = self.build_bill_id(bill_dict['billType'].lower(), bill_dict['billNumber'], bill_dict['congress'])
        titles = self._build_legacy_titles(bill_dict['titles']['item'])
        actions = self.build_legacy_actions_list(bill_dict['actions']['item'], bill_id, Bills.current_title_for(titles, 'official'))
        status, status_date = self.latest_status(actions, bill_dict.get('introducedDate', ''))

        legacy_dict = {
            'bill_id': bill_id,
            'bill_type': bill_dict.get('billType').lower(),
            'number': bill_dict.get('billNumber'),
            'congress': bill_dict.get('congress'),

            'url': self.billstatus_url_for(bill_id),

            'introduced_at': bill_dict.get('introducedDate', ''),
            'by_request': tasks.safeget(bill_dict, None, 'sponsors', 'item', 'byRequestType') is not None,
            'sponsor': self._build_legacy_sponsor_dict(tasks.safeget(bill_dict, None, 'sponsors', 'item', 0), self),
            'cosponsors': self._build_legacy_cosponsor_list(tasks.safeget(bill_dict, [], 'cosponsors', 'item')),

            'actions': actions,
            'history': self._build_legacy_history(actions),
            'status': status,
            'status_at': status_date,
            'enacted_as': self.slip_law_from(actions),

            'titles': titles,
            'official_title': Bills.current_title_for(titles, 'official'),
            'short_title': Bills.current_title_for(titles, 'short'),
            'popular_title': Bills.current_title_for(titles, 'popular'),

            'summary': self._build_summary_dict(bill_dict['summaries']['billSummaries']),

            # The top term's case has changed with the new bulk data. It's now in
            # Title Case. For backwards compatibility, the top term is run through
            # '.capitalize()' so it matches the old string. TODO: Remove one day?
            'subjects_top_term': Bills._fixup_top_term_case(bill_dict['primarySubject']['name']) if bill_dict['primarySubject'] else None,
            'subjects':
                sorted(
                    ([Bills._fixup_top_term_case(bill_dict['primarySubject']['name'])] if bill_dict['primarySubject'] else []) +
                    ([item['name'] for item in bill_dict['subjects']['billSubjects']['otherSubjects']['item']] if bill_dict['subjects']['billSubjects']['otherSubjects'] else [])
                ),

            'related_bills': self._build_legacy_related_bills_list(tasks.safeget(bill_dict, [], 'relatedBills', 'item')),
            'committees': self._build_legacy_committees_list(tasks.safeget(bill_dict, [], 'committees', 'billCommittees', 'item')),
            'amendments': self._build_legacy_amendments_list(tasks.safeget(bill_dict, [], 'amendments', 'amendment')),

            'updated_at': bill_dict.get('updateDate', ''),
        }

        return legacy_dict

    @staticmethod
    def _fixup_top_term_case(term):
        if term in ("Native Americans",):
            return term
        return term.capitalize()

    @staticmethod
    def _build_legacy_sponsor_dict(sponsor_dict, task):
        """

        @param sponsor_dict:
        @type sponsor_dict:
        @return:
        @rtype:
        """

        if sponsor_dict is None:
            # TODO: This can hopefully be removed. In testing s414-113
            # was missing sponsor data. But all bills have a sponsor.
            return None

        # TODO: Don't do regex matching here. Find another way.
        m = re.match(r'(?P<title>(Rep|Sen))\. (?P<name>.*?) +\[(?P<party>[DRI])-(?P<state>[A-Z][A-Z])(-(?P<district>\d{1,2}|At Large))?\]$',
            sponsor_dict['fullName'])
        
        if m.group("district") is None:
            district = None # a senator
        elif m.group("district") == "At Large":
            district = None # TODO: For backwards compatibility, we're returning None, but 0 would be better.
        else:
            # TODO: For backwards compatibility, we're returning a string, but an int would be better.
            district = m.group('district')

        return {
            'title': m.group("title"),
            'name': m.group("name"), # the firstName, middleName, lastName fields have inconsistent capitalization - some are all uppercase
            'district': district,
            'state': m.group('state'),
            #'party': m.group('party'),
            'thomas_id': task.lookup_legislator_by_id('bioguide', sponsor_dict['bioguideId'])['id']['thomas'],  # TODO: Remove.
            'bioguide_id': sponsor_dict['bioguideId'],
            'type': 'person'
        }

    def _build_legacy_cosponsor_list(self, cosponsors_list):
        """

        @param cosponsors_list:
        @type cosponsors_list:
        @return:
        @rtype:
        """
        def build_dict(item):
            cosponsor_dict = self._build_legacy_sponsor_dict(item, self)
            del cosponsor_dict["type"] # always 'person'
            cosponsor_dict.update({
                'sponsored_at': item['sponsorshipDate'],
                'withdrawn_at': item['sponsorshipWithdrawnDate'],
                'original_cosponsor': item['isOriginalCosponsor'] == 'True'
            })
            return cosponsor_dict

        cosponsors = [build_dict(cosponsor) for cosponsor in cosponsors_list]

        # TODO: Can remove. Sort like the old order to make diffs easier.
        cosponsors.sort(key = lambda c: c['name'].lower())

        return cosponsors

    @staticmethod
    def build_legacy_actions_list(action_list, bill_id, title):
        from bill_info import parse_bill_action

        # The bulk XML data has action history information from multiple sources. For
        # major actions, the Library of Congress (code 9) action item often duplicates
        # the information of a House/Senate action item. We have to skip one so that we
        # don't tag multiple history items with the same parsed action info, which
        # would imply the action (like a vote) ocurred multiple times. THOMAS appears
        # to have suppressed the Library of Congress action lines in certain cases
        # to avoid duplication - they were not in our older data files.
        #
        # Also, there are some ghost action items with totally empty text. Remove those.
        # TODO: When removed from upstream data, we can remove that check.
        closure = {
            "prev": None,
        }
        def keep_action(item, closure):
            if item['text'] in (None, ""):
                return False

            keep = True
            if closure['prev']:
                if tasks.safeget(item, None, 'sourceSystem', 'code') == "9":
                    # Date must match previous action..
                    # If both this and previous have a time, the times must match.
                    # The text must approximately match. Sometimes the LOC text has a prefix
                    #   and different whitespace. And they may drop references -- so we'll
                    # use our Bills.action_for helper function to drop references from both
                    # prior to the string comparison.
                    if   item['actionDate'] == closure["prev"]["actionDate"] \
                     and (item.get('actionTime') == closure["prev"].get("actionTime") or not item.get('actionTime') or not closure["prev"].get("actionTime")) \
                     and Bills.action_for(item['text'])[0].replace(" ", "").endswith(Bills.action_for(closure["prev"]["text"])[0].replace(" ", "")):

                        keep = False
            closure['prev'] = item
            return keep

        action_list = [item for item in action_list
            if keep_action(item, closure)]

        # Turn the actions into dicts. The actions are in reverse-chronological
        # order in the bulk data XML. Process them in chronological order so that
        # our bill status logic sees the actions in the right order.

        def build_dict(item, closure):
            text, references = Bills.action_for(item['text'])

            if not item.get('actionTime'):
                acted_at = item.get('actionDate', '')
            else:    
                # Although we get the action date & time in an ISO-ish format (split
                # across two fields), and although we know it's in local time at the
                # U.S. Capitol (i.e. U.S. Eastern), we don't know the UTC offset which
                # is a part of how we used to serialize the time. So parse and then
                # use pytz (via format_datetime) to re-serialize.
                acted_at = format_datetime(datetime.strptime(item.get('actionDate', '') + " " + item['actionTime'], "%Y-%m-%d %H:%M:%S"))

            action_dict = {
                'acted_at': acted_at,
                'action_code': item.get('actionCode', ''),
                'committees': [item['committee']['systemCode'][0:-2].upper()] if tasks.safeget(item, '', 'committee', 'systemCode') else None,
                'references': references,
                'type': 'action',  # TODO see parse_bill_action in bill_info.py this is a mess
                #'status': '',  # TODO see parse_bill_action in bill_info.py this is a mess
                'text': text,
                #'where': '', # TODO see parse_bill_action in bill_info.py this is a mess
            }

            if not action_dict["committees"]:
                # remove if empty - not present in how we used to generate the file
                del action_dict["committees"]

            extra_action_info, new_status = parse_bill_action(action_dict, closure['prev_status'], bill_id, title)

            # only change/reflect status change if there was one
            if new_status:
                action_dict['status'] = new_status
                closure['prev_status'] = new_status

            # add additional parsed fields
            if extra_action_info:
                action_dict.update(extra_action_info)

            return action_dict

        closure = {
            "prev_status": "INTRODUCED",
        }
        return [build_dict(action, closure) for action in reversed(action_list)]

    @staticmethod
    def _build_legacy_history(actions):

        history = {}

        activation = Bills.activation_from(actions)
        if activation:
            history['active'] = True
            history['active_at'] = activation['acted_at']
        else:
            history['active'] = False

        house_vote = None
        for action in actions:
            if (action['type'] == 'vote') and (action['where'] == 'h') and (action['vote_type'] != "override"):
                house_vote = action
        if house_vote:
            history['house_passage_result'] = house_vote['result']
            history['house_passage_result_at'] = house_vote['acted_at']

        senate_vote = None
        for action in actions:
            if (action['type'] == 'vote') and (action['where'] == 's') and (action['vote_type'] != "override"):
                senate_vote = action
        if senate_vote:
            history['senate_passage_result'] = senate_vote['result']
            history['senate_passage_result_at'] = senate_vote['acted_at']

        senate_vote = None
        for action in actions:
            if (action['type'] == 'vote-aux') and (action['vote_type'] == 'cloture') and (action['where'] == 's') and (action['vote_type'] != "override"):
                senate_vote = action
        if senate_vote:
            history['senate_cloture_result'] = senate_vote['result']
            history['senate_cloture_result_at'] = senate_vote['acted_at']

        vetoed = None
        for action in actions:
            if action['type'] == 'vetoed':
                vetoed = action
        if vetoed:
            history['vetoed'] = True
            history['vetoed_at'] = vetoed['acted_at']
        else:
            history['vetoed'] = False

        house_override_vote = None
        for action in actions:
            if (action['type'] == 'vote') and (action['where'] == 'h') and (action['vote_type'] == "override"):
                house_override_vote = action
        if house_override_vote:
            history['house_override_result'] = house_override_vote['result']
            history['house_override_result_at'] = house_override_vote['acted_at']

        senate_override_vote = None
        for action in actions:
            if (action['type'] == 'vote') and (action['where'] == 's') and (action['vote_type'] == "override"):
                senate_override_vote = action
        if senate_override_vote:
            history['senate_override_result'] = senate_override_vote['result']
            history['senate_override_result_at'] = senate_override_vote['acted_at']

        enacted = None
        for action in actions:
            if action['type'] == 'enacted':
                enacted = action
        if enacted:
            history['enacted'] = True
            history['enacted_at'] = action['acted_at']
        else:
            history['enacted'] = False

        topresident = None
        for action in actions:
            if action['type'] == 'topresident':
                topresident = action
        if topresident and (not history['vetoed']) and (not history['enacted']):
            history['awaiting_signature'] = True
            history['awaiting_signature_since'] = action['acted_at']
        else:
            history['awaiting_signature'] = False

        return history

    @staticmethod
    def _build_legacy_status(action_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_status_at(action_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_enacted_as(action_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_titles(title_list):
        def build_dict(item):

            full_type = item['titleType']
            is_for_portion = False

            # "Official Titles as Introduced", "Short Titles on Conference report"
            splits = re.split(" as | on ", full_type, 1)
            if len(splits) == 2:
                title_type, state = splits

                if state.endswith(" for portions of this bill"):
                    is_for_portion = True
                    state = state.replace(" for portions of this bill" ,"")

                state = state.replace(":", "").lower()
            else:
                title_type, state = full_type, None

            if "Popular Title" in title_type:
                title_type = "popular"
            elif "Short Title" in title_type:
                title_type = "short"
            elif "Official Title" in title_type:
                title_type = "official"
            elif "Display Title" in title_type:
                title_type = "display"
            elif title_type == "Non-bill-report":
                # TODO: What kind of title is this? Maybe assign
                # a better title_type code once we know.
                title_type = "nonbillreport"
            else:
                raise Exception("Unknown title type: " + title_type)

            return {
                'title': item['title'],
                'is_for_portion': is_for_portion,
                'as': state,
                'type': title_type
            }

        titles = [build_dict(title) for title in title_list]

        # THOMAS used to give us the titles in a particular order:
        #  short as introduced
        #  short as introduced (for portion)
        #  short as some later stage
        #  short as some later stage (for portion)
        #  official as introduced
        #  official as some later stage
        # The "as" stages (introduced, etc.) were in the order in which actions
        # actually occurred. This was handy because to get the current title for
        # a bill, you need to know which action type was most recent. The new
        # order is reverse-chronological, so we have to turn the order around
        # for backwards compatibility. Rather than do a simple .reverse(), I'm
        # adding an explicit sort order here which gets very close to the THOMAS
        # order.
        # Unfortunately this can no longer be relied on because the new bulk
        # data has the "as" stages sometimes in the wrong order: The "reported to
        # senate" status for House bills seems to be consistently out of place.
        titles_copy = list(titles) # clone before beginning sort
        def first_index_of(**kwargs):
            for i, title in enumerate(titles_copy):
                for k, v in kwargs.items():
                    k = k.replace("_", "")
                    if title.get(k) != v:
                        break
                else:
                    # break not called --- all match
                    return i
        titles.sort(key = lambda title: (
            # keep the same 'short', 'official', 'display' order intact
            first_index_of(type=title['type']),

            # within each of those categories, reverse the 'as' order
            -first_index_of(type=title['type'], _as=title.get('as')),

            # put titles for portions last, within the type/as category
            title['is_for_portion'],

            # and within that, just sort alphabetically, case-insensitively (which is
            # what it appears THOMAS used to do)
            title['title'].lower(),
            ))

        return titles

    @staticmethod
    def current_title_for(titles, title_type):
        current_title = None
        current_as = -1  # not None, cause for popular titles, None is a valid 'as'

        for title in titles:
            if title['type'] != title_type or title['is_for_portion'] == True:
                continue
            if title['as'] == current_as:
                continue
            # right type, new 'as', store first one
            current_title = title['title']
            current_as = title['as']

        return current_title

    @staticmethod
    def _build_legacy_short_titles(title_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_committees_list(committee_list):
        activity_text_map = {
            "Referred to": ["referral"],
            "Hearings by": ["hearings"],
            "Markup by": ["markup"],
            "Reported by": ["reporting"],
            "Discharged from": ["discharged"],
            "Reported original measure": ["origin", "reporting"],
        }

        def fix_subcommittee_name(name):
            return re.sub("(.*) Subcommittee$",
                lambda m : "Subcommittee on " + m.group(1),
                name)

        def get_activitiy_list(item):
            if not item['activities']:
                return []
            return sum([activity_text_map.get(i['name'], [i['name']]) for i in item['activities']['item']], [])

        def fixup_committee_name(name):
            # Preserve backwards compatiblity.
            if name == "House House Administration":
                return "House Administration"
            return name

        def build_dict(item):
            committee_dict = {
                'activity': get_activitiy_list(item),
                'committee': fixup_committee_name(item['chamber'] + ' ' + re.sub(" Committee$", "", item['name'])),
                'committee_id': item['systemCode'][0:-2].upper(),
            }

            subcommittees_list = []
            if 'subcommittees' in item and item['subcommittees'] is not None:
                for subcommittee in item['subcommittees']['item']:
                    subcommittee_dict = copy.deepcopy(committee_dict)
                    subcommittee_dict.update({
                        'subcommittee': fix_subcommittee_name(subcommittee['name']),
                        'subcommittee_id': subcommittee['systemCode'][-2:],
                        'activity': get_activitiy_list(subcommittee),
                    })
                    subcommittees_list.append(subcommittee_dict)

            return [committee_dict] + subcommittees_list

        return sum([build_dict(committee) for committee in committee_list], [])

    @staticmethod
    def _build_legacy_amendments_list(amendment_list):
        def build_dict(item):
            # Malformed XML containing duplicate elements causes attributes to parse as a list
            for attr in ['type', 'number', 'congress']:
                if type(item[attr]) is list:
                    item[attr] = item[attr][0]
            return {
                'amendment_id': "{0}{1}-{2}".format(item['type'].lower(), item['number'], item['congress']),
                'amendment_type': item['type'].lower(),
                'chamber': item['type'][0].lower(),
                'number': item['number']
            }
        return [build_dict(amendment) for amendment in amendment_list]

    @staticmethod
    def _build_legacy_related_bills_list(related_bills_list):
        def build_dict(item):

            return {
                'reason': item['relationshipDetails']['item'][0]['type'].replace('bill', '').strip().lower(),
                'bill_id': '{0}{1}-{2}'.format(item['type'].replace('.', '').lower(), item['number'], item['congress']),
                'type': 'bill',
                'identified_by': item['relationshipDetails']['item'][0]['identifiedBy']
            }

        return [build_dict(related_bill) for related_bill in related_bills_list]

    # clean text, pull out the action type, any other associated metadata with an action
    @staticmethod
    def action_for(text):
        # strip out links
        text = re.sub(r"</?[Aa]( \S.*?)?>", "", text)

        # remove and extract references
        references = []
        match = re.search("\s*\(([^)]+)\)\s*$", text)
        if match:
            # remove the matched section
            text = text[0:match.start()] + text[match.end():]

            types = match.group(1)

            # fix use of comma or colon instead of a semi colon between reference types
            # have seen some accidental capitalization combined with accidental comma, thus the 'T'
            # e.g. "text of Title VII as reported in House: CR H3075-3077, Text omission from Title VII:" (hr5384-109)
            types = re.sub("[,:] ([a-zT])", r"; \1", types)
            # fix "CR:"
            types = re.sub("CR:", "CR", types)
            # fix a missing semicolon altogether between references
            # e.g. sres107-112, "consideration: CR S1877-1878 text as"
            types = re.sub("(\d+) +([a-z])", r"\1; \2", types)

            for reference in re.split("; ?", types):
                if ": " not in reference:
                    type, reference = None, reference
                else:
                    type, reference = reference.split(": ", 1)

                references.append({'type': type, 'reference': reference})

        return text, references

    def _load_committees_systemCodes(self):

        # Load the committee metadata from the congress-legislators repository and make a
        # mapping from thomas_id and house_id to the committee dict. For each committee,
        # replace the subcommittees list with a dict from thomas_id to the subcommittee.
        self.require_congress_legislators_repo()
        committees = {}
        for c in self.storage.yaml_load("congress-legislators/committees-current.yaml"):
            committees[c["thomas_id"]] = c
            if "house_committee_id" in c:
                committees[c["house_committee_id"] + "00"] = c
            c["subcommittees"] = dict((s["thomas_id"], s) for s in c.get("subcommittees", []))
        return committees

    def _build_summary_dict(self, summaries):
        # Some bills are missing the summaries entirely?
        if summaries is None:
            return None

        # Take the most recent summary, by looking at the lexicographically last updateDate.
        summaries = summaries['item']
        summary = sorted(summaries, key = lambda s: s['updateDate'])[-1]

        # Build dict.
        return {
            "date": summary['updateDate'],
            "as": summary['name'],
            "text": Bills.strip_tags(summary['text']),
        }

    @staticmethod
    def build_bill_version_id(bill_type, bill_number, congress, version_code):
        return "%s%s-%s-%s" % (bill_type, bill_number, congress, version_code)

    @staticmethod
    def split_bill_id(bill_id):
        return re.match("^([a-z]+)(\d+)-(\d+)$", bill_id).groups()

    @staticmethod
    def split_bill_version_id(bill_version_id):
        return re.match("^([a-z]+)(\d+)-(\d+)-([a-z\d]+)$", bill_version_id).groups()

    @staticmethod
    def build_bill_id(bill_type, bill_number, congress):
        return "%s%s-%s" % (bill_type, bill_number, congress)

    @staticmethod
    def billstatus_url_for(bill_id):
        bill_type, bill_number, congress = Bills.split_bill_id(bill_id)
        return Fdsys.BULKDATA_BASE_URL + 'BILLSTATUS/{0}/{1}/BILLSTATUS-{0}{1}{2}.xml'.format(congress, bill_type, bill_number)

    def output_for_bill(self, bill_id, format, is_data_dot=True):
        bill_type, number, congress = self.split_bill_id(bill_id)
        fn = "data.%s" % format if is_data_dot else format
        return "%s/%s/bills/%s/%s%s/%s" % (self.storage.data_dir, congress, bill_type, bill_type, number, fn)

    # find the first action beyond the standard actions every bill gets.
    # - if the bill's first action is "referral" then the first action not those
    #     most common
    #     e.g. hr3590-111 (active), s1-113 (inactive)
    # - if the bill's first action is "action", then the next action, if one is present
    #     resolutions
    #     e.g. sres5-113 (active), sres4-113 (inactive)
    # - if the bill's first action is anything else (e.g. "vote"), then that first action
    #     bills that skip committee
    #     e.g. s227-113 (active)
    @staticmethod
    def activation_from(actions):
        # there's NOT always at least one :(
        # as of 2013-06-10, hr2272-113 has no actions at all
        if len(actions) == 0:
            return None

        first = actions[0]

        if first['type'] in ["referral", "calendar", "action"]:
            for action in actions[1:]:
                if (action['type'] != "referral") and (action['type'] != "calendar") and ("Sponsor introductory remarks" not in action['text']):
                    return action
            return None
        else:
            return first

    @staticmethod
    def latest_status(actions, introduced_date):
        status, status_date = "INTRODUCED", introduced_date
        for action in actions:
            if action.get('status', None):
                status = action['status']
                status_date = action['acted_at']
        return status, status_date

    @staticmethod
    def slip_law_from(actions):
        for action in actions:
            if action['type'] == "enacted":
                return {
                    'law_type': action["law"],
                    'congress': action["congress"],
                    'number': action["number"]
                }

    @staticmethod
    def strip_tags(text):
        # Preserve paragraph breaks. Convert closing p tags (and surrounding whitespace) into two newlines. Strip trailing whitespace
        text = re.sub("\s*</\s*p\s*>\s*", "\n\n", text).strip()

        # naive stripping of tags, should work okay in this limited context
        text = re.sub("<[^>]+>", "", text)

        # compress and strip whitespace artifacts, except for the paragraph breaks
        text = re.sub("[ \t\r\f\v]{2,}", " ", text).strip()

        # Replace HTML entities with characters.
        text = unescape(text)

        return text

    def scan_for_bills_to_process(self):
        # Return a generator over bill_ids that need to be
        # processed.

        def get_data_path(*args):
            # Utility function to generate a part of the path
            # to data/{congress}/bills/{billtype}/{billtypenumber}/fdsys_billstatus.xml
            # given as many path elements as are provided. args
            # is a list of zero or more of congress, billtype,
            # and billtypenumber (in order).
            args = list(args)
            if len(args) > 0:
                args.insert(1, "bills")
            return os.path.join(self.storage.data_dir, *args)

        if not self.options.get('congress'):
            # Get a list of all congress directories on disk.
            # Filter out non-integer directory names, then sort on the
            # integer.
            def filter_ints(seq):
                for s in seq:
                    try:
                        yield int(s)
                    except:
                        # Not an integer.
                        continue
            congresses = sorted(filter_ints(os.listdir(get_data_path())))
        else:
            congresses = sorted([int(c) for c in self.options['congress'].split(',')])

        # walk through congresses
        for congress in congresses:
            # turn this back into a string
            congress = str(congress)

            # walk through all bill types in that congress
            # (sort by bill type so that we proceed in a stable order each run)
            for bill_type in sorted(os.listdir(get_data_path(congress))):

                # walk through each bill in that congress and bill type
                # (sort by bill number so that we proceed in a normal order)
                for bill_type_and_number in sorted(
                    os.listdir(get_data_path(congress, bill_type)),
                    key = lambda x : int(x.replace(bill_type, ""))
                    ):

                    fn = get_data_path(congress, bill_type, bill_type_and_number, Fdsys.BULK_BILLSTATUS_FILENAME)
                    if os.path.exists(fn):
                        # The FDSys bulk data file exists. Does our JSON data
                        # file need to be updated?
                        bulkfile_lastmod = self.storage.read(fn.replace(".xml", "-lastmod.txt"))
                        parse_lastmod = self.storage.read(get_data_path(congress, bill_type, bill_type_and_number, "data-fromfdsys-lastmod.txt"))
                        if bulkfile_lastmod != parse_lastmod:
                            bill_id = bill_type_and_number + "-" + congress
                            print(bill_id)
                            yield bill_id
