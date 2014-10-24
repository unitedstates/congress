import re
import logging
import datetime
import time
import json
from lxml import etree

import utils

from bill_info import sponsor_for, actions_for


# downloads amendment information from THOMAS.gov,
# parses out basic information, writes JSON to disk

def fetch_amendment(amendment_id, options):
    logging.info("\n[%s] Fetching..." % amendment_id)

    body = utils.download(
        amendment_url_for(amendment_id),
        amendment_cache_for(amendment_id, "information.html"),
        options)

    if not body:
        return {'saved': False, 'ok': False, 'reason': "failed to download"}

    if options.get("download_only", False):
        return {'saved': False, 'ok': True, 'reason': "requested download only"}

    if "Amends:" not in body:
        return {'saved': False, 'ok': True, 'reason': "orphaned amendment"}

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


def amendment_status_for(amdt):
    status = 'offered'
    status_date = amdt['introduced_at']

    for action in amdt['actions']:
        if action['type'] == 'vote':
            status = action['result']  # 'pass', 'fail'
            status_date = action['acted_at']
        if action['type'] == 'withdrawn':
            status = 'withdrawn'
            status_date = action['acted_at']

    return status, status_date


def amendment_url_for(amendment_id):
    amendment_type, number, congress = utils.split_bill_id(amendment_id)
    thomas_type = utils.thomas_types[amendment_type][0]
    congress = int(congress)
    number = int(number)
    return "http://thomas.loc.gov/cgi-bin/bdquery/z?d%03d:%s%s:" % (congress, thomas_type, number)


def amendment_cache_for(amendment_id, file):
    amendment_type, number, congress = utils.split_bill_id(amendment_id)
    return "%s/amendments/%s/%s%s/%s" % (congress, amendment_type, amendment_type, number, file)


def output_for_amdt(amendment_id, format):
    amendment_type, number, congress = utils.split_bill_id(amendment_id)
    return "%s/%s/amendments/%s/%s%s/%s" % (utils.data_dir(), congress, amendment_type, amendment_type, number, "data.%s" % format)
