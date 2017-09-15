import re
import logging
import datetime
import time
import json
from lxml import etree

import utils

from bill_info import sponsor_for as sponsor_for_bill, action_for

def process_amendment(amdt_data, bill_id, options):
    amdt = build_amendment_json_dict(amdt_data, options)
    path = output_for_amdt(amdt['amendment_id'], "json")

    logging.info("[%s] Saving %s to %s..." % (bill_id, amdt['amendment_id'], path))

    # output JSON - so easy!
    utils.write(
        json.dumps(amdt, sort_keys=True, indent=2, default=utils.format_datetime),
        path
    )

    with open(output_for_amdt(amdt['amendment_id'], "xml"), 'wb') as xml_file:
        xml_file.write(create_govtrack_xml(amdt, options))

def build_amendment_json_dict(amdt_dict, options):
    # good set of tests for each situation:
    # samdt712-113 - amendment to bill
    # samdt112-113 - amendment to amendment on bill
    # samdt4904-111 - amendment to treaty
    # samdt4922-111 - amendment to amendment to treaty

    amendment_id = build_amendment_id(amdt_dict['type'].lower(), amdt_dict['number'], amdt_dict['congress'])

    amends_bill = amends_bill_for(amdt_dict.get('amendedBill'))  # almost always present
    amends_treaty = None # amends_treaty_for(amdt_dict) # the bulk data does not provide amendments to treaties (THOMAS did)
    amends_amendment = amends_amendment_for(amdt_dict.get('amendedAmendment'))  # sometimes present
    if not amends_bill and not amends_treaty:
        raise Exception("Choked finding out what bill or treaty the amendment amends.")

    actions = actions_for(amdt_dict['actions']['actions'])

    amdt = {
        'amendment_id': amendment_id,
        'amendment_type': amdt_dict['type'].lower(),
        'chamber': amdt_dict['type'][0].lower(),
        'number': int(amdt_dict['number']),
        'congress': amdt_dict['congress'],

        'amends_bill': amends_bill,
        'amends_treaty': amends_treaty,
        'amends_amendment': amends_amendment,

        'sponsor': sponsor_for(amdt_dict['sponsors']['item'][0], amdt_dict['type'].lower()),

        'purpose': amdt_dict['purpose'][0] if type(amdt_dict['purpose']) is list else amdt_dict['purpose'],

        'introduced_at': amdt_dict['submittedDate'][:10],
        'actions': actions,

        'updated_at':  amdt_dict['updateDate'],
    }

    # duplicate attributes creates lists when parsed, this block deduplicates
    if 'description' in amdt_dict:
        amdt['description'] = amdt_dict['description']
        if type(amdt_dict['description']) is list:
            amdt['description'] = amdt['description'][0]

    if amdt_dict['type'][0].lower() == 's':
        amdt['proposed_at'] = amdt_dict['proposedDate']

    # needs to come *after* the setting of introduced_at
    amdt['status'], amdt['status_at'] = amendment_status_for(amdt)

    return amdt


def create_govtrack_xml(amdt, options):
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
        v = amdt['sponsor']['bioguide_id']
        if not options.get("govtrack", False):
            make_node(root, "sponsor", None, bioguide_id=v)
        else:
            v = str(utils.translate_legislator_id('bioguide', v, 'govtrack'))
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

    return etree.tostring(root, pretty_print=True)


def build_amendment_id(amdt_type, amdt_number, congress):
    return "%s%s-%s" % (amdt_type, amdt_number, congress)

def amends_bill_for(amends_bill):
    from bills import build_bill_id
    bill_id = build_bill_id(amends_bill['type'].lower(), amends_bill['number'], amends_bill['congress'])
    return {
        'bill_id': bill_id,
        'bill_type': amends_bill['type'].lower(),
        'congress': int(amends_bill['congress']),
        'number': int(amends_bill['number'])
    }

def amends_amendment_for(amends_amdt):
    if amends_amdt is None:
        return None

    amdt_id = build_amendment_id(amends_amdt['type'].lower(), amends_amdt['number'], amends_amdt['congress'])
    return {
        'amendment_id': amdt_id,
        'amendment_type': amends_amdt.get('type','').lower(),
        'congress': int(amends_amdt.get('congress','')),
        'number': int(amends_amdt.get('number','')),
        'purpose': amends_amdt.get('purpose', ''),
        'description': amends_amdt.get('description','')
    }


def actions_for(action_list):
    if action_list is None: return [] # no actions
    actions = [action_for(action) for action in action_list['item']]
    parse_amendment_actions(actions)
    return actions

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

def sponsor_for(sponsor, amendment_type):
    if sponsor.get('bioguideId') is None:
        # A committee can sponsor an amendment!
        # Change e.g. "Rules Committee" to "House Rules" for the committee name,
        # for backwards compatibility.
        name = re.sub(r"(.*) Committee$", ("House" if (amendment_type[0] == "h") else "Senate" ) + r" \1", sponsor['name'])
        return {
            "type": "committee",
            "name": name,
            #"committee_id": None, # TODO
        }

    return sponsor_for_bill(sponsor)

def output_for_amdt(amendment_id, format):
    amendment_type, number, congress = utils.split_bill_id(amendment_id)
    return "%s/%s/amendments/%s/%s%s/%s" % (utils.data_dir(), congress, amendment_type, amendment_type, number, "data.%s" % format)
