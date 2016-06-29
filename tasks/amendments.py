import utils
import logging
import json
import os
import re

#from bills import bill_ids_for, save_bill_search_state
#from bill_info import fetch_bill, output_for_bill

#from amendment_info import fetch_amendment

import tasks
from tasks import Task, make_node as parent_make_node, current_congress, format_datetime, bills
from tasks.fdsys import Fdsys
from tasks.bills import Bills


class Amendments(Task):

    def __init__(self, options=None, config=None):
        super(Amendments, self).__init__(options, config)

    def run(self):
        Bills(self.options, self.config).run()

    def extract_all_amendments(self, xml_as_dict):
        amdt_list = xml_as_dict['billStatus']['bill']['amendments']
        if amdt_list is None:  # many bills don't have amendments so let's skip this
            return
        for amdt in amdt_list['amendment']:
            amdt_dict = self.convert_to_legacy_dict(amdt)
            amdt_id = self.build_amendment_id(amdt['type'].lower(), amdt['number'], amdt['congress'])
            path = self._output_path(amdt_id)
            self.storage.mkdir_p(path)
            logging.info("[%s] Writing to %s..." % (amdt, path))
            with self.storage.fs.open(path + '/data.json', 'w') as json_file:
                json_file.write(unicode(json.dumps(amdt_dict, indent=2, sort_keys=True)))
            with self.storage.fs.open(path + '/data.xml', 'wb') as xml_file:
                pass # TODO
                # xml_file.write(self._convert_legacy_dict_to_xml(legacy_dict))

    def _output_path(self, amendment_id):
        amendment_type, amendment_number, congress = self.split_amendment_id(amendment_id)
        return os.path.join(self.storage.data_dir, congress, 'amendments',
                            amendment_type, amendment_type + amendment_number)

    def convert_to_legacy_dict(self, amdt_dict):
        amdt_id = Amendments.build_amendment_id(amdt_dict['type'].lower(), amdt_dict['number'], amdt_dict['congress'])

        actions = self.build_action_list(tasks.safeget(amdt_dict, [], 'actions', 'actions', 'item'))

        legacy_dict = {
            'actions': actions,
            'amendment_id': amdt_id,
            'amendment_type': amdt_dict['type'].lower(),
            'amends_amendment': self.build_amends_amendment_dict(amdt_dict.get('amendedAmendment', None)),
            'amends_bill': self.build_amended_bill_dict(amdt_dict.get('amendedBill')),
            'amends_treaty': None,  # TODO doesn't appear to be used in 113th and 114th congress anywhere?
            'chamber': amdt_dict['type'][0].lower(),
            'congress': amdt_dict['congress'],
            'introduced_at': amdt_dict['submittedDate'],
            'number': int(amdt_dict['number']),
            'proposed_at': amdt_dict['proposedDate'],
            'purpose': amdt_dict['purpose'][0] if type(amdt_dict['purpose']) is list else amdt_dict['purpose'],
            'sponsor': self.build_sponsor_dict(tasks.safeget(amdt_dict, None, 'sponsors', 'item', 0)),
            'updated_at': amdt_dict['updateDate']
        }

        status, status_at = self.amendment_status_for(legacy_dict)
        legacy_dict.update({'status': status, 'status_at': status_at}) # TODO date instead of datetime

        # duplicate attributes creates lists when parsed, this block deduplicates
        if 'description' in amdt_dict:
            legacy_dict['description'] = amdt_dict['description']
            if type(amdt_dict['description']) is list:
                legacy_dict['description'] = legacy_dict['description'][0]

        return legacy_dict

    @staticmethod
    def build_amendment_id(amdt_type, amdt_number, congress):
        return "%s%s-%s" % (amdt_type, amdt_number, congress)

    @staticmethod
    def split_amendment_id(amdt_id):
        return re.match("^([a-z]+)(\d+)-(\d+)$", amdt_id).groups()

    @staticmethod
    def build_action_list(action_list):

        def build_dict(item):
            text, references = Bills.action_for(item['text'] if item['text'] is not None else '' )

            return {
                'acted_at': item.get('actionDate', '') + (("T" + item['actionTime']) if item.get('actionTime') else ""),
                'action_code': item.get('actionCode', ''),
                'committees': [tasks.safeget(item, '', 'committee', 'systemCode')[0:-2].upper()],
                'references': references,
                'type': 'action',
                #'type': '',  # TODO see parse_bill_action in bill_info.py this is a mess
                #'status': '',  # TODO see parse_bill_action in bill_info.py this is a mess
                'text': text,
                #'where': '', # TODO see parse_bill_action in bill_info.py this is a mess
            }

        actions = [build_dict(action) for action in action_list]

        for action in actions:
            # House Vote
            m = re.match(r"On agreeing to the .* amendments? (\(.*\) )?(?:as (?:modified|amended) )?(Agreed to|Failed) (without objection|by [^\.:]+|by (?:recorded vote|the Yeas and Nays): (\d+) - (\d+)(, \d+ Present)? \(Roll [nN]o. (\d+)\))\.", action['text'])
            if m:
                action["where"] = "h"
                action["type"] = "vote"
                action["vote_type"] = "vote"

                if m.group(2) == "Agreed to":
                    action["result"] = "pass"
                else:
                    action["result"] = "fail"

                action["how"] = m.group(3)
                if "recorded vote" in m.group(3) or "the Yeas and Nays" in m.group(3):
                    action["how"] = "roll"
                    action["roll"] = int(m.group(7))

            # Senate Vote
            m = re.match(r"(Motion to table )?Amendment SA \d+(?:, .*?)? (as modified )?(agreed to|not agreed to) in Senate by ([^\.:\-]+|Yea-Nay( Vote)?. (\d+) - (\d+)(, \d+ Present)?. Record Vote Number: (\d+))\.", action['text'])
            if m:
                action["type"] = "vote"
                action["vote_type"] = "vote"
                action["where"] = "s"

                if m.group(3) == "agreed to":
                    action["result"] = "pass"
                    if m.group(1):  # is a motion to table, so result is sort of reversed.... eeek
                        action["result"] = "fail"
                else:
                    if m.group(1):  # is a failed motion to table, so this doesn't count as a vote on agreeing to the amendment
                        continue
                    action["result"] = "fail"

                action["how"] = m.group(4)
                if "Yea-Nay" in m.group(4):
                    action["how"] = "roll"
                    action["roll"] = int(m.group(9))

            # Withdrawn
            m = re.match(r"Proposed amendment SA \d+ withdrawn in Senate", action['text'])
            if m:
                action['type'] = 'withdrawn'

        return actions

    @staticmethod
    def build_amends_amendment_dict(amends_amdt):
        if amends_amdt is None:
            return None

        amdt_id = Amendments.build_amendment_id(amends_amdt['type'].lower(), amends_amdt['number'], amends_amdt['congress'])
        return {
            'amendment_id': amdt_id,
            'amendment_type': amends_amdt.get('type','').lower(),
            'congress': int(amends_amdt.get('congress','')),
            'number': int(amends_amdt.get('number','')),
            'purpose': amends_amdt.get('purpose', ''),
            'description': amends_amdt.get('description','')
        }

    @staticmethod
    def build_amended_bill_dict(amends_bill):
        bill_id = Bills.build_bill_id(amends_bill['type'].lower(), amends_bill['number'], amends_bill['congress'])
        return {
            'bill_id': bill_id,
            'bill_type': amends_bill['type'].lower(),
            'congress': int(amends_bill['congress']),
            'number': int(amends_bill['number'])
        }

    def build_sponsor_dict(self, sponsor):
        # check for committee sponsorship
        if sponsor.get('bioguideId') is None:
            return {}  # TODO committee lookup

        # TODO: Don't do regex matching here. Find another way. Is there a better way?
        m = re.match(r'(?P<title>(Rep|Sen))\. (?P<name>.*) \[(?P<party>[DRI])-(?P<state>[A-Z][A-Z])(-(?P<district>\d{1,2}|At Large))?\]$',
            sponsor['fullName'])

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
            'thomas_id': self.lookup_legislator_by_id('bioguide', sponsor['bioguideId'])['id']['thomas'],  # TODO: Remove.
            'bioguide_id': sponsor['bioguideId'],
            'type': 'person'
        }

    def amendment_status_for(self, amdt_dict):
        status = 'offered'
        status_date = amdt_dict['introduced_at']

        for action in amdt_dict['actions']:
            if action['type'] == 'vote':
                status = action['result']  # 'pass', 'fail'
                status_date = action['acted_at']
            if action['type'] == 'withdrawn':
                status = 'withdrawn'
                status_date = action['acted_at']

        return status, status_date

    def amendment_cache_for(self, amendment_id, file):
        amendment_type, number, congress = utils.split_bill_id(amendment_id)
        return "%s/amendments/%s/%s%s/%s" % (congress, amendment_type, amendment_type, number, file)

    def output_for_amdt(self, amendment_id, format):
        amendment_type, number, congress = utils.split_bill_id(amendment_id)
        return "%s/%s/amendments/%s/%s%s/%s" % (self.storage.data_dir, congress, amendment_type, amendment_type, number, "data.%s" % format)



    """
    def fetch_amendment(amendment_id, options):

        amendment_type, number, congress = utils.split_bill_id(amendment_id)

        actions = actions_for(body, amendment_id, is_amendment=True)
        if actions is None:
            actions = []
        parse_amendment_actions(actions)

        chamber = amendment_type[0]

        # good set of tests for each situation:
        # samdt712-113 - amendment to bill
        # samdt112-113 - amendment to amendment on bill
        # samdt4904-111 - amendment to treaty
        # samdt4922-111 - amendment to amendment to treaty

        amends_bill = amends_bill_for(body)  # almost always present
        amends_treaty = amends_treaty_for(body)  # present if bill is missing
        amends_amendment = amends_amendment_for(body)  # sometimes present
        if not amends_bill and not amends_treaty:
            raise Exception("Choked finding out what bill or treaty the amendment amends.")

        amdt = {
            'amendment_id': amendment_id,
            'amendment_type': amendment_type,
            'chamber': chamber,
            'number': int(number),
            'congress': congress,

            'amends_bill': amends_bill,
            'amends_treaty': amends_treaty,
            'amends_amendment': amends_amendment,

            'sponsor': sponsor_for(body),

            'description': amendment_simple_text_for(body, "description"),
            'purpose': amendment_simple_text_for(body, "purpose"),

            'actions': actions,

            'updated_at': datetime.datetime.fromtimestamp(time.time()),
        }

        if chamber == 'h':
            amdt['introduced_at'] = offered_at_for(body, 'offered')
        elif chamber == 's':
            amdt['introduced_at'] = offered_at_for(body, 'submitted')
            amdt['proposed_at'] = offered_at_for(body, 'proposed')

        if not amdt.get('introduced_at', None):
            raise Exception("Couldn't find a reliable introduction date for amendment.")

        # needs to come *after* the setting of introduced_at
        amdt['status'], amdt['status_at'] = amendment_status_for(amdt)

        # only set a house_number if it's a House bill -
        # this lets us choke if it's not found.
        if amdt['chamber'] == 'h':
            # numbers found in vote XML
            # summary = amdt['purpose'] if amdt['purpose'] else amdt['description']
            # amdt['house_number'] = house_simple_number_for(amdt['amendment_id'], summary)

            if int(amdt['congress']) > 100:
                # A___-style numbers, present only starting with the 101st Congress
                amdt['house_number'] = house_number_for(body)

        output_amendment(amdt, options)

        return {'ok': True, 'saved': True}


    def output_amendment(amdt, options):
        logging.info("[%s] Writing to disk..." % amdt['amendment_id'])

        # output JSON - so easy!
        utils.write(
            json.dumps(amdt, sort_keys=True, indent=2, default=utils.format_datetime),
            output_for_amdt(amdt['amendment_id'], "json")
        )

        # output XML
        govtrack_type_codes = {'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc'}
        root = etree.Element("amendment")
        root.set("session", amdt['congress'])
        root.set("chamber", amdt['amendment_type'][0])
        root.set("number", str(amdt['number']))
        root.set("updated", utils.format_datetime(amdt['updated_at']))

        make_node = utils.make_node

        if amdt.get("amends_bill", None):
            make_node(root, "amends", None,
                      type=govtrack_type_codes[amdt["amends_bill"]["bill_type"]],
                      number=str(amdt["amends_bill"]["number"]),
                      sequence=str(amdt["house_number"]) if amdt.get("house_number", None) else "")
        elif amdt.get("amends_treaty", None):
            make_node(root, "amends", None,
                      type="treaty",
                      number=str(amdt["amends_treaty"]["number"]))

        make_node(root, "status", amdt['status'], datetime=amdt['status_at'])

        if amdt['sponsor'] and amdt['sponsor']['type'] == 'person':
            v = amdt['sponsor']['thomas_id']
            if not options.get("govtrack", False):
                make_node(root, "sponsor", None, thomas_id=v)
            else:
                v = str(utils.get_govtrack_person_id('thomas', v))
                make_node(root, "sponsor", None, id=v)
        elif amdt['sponsor'] and amdt['sponsor']['type'] == 'committee':
            make_node(root, "sponsor", None, committee=amdt['sponsor']['name'])
        else:
            make_node(root, "sponsor", None)

        make_node(root, "offered", None, datetime=amdt['introduced_at'])

        make_node(root, "description", amdt["description"] if amdt["description"] else amdt["purpose"])
        if amdt["description"]:
            make_node(root, "purpose", amdt["purpose"])

        actions = make_node(root, "actions", None)
        for action in amdt['actions']:
            a = make_node(actions,
                          action['type'] if action['type'] in ("vote",) else "action",
                          None,
                          datetime=action['acted_at'])
            if action['type'] == 'vote':
                a.set("how", action["how"])
                a.set("result", action["result"])
                if action.get("roll") != None:
                    a.set("roll", str(action["roll"]))
            if action.get('text'):
                make_node(a, "text", action['text'])
            if action.get('in_committee'):
                make_node(a, "committee", None, name=action['in_committee'])
            for cr in action['references']:
                make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])

        utils.write(
            etree.tostring(root, pretty_print=True),
            output_for_amdt(amdt['amendment_id'], "xml")
        )


    # assumes this is a House amendment, and it should choke if it doesn't find a number
    def house_number_for(body):
        match = re.search(r"H.AMDT.\d+</b>\n \(A(\d+)\)", body, re.I)
        if match:
            return int(match.group(1))
        else:
            raise Exception("Choked finding a House amendment A___ number.")

    # def house_simple_number_for(amdt_id, purpose):
    # No purpose, so no number.
    #   if purpose is None: return None

    # Explicitly no number.
    #   if re.match("Pursuant to the provisions of .* the amendment in the nature of a substitute consisting (of )?the text of (the )?Rules Committee Print .* (is|shall be) considered as adopted.", purpose): return None
    #   if re.match("Pursuant to the provisions of .* the .*amendment printed in .* is considered as adopted.", purpose): return None
    #   if re.match(r"An amendment (in the nature of a substitute consisting of the text of Rules Committee Print \d+-\d+ )?printed in (part .* of )?House Report ", purpose, re.I): return None

    #   match = re.match(r"(?:An )?(?:substitute )?amendment (?:in the nature of a substitute )?numbered (\d+) printed in (part .* of )?(House Report|the Congressional Record) ", purpose, re.I)
    #   if not match:
    # logging.warn("No number in purpose (%s):\n%s\n" % (amdt_id, purpose))
    #     return

    #   return int(match.group(1))


    def amends_bill_for(body):
        bill_types = set(utils.thomas_types_2.keys()) - set(['HZ', 'SP', 'SU'])
        bill_types = str.join("|", list(bill_types))
        match = re.search(r"Amends: "
                          + ("<a href=\"/cgi-bin/bdquery/z\?d(\d+):(%s)(\d+):" % bill_types),
                          body)
        if match:
            congress = int(match.group(1))
            bill_type = utils.thomas_types_2[match.group(2)]
            bill_number = int(match.group(3))
            bill_id = "%s%i-%i" % (bill_type, bill_number, congress)
            return {
                "bill_id": bill_id,
                "congress": congress,
                "bill_type": bill_type,
                "number": bill_number
            }


    def amends_amendment_for(body):
        amendment_types = str.join("|", ['HZ', 'SP', 'SU'])
        match = re.search(r"Amends: "
                          + "(?:.*\n, )?"
                          + ("<a href=\"/cgi-bin/bdquery/z\?d(\d+):(%s)(\d+):" % amendment_types),
                          body)
        if match:
            congress = int(match.group(1))
            amendment_type = utils.thomas_types_2[match.group(2)]
            amendment_number = int(match.group(3))
            amendment_id = "%s%i-%i" % (amendment_type, amendment_number, congress)

            if amendment_type not in ("samdt", "supamdt", "hamdt"):
                raise Exception("Choked on a bad detection of an amendment this amends.")

            return {
                "amendment_id": amendment_id,
                "congress": congress,
                "amendment_type": amendment_type,
                "number": amendment_number
            }


    def amends_treaty_for(body):
        match = re.search(r"Amends: "
                          + "(?:.*\n, )?"
                          + "Treaty <a href=\"/cgi-bin/ntquery/z\?trtys:(\d+)TD(\d+?)A?:",
                          body)
        # don't know what the "A" is at the end of the url, but it's present in samdt3-100
        if match:
            congress = int(match.group(1))
            treaty_number = int(match.group(2))
            treaty_id = "treaty%i-%i" % (treaty_number, congress)
            return {
                "treaty_id": treaty_id,
                "congress": congress,
                "number": treaty_number
            }


    def offered_at_for(body, offer_type):
        match = re.search(r"Sponsor:.*\n.*\(" + offer_type + " (\d+/\d+/\d+)", body, re.I)
        if match:
            date = match.group(1)
            date = datetime.datetime.strptime(date, "%m/%d/%Y")
            date = datetime.datetime.strftime(date, "%Y-%m-%d")
            return date
        else:
            return None  # not all of offered/submitted/proposed will be present


    def amendment_simple_text_for(body, heading):
        match = re.search(r"AMENDMENT " + heading.upper() + ":(<br />| )\n*(.+)", body, re.I)
        if match:
            text = match.group(2).strip()

            # naive stripping of tags, should work okay in this limited context
            text = re.sub("<[^>]+>", "", text)

            if "Purpose will be available when the amendment is proposed for consideration." in text:
                return None
            return text
        else:
            return None


    def parse_amendment_actions(actions):
        for action in actions:
            # House Vote
            m = re.match(r"On agreeing to the .* amendments? (\(.*\) )?(?:as (?:modified|amended) )?(Agreed to|Failed) (without objection|by [^\.:]+|by (?:recorded vote|the Yeas and Nays): (\d+) - (\d+)(, \d+ Present)? \(Roll [nN]o. (\d+)\))\.", action['text'])
            if m:
                action["where"] = "h"
                action["type"] = "vote"
                action["vote_type"] = "vote"

                if m.group(2) == "Agreed to":
                    action["result"] = "pass"
                else:
                    action["result"] = "fail"

                action["how"] = m.group(3)
                if "recorded vote" in m.group(3) or "the Yeas and Nays" in m.group(3):
                    action["how"] = "roll"
                    action["roll"] = int(m.group(7))

            # Senate Vote
            m = re.match(r"(Motion to table )?Amendment SA \d+(?:, .*?)? (as modified )?(agreed to|not agreed to) in Senate by ([^\.:\-]+|Yea-Nay( Vote)?. (\d+) - (\d+)(, \d+ Present)?. Record Vote Number: (\d+))\.", action['text'])
            if m:
                action["type"] = "vote"
                action["vote_type"] = "vote"
                action["where"] = "s"

                if m.group(3) == "agreed to":
                    action["result"] = "pass"
                    if m.group(1):  # is a motion to table, so result is sort of reversed.... eeek
                        action["result"] = "fail"
                else:
                    if m.group(1):  # is a failed motion to table, so this doesn't count as a vote on agreeing to the amendment
                        continue
                    action["result"] = "fail"

                action["how"] = m.group(4)
                if "Yea-Nay" in m.group(4):
                    action["how"] = "roll"
                    action["roll"] = int(m.group(9))

            # Withdrawn
            m = re.match(r"Proposed amendment SA \d+ withdrawn in Senate", action['text'])
            if m:
                action['type'] = 'withdrawn'

    """





"""


def run(options):
    amendment_id = options.get('amendment_id', None)
    bill_id = options.get('bill_id', None)

    search_state = {}

    if amendment_id:
        amendment_type, number, congress = utils.split_bill_id(amendment_id)
        to_fetch = [amendment_id]

    elif bill_id:
        # first, crawl the bill
        bill_type, number, congress = utils.split_bill_id(bill_id)
        bill_status = fetch_bill(bill_id, options)
        if bill_status['ok']:
            bill = json.loads(utils.read(output_for_bill(bill_id, "json")))
            to_fetch = [x["amendment_id"] for x in bill["amendments"]]
        else:
            logging.error("Couldn't download information for that bill.")
            return None

    else:
        congress = options.get('congress', utils.current_congress())

        to_fetch = bill_ids_for(congress, utils.merge(options, {'amendments': True}), bill_states=search_state)
        if not to_fetch:
            if options.get("fast", False):
                logging.warn("No amendments changed.")
            else:
                logging.error("Error figuring out which amendments to download, aborting.")

            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    if options.get('pages_only', False):
        return None

    logging.warn("Going to fetch %i amendments from congress #%s" % (len(to_fetch), congress))
    saved_amendments = utils.process_set(to_fetch, fetch_amendment, options)

    # keep record of the last state of all these amendments, for later fast-searching
    save_bill_search_state(saved_amendments, search_state)
"""