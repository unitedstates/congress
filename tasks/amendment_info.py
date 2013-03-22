import re, logging, datetime, time, json
from lxml import etree
from lxml.html import fromstring
from amendment_text import fetch_amendment_text
import utils

from bill_info import sponsor_for, actions_for

# TODO:
# "TEXT OF AMENDMENT AS SUBMITTED"
# "COSPONSORS"

def fetch_amendment(amdt_id, options):
  logging.info("\n[%s] Fetching..." % amdt_id)
  
  # fetch bill details body
  body = utils.download(
    amdt_url_for(amdt_id), 
    amdt_cache_for(amdt_id, "information.html"),
    options)

  if not body:
    return {'saved': False, 'ok': False, 'reason': "failed to download"}

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}
    
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  
  actions = actions_for(body, amdt_id, is_amendment=True)
  if actions is None: actions = []
  parse_amendment_actions(actions)

  amdt = {
    'amendment_id': amdt_id,
    'amendment_type': amdt_type,
    'chamber': amdt_type[0],
    'number': number,
    'congress': congress,
    
    'amends': amends_for(body, grab_bill=False),
    'amends_bill': amends_for(body, grab_bill=True),
    'house_number': house_number_for(body),

    'offered_at': offered_at_for(body, 'offered'),
    'submitted_at': offered_at_for(body, 'submitted'),
    'proposed_at': offered_at_for(body, 'proposed'),
    'sponsor': sponsor_for(body),

    'title': amendment_simple_text_for(body, "title"),
    'description': amendment_simple_text_for(body, "description"),
    'purpose': amendment_simple_text_for(body, "purpose"),
    
    'actions': actions,

    'updated_at': datetime.datetime.fromtimestamp(time.time()),
  }
  
  set_amendment_status(amdt)
  
  output_amendment(amdt, options)

  if not options.get("fulltext", False):
    return {'ok': True, 'saved': True}

  #fetch amendment text
  fulltext = fetch_amendment_text(body, amdt, options)

  if not fulltext:    
    return {
      'ok': True,
      'saved': True,
      'fulltext': False
    }

  outpt = "%s/%s/amendments/%s/%s%s/%s" % (utils.data_dir(), congress, amdt_type, amdt_type, number, "text.txt")
  logging.info(outpt)
  logging.info("[%s] Writing full text to disk..." % amdt['amendment_id'])
  utils.write(fulltext, outpt)
  return {
    'ok': True,
    'saved': True,
    'fulltext': True
  }
    

def output_amendment(amdt, options):
  logging.info("[%s] Writing to disk..." % amdt['amendment_id'])

  # output JSON - so easy!
  utils.write(
    json.dumps(amdt, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_amdt(amdt['amendment_id'], "json")
  )

  # output XML
  govtrack_type_codes = { 'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc' }
  root = etree.Element("amendment")
  root.set("session", amdt['congress'])
  root.set("chamber", amdt['amendment_type'][0])
  root.set("number", amdt['number'])
  root.set("updated", utils.format_datetime(amdt['updated_at']))
  
  make_node = utils.make_node
  
  make_node(root, "amends", None,
    type=govtrack_type_codes[amdt["amends_bill"]["bill_type"]],
    number=str(amdt["amends_bill"]["number"]),
    sequence=str(int(amdt["house_number"][1:])) if amdt["house_number"] else "") # chop off A from the house_number
  
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

  make_node(root, "offered", None, datetime=amdt['offered_at'] if amdt['offered_at'] else amdt['submitted_at'])
      
  if amdt["title"]: make_node(root, "title", amdt["title"])
  make_node(root, "description", amdt["description"] if amdt["description"] else amdt["purpose"])
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
        if action.get("roll") != None: a.set("roll", str(action["roll"]))
      if action.get('text'): make_node(a, "text", action['text'])
      if action.get('in_committee'): make_node(a, "committee", None, name=action['in_committee'])
      for cr in action['references']:
          make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])
          
  utils.write(
    etree.tostring(root, pretty_print=True),
    output_for_amdt(amdt['amendment_id'], "xml")
  )

def house_number_for(body):
  match = re.search(r"H.AMDT.\d+</b>\n \((A\d+)\)", body, re.I)
  if match:
    return match.group(1)
  else:
    return None
    
def amends_for(body, grab_bill):
  # When an amendment amends an amendment, the bill is listed first, followed by a comma
  # and newline. Skip the bill when it exists and just parse the amendment.
  match = re.search(r"Amends: "
      + ("(?:.*\n, )?" if not grab_bill else "")
      + "<a href=\"/cgi-bin/bdquery/z\?d(\d+):([A-Z]+)(\d+):",
      body)
  if match:
    congress = int(match.group(1))
    bill_type = utils.thomas_types_2[match.group(2)]
    bill_number = int(match.group(3))
    is_bill = bill_type not in ("samdt", "hamdt")
    return {
      "document_type": "bill" if is_bill else "amendment",
      "congress": congress,
      "bill_type" if is_bill else "amendment_type": bill_type,
      "number": bill_number,
    }
  else:
    raise Exception("Choked finding what the amendment amends.")

def offered_at_for(body, offer_type):
  match = re.search(r"Sponsor:.*\n.*\(" + offer_type + " (\d+/\d+/\d+)", body, re.I)
  if match:
    date = match.group(1)
    date = datetime.datetime.strptime(date, "%m/%d/%Y")
    date = datetime.datetime.strftime(date, "%Y-%m-%d")
    return date
  else:
    return None # not all of offered/submitted/proposed will be present

def amendment_simple_text_for(body, heading):
  match = re.search(r"AMENDMENT " + heading.upper() + ":(<br />| )(.+)", body, re.I)
  if match:
    title = match.group(2).strip()
    if title == "*** TITLE NOT FOUND ***":
      return None
    return title
  else:
    return None

def parse_amendment_actions(actions):
  for action in actions:
    # House Vote
    m = re.match(r"On agreeing to the .* amendment (\(.*\) )?(Agreed to|Failed) (without objection|by [^\.:]+|by recorded vote: (\d+) - (\d+)(, \d+ Present)? \(Roll no. (\d+)\))\.", action['text'])
    if m:
      action["type"] = "vote"
      
      if m.group(2) == "Agreed to":
        action["result"] = "pass"
      else:
        action["result"] = "fail"
      
      action["how"] = m.group(3)
      if "recorded vote" in m.group(3):
        action["how"] = "roll"
        action["roll"] = int(m.group(7))
      
    # Senate Vote
    m = re.match(r"(Motion to table )?Amendment SA \d+ (as modified )?(agreed to|not agreed to) in Senate by ([^\.:\-]+|Yea-Nay( Vote)?. (\d+) - (\d+)(, \d+ Present)?. Record Vote Number: (\d+))\.", action['text'])
    if m:
      action["type"] = "vote"
      if m.group(3) == "agreed to":
        action["result"] = "pass"
        if m.group(1): # is a motion to table, so result is sort of reversed.... eeek
          action["result"] = "fail"
      else:
        if m.group(1): # is a failed motion to table, so this doesn't count as a vote on agreeing to the amendment
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
      
def set_amendment_status(amdt):
  status = 'offered'
  status_date = amdt['offered_at'] if amdt['offered_at'] else amdt['submitted_at']

  for action in amdt['actions']:
    if action['type'] == 'vote':
      status = action['result'] # 'pass', 'fail'
      status_date = action['acted_at']
    if action['type'] == 'withdrawn':
      status = 'withdrawn'
      status_date = action['acted_at']
      
  amdt['status'] = status
  amdt['status_at'] = status_date

def amdt_url_for(amdt_id):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  thomas_type = utils.thomas_types[amdt_type][0]
  congress = int(congress)
  number = int(number)
  return "http://thomas.loc.gov/cgi-bin/bdquery/D?d%03d:%d:./list/bss/d%03d%s.lst::" % (congress, number, congress, thomas_type)

def amdt_cache_for(amdt_id, file):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/amendments/%s/%s%s/%s" % (congress, amdt_type, amdt_type, number, file)

def output_for_amdt(amdt_id, format):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/%s/amendments/%s/%s%s/%s" % (utils.data_dir(), congress, amdt_type, amdt_type, number, "data.%s" % format)

