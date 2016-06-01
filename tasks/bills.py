import os
import os.path
import re
import xmltodict
import json
import logging
from lxml import etree
from datetime import datetime

import tasks
from tasks import Task, make_node as parent_make_node, current_congress, format_datetime
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

    def __init__(self, options=None, config=None):
        super(Bills, self).__init__(options, config)
        self.bill_types = filter(None, set(self.options.get("bill_types", '').split(","))) or self.BILL_TYPES.keys()
        self.congress = self.options.get('congress', current_congress())
        self.bill_id = self.options.get('bill_id', None)

    def run(self):
        if self.bill_id:
            return self.write_legacy_dict_to_disk(self.bill_id)
        else:
            for bill_type in self.bill_types:
                pass # TODO traverse data directory and run convert_bulk_to_legacy_format for the bill_id

    def _path_to_billstatus_file(self, bill_id):
        bill_type, bill_number, congress = self.split_bill_id(bill_id)
        return os.path.join(self.storage.data_dir, congress, 'bills',
                            bill_type, bill_type + bill_number, Fdsys.BULK_BILLSTATUS_FILENAME)

    def write_legacy_dict_to_disk(self, bill_id):
        legacy_dict = self.convert_bulk_to_legacy_dict(bill_id)
        path = os.path.dirname(self._path_to_billstatus_file(bill_id))
        with self.storage.fs.open(path + '/data.json', 'w') as json_file:
            json_file.write(unicode(json.dumps(legacy_dict, indent=2, sort_keys=True)))
        # TODO convert to xml and write
        #with self.storage.fs.open(path + '/data.xml', 'w') as xml_file:
        #    xml_file.write(self._convert_legacy_dict_to_xml(legacy_dict))

    def convert_bulk_xml_to_dict(self, bill_id):
        with self.storage.fs.open(self._path_to_billstatus_file(bill_id)) as fdsys_billstatus:
            return xmltodict.parse(fdsys_billstatus.read())

    def convert_bulk_to_legacy_dict(self, bill_id):
        bill_type, bill_number, congress = self.split_bill_id(bill_id)
        complete_xml_as_dict = self.convert_bulk_xml_to_dict(bill_id)
        bill_dict = complete_xml_as_dict['billStatus']['bill']

        legacy_json = {
            'bill_id': bill_id,
            'bill_type': bill_type,
            'number': bill_number,
            'congress': congress,

            'url': self.billstatus_url_for(bill_id),

            'introduced_at': bill_dict.get('introducedDate', ''),
            'by_request': tasks.safeget(bill_dict, None, 'sponsors', 'item', 'byRequestType') is not None,
            'sponsor': self._build_legacy_sponsor_dict(tasks.safeget(bill_dict, None, 'sponsors', 'item')),
            'cosponsors': self._build_legacy_cosponsor_list(bill_dict['cosponsors']['item']),

            'actions': self._build_legacy_actions_list(bill_dict['actions']['item']),
            'history': self._build_legacy_history(bill_dict['actions']['item']),
            'status': self._build_legacy_status(bill_dict['actions']['item']),
            'status_at': self._build_legacy_status_at(bill_dict['actions']['item']),
            'enacted_as': self._build_legacy_enacted_as(bill_dict['actions']['item']),

            'titles': self._build_legacy_titles(bill_dict['titles']['item']),
            'official_title': bill_dict['title'],
            'short_title': self._build_legacy_short_titles(bill_dict['titles']['item']),
            'popular_title': None,

            'summary': bill_dict['summaries']['billSummaries']['item']['text'],
            'subjects_top_term': bill_dict['primarySubject']['name'],
            'subjects': [item['name'] for item in bill_dict['subjects']['billSubjects']['otherSubjects']['item']],

            'related_bills': self._build_legacy_related_bills_list(tasks.safeget(bill_dict, [], 'relatedBills', 'item')),
            'committees': self._build_legacy_committees_list(tasks.safeget(bill_dict, [], 'committees', 'billCommittees', 'item')),
            'amendments': self._build_legacy_amendments_list(tasks.safeget(bill_dict, [], 'amendments', 'amendment')),

            'updated_at': bill_dict.get('updateDate', ''),
        }

        return legacy_json

    @staticmethod
    def _build_legacy_sponsor_dict(sponsor_dict):
        extract_district_state = re.search(r'\[(\w+)-(\w+)(-\d{1,2})?\]', sponsor_dict['fullName'])
        return {
            'title': sponsor_dict['fullName'][0:3],
            'name': '{0}, {1}'.format(sponsor_dict['lastName'].capitalize(), sponsor_dict['firstName'].capitalize()),
            'district': extract_district_state.group(3),
            'state': extract_district_state.group(2),
            'thomas_id': None,
            'bioguide_id': sponsor_dict['bioguideId'],
            'type': 'person'
        }

    @staticmethod
    def _build_legacy_cosponsor_list(cosponsors_list):
        def build_dict(item):
            cosponsor_dict = Bills._build_legacy_sponsor_dict(item)
            cosponsor_dict.update({
                'sponsored_at': item['sponsorshipDate'],
                'withdrawn_at': item['sponsorshipWithdrawnDate'],
                'original_cosponsor': item['isOriginalCosponsor'] == 'True'
            })
            return cosponsor_dict

        return [build_dict(cosponsor) for cosponsor in cosponsors_list]

    @staticmethod
    def _build_legacy_actions_list(action_list):
        def build_dict(item):
            print item
            action_dict = {
                'acted_at': item.get('actionDate', ''),
                'acted_time': item.get('actionTime', ''),
                'action_code': item.get('actionCode', ''),
                'committees': [tasks.safeget(item, '', 'committee', 'systemCode')],  # TODO: committee symbols are different
                'references': Bills._action_for(item.get('text',''))[1],
                'type': item.get('type', ''),  # TODO
                'status': '', #  TODO
                'text': item.get('text', ''),
                'where': tasks.safeget(item, '', 'sourceSystem', 'name'), #  TODO
            }
            return action_dict

        return [build_dict(action) for action in action_list]

    @staticmethod
    def _build_legacy_history(action_list):
        # TODO
        pass

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
        # TODO
        pass

    @staticmethod
    def _build_legacy_short_titles(title_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_committees_list(committee_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_amendments_list(amendment_list):
        # TODO
        pass

    @staticmethod
    def _build_legacy_related_bills_list(related_bills_list):
        def build_dict(item):
            return {
                'reason': item['relationshipDetail']['item']['type'].replace('bill', '').strip().lower(),
                'bill_id': '{0}{1}-{2}'.format(item['type'].replace('.', '').lower(), item['number'], item['congress']),
                'type': 'bill',
                'identified_by': item['relationshipDetail']['item']['identifiedBy']
            }

        return [build_dict(related_bill) for related_bill in related_bills_list]

    @staticmethod
    def _convert_legacy_dict_to_xml(legacy_dict):
        # TODO
        pass

    # clean text, pull out the action type, any other associated metadata with an action
    @staticmethod
    def _action_for(text):
        # strip out links
        text = re.sub(r"</?[Aa]( \S.*?)?>", "", text)

        # remove and extract references
        references = []
        match = re.search("\s+\(([^)]+)\)\s*$", text)
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

    def output_bill(self, bill):
        logging.info("[%s] Writing to disk..." % bill['bill_id'])

        # output JSON - so easy!
        self.storage.write(
            json.dumps(bill, sort_keys=True, indent=2, default=format_datetime),
            self.output_for_bill(bill['bill_id'], "json"),
            options=self.options,
        )

        # output XML
        govtrack_type_codes = {'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc'}
        root = etree.Element("bill")
        root.set("session", bill['congress'])
        root.set("type", govtrack_type_codes[bill['bill_type']])
        root.set("number", bill['number'])
        root.set("updated", format_datetime(bill['updated_at']))

        def make_node(parent, tag, text, **attrs):
            if self.options.get("govtrack", False):
                # Rewrite thomas_id attributes as just id with GovTrack person IDs.
                attrs2 = {}
                for k,v in attrs.items():
                    if v:
                        if k == "thomas_id":
                            pass
                            # TODO: Govtrack conversion method is very, very complicated.
                            # remap "thomas_id" attributes to govtrack "id"
                            #k = "id"
                            #v = str(utils.get_govtrack_person_id('thomas', v))
                        attrs2[k] = v
                attrs = attrs2

            return parent_make_node(parent, tag, text, **attrs)

        # for American Memory Century of Lawmaking bills...
        for source in bill.get("sources", []):
            n = make_node(root, "source", "")
            for k, v in sorted(source.items()):
                if k == "source":
                    n.text = v
                elif k == "source_url":
                    n.set("url", v)
                else:
                    n.set(k, unicode(v))
        if "original_bill_number" in bill:
            make_node(root, "bill-number", bill["original_bill_number"])

        make_node(root, "state", bill['status'], datetime=bill['status_at'])
        old_status = make_node(root, "status", None)
        make_node(old_status, "introduced" if bill['status'] in ("INTRODUCED", "REFERRED") else "unknown", None, datetime=bill['status_at'])  # dummy for the sake of comparison

        make_node(root, "introduced", None, datetime=bill['introduced_at'])
        titles = make_node(root, "titles", None)
        for title in bill['titles']:
            n = make_node(titles, "title", title['title'])
            n.set("type", title['type'])
            if title['as']:
                n.set("as", title['as'])
            if title['is_for_portion']:
                n.set("partial", "1")

        if bill['sponsor']:
            # TODO: Sponsored by committee?
            make_node(root, "sponsor", None, thomas_id=bill['sponsor']['thomas_id'])
        else:
            make_node(root, "sponsor", None)

        cosponsors = make_node(root, "cosponsors", None)
        for cosp in bill['cosponsors']:
            n = make_node(cosponsors, "cosponsor", None, thomas_id=cosp["thomas_id"])
            if cosp["sponsored_at"]:
                n.set("joined", cosp["sponsored_at"])
            if cosp["withdrawn_at"]:
                n.set("withdrawn", cosp["withdrawn_at"])

        actions = make_node(root, "actions", None)
        for action in bill['actions']:
            a = make_node(actions,
                          action['type'] if action['type'] in ("vote", "vote-aux", "calendar", "topresident", "signed", "enacted", "vetoed") else "action",
                          None,
                          datetime=action['acted_at'])
            if action.get("status"):
                a.set("state", action["status"])
            if action['type'] in ('vote', 'vote-aux'):
                a.clear()  # re-insert date between some of these attributes
                a.set("how", action["how"])
                a.set("type", action["vote_type"])
                if action.get("roll") != None:
                    a.set("roll", action["roll"])
                a.set("datetime", format_datetime(action['acted_at']))
                a.set("where", action["where"])
                a.set("result", action["result"])
                if action.get("suspension"):
                    a.set("suspension", "1")
                if action.get("status"):
                    a.set("state", action["status"])
            if action['type'] == 'calendar' and "calendar" in action:
                a.set("calendar", action["calendar"])
                if action["under"]:
                    a.set("under", action["under"])
                if action["number"]:
                    a.set("number", action["number"])
            if action['type'] == 'enacted':
                a.clear()  # re-insert date between some of these attributes
                a.set("number", "%s-%s" % (bill['congress'], action["number"]))
                a.set("type", action["law"])
                a.set("datetime", format_datetime(action['acted_at']))
                if action.get("status"):
                    a.set("state", action["status"])
            if action['type'] == 'vetoed':
                if action.get("pocket"):
                    a.set("pocket", "1")
            if action.get('text'):
                make_node(a, "text", action['text'])
            if action.get('in_committee'):
                make_node(a, "committee", None, name=action['in_committee'])
            for cr in action['references']:
                make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])

        committees = make_node(root, "committees", None)
        for cmt in bill['committees']:
            make_node(committees, "committee", None, code=(cmt["committee_id"] + cmt["subcommittee_id"]) if cmt.get("subcommittee_id", None) else cmt["committee_id"], name=cmt["committee"], subcommittee=cmt.get("subcommittee").replace("Subcommittee on ", "") if cmt.get("subcommittee") else "", activity=", ".join(c.title() for c in cmt["activity"]))

        relatedbills = make_node(root, "relatedbills", None)
        for rb in bill['related_bills']:
            if rb['type'] == "bill":
                rb_bill_type, rb_number, rb_congress = Bills.split_bill_id(rb['bill_id'])
                make_node(relatedbills, "bill", None, session=rb_congress, type=govtrack_type_codes[rb_bill_type], number=rb_number, relation="unknown" if rb['reason'] == "related" else rb['reason'])

        subjects = make_node(root, "subjects", None)
        if bill['subjects_top_term']:
            make_node(subjects, "term", None, name=bill['subjects_top_term'])
        for s in bill['subjects']:
            if s != bill['subjects_top_term']:
                make_node(subjects, "term", None, name=s)

        amendments = make_node(root, "amendments", None)
        for amd in bill['amendments']:
            make_node(amendments, "amendment", None, number=amd["chamber"] + str(amd["number"]))

        if bill.get('summary'):
            make_node(root, "summary", re.sub(r"^0|(/)0", lambda m: m.group(1), datetime.strftime(datetime.strptime(bill['summary']['date'], "%Y-%m-%d"), "%m/%d/%Y")) + "--" + bill['summary'].get('as', '?') + ".\n" + bill['summary']['text'])  # , date=bill['summary'].get('date'), status=bill['summary'].get('as'))

        self.storage.write(
            etree.tostring(root, pretty_print=True),
            self.output_for_bill(bill['bill_id'], "xml"),
            options=self.options
        )
