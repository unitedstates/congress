import utils
from utils import log
import re
import json
from lxml import etree
import time, datetime
from lxml.html import fromstring

# can be run on its own, just require a bill_id
def run(options):
  bill_id = options.get('bill_id', None)
  
  if bill_id:
    result = fetch_bill(bill_id, options)
    log("\n%s" % result)
  else:
    log("To run this task directly, supply a bill_id.")


# download and cache landing page for bill
# can raise an exception under various conditions
def fetch_bill(bill_id, options):
  log("\n[%s] Fetching..." % bill_id)


  body = utils.download(
    bill_url_for(bill_id), 
    bill_cache_for(bill_id, "information.html"),
    options.get('force', False))

  if not body:
    return {'saved': False, 'ok': False, 'reason': "failed to download"}

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}

  if reserved_for_speaker(body):
    log("[%s] Reserved for the speaker, not a real bill, skipping..." % bill_id)
    return {'saved': False, 'ok': True, 'reason': "reserved for the speaker"}

  # conditions where we want to parse the bill from multiple pages instead of one:
  # 1) the all info page is truncated (~5-10 bills a congress)
  #     e.g. s1867-112, hr2112-112, s3240-112
  if "</html>" not in body:
    log("[%s] Main page truncated, fetching many pages..." % bill_id)
    bill = parse_bill_split(bill_id, body, options)

  # 2) there are > 150 amendments, use undocumented amendments list (~5-10 bills a congress)
  #     e.g. hr3590-111, sconres13-111, s3240-112
  elif too_many_amendments(body):
    log("[%s] Too many amendments, fetching many pages..." % bill_id)
    bill = parse_bill_split(bill_id, body, options)

  # 3) when I feel like it
  elif options.get('force_split', False):
    log("[%s] Forcing a split, fetching many pages..." % bill_id)
    bill = parse_bill_split(bill_id, body, options)

  # Otherwise, get the bill's data from a single All Information page
  else:
    bill = parse_bill(bill_id, body, options)

  output_bill(bill, options)

  return {'ok': True, 'saved': True}


def parse_bill(bill_id, body, options):
  bill_type, number, congress = utils.split_bill_id(bill_id)

  # parse everything out of the All Information page
  introduced_at = introduced_at_for(body)
  sponsor = sponsor_for(body)
  cosponsors = cosponsors_for(body)
  summary = summary_for(body)
  titles = titles_for(body)
  actions = actions_for(body)
  related_bills = related_bills_for(body, congress)
  subjects = subjects_for(body)
  committees = committees_for(body)
  amendments = amendments_for(body, bill_id)

  return process_bill(bill_id, options, introduced_at, sponsor, cosponsors, 
    summary, titles, actions, related_bills, subjects, committees, amendments)


# parse information pieced together from various pages
def parse_bill_split(bill_id, body, options):
  bill_type, number, congress = utils.split_bill_id(bill_id)

  # get some info out of the All Info page, since we already have it
  introduced_at = introduced_at_for(body)
  sponsor = sponsor_for(body)
  subjects = subjects_for(body)

  # cosponsors page
  cosponsors_body = utils.download(
    bill_url_for(bill_id, "P"), 
    bill_cache_for(bill_id, "cosponsors.html"),
    options.get('force', False))
  cosponsors_body = utils.unescape(cosponsors_body)
  cosponsors = cosponsors_for(cosponsors_body)

  # summary page
  summary_body = utils.download(
    bill_url_for(bill_id, "D"), 
    bill_cache_for(bill_id, "summary.html"),
    options.get('force', False))
  summary_body = utils.unescape(summary_body)
  summary = summary_for(summary_body)

  # titles page
  titles_body = utils.download(
    bill_url_for(bill_id, "T"), 
    bill_cache_for(bill_id, "titles.html"),
    options.get('force', False))
  titles_body = utils.unescape(titles_body)
  titles = titles_for(titles_body)

  # actions page
  actions_body = utils.download(
    bill_url_for(bill_id, "X"), 
    bill_cache_for(bill_id, "actions.html"),
    options.get('force', False))
  actions_body = utils.unescape(actions_body)
  actions = actions_for(actions_body)

  related_bills_body = utils.download(
    bill_url_for(bill_id, "K"), 
    bill_cache_for(bill_id, "related_bills.html"),
    options.get('force', False))
  related_bills_body = utils.unescape(related_bills_body)
  related_bills = related_bills_for(related_bills_body, congress)
  
  amendments_body = utils.download(
    bill_url_for(bill_id, "A"), 
    bill_cache_for(bill_id, "amendments.html"),
    options.get('force', False))
  amendments_body = utils.unescape(amendments_body)
  amendments = amendments_for_standalone(amendments_body, bill_id)

  committees_body = utils.download(
    bill_url_for(bill_id, "C"), 
    bill_cache_for(bill_id, "committees.html"),
    options.get('force', False))
  committees_body = utils.unescape(committees_body)
  committees = committees_for(committees_body)

  return process_bill(bill_id, options, introduced_at, sponsor, cosponsors, 
    summary, titles, actions, related_bills, subjects, committees, amendments)


# take the initial parsed content, extract more information, assemble output data
def process_bill(bill_id, options,
  introduced_at, sponsor, cosponsors, 
  summary, titles, actions, related_bills, subjects, committees, amendments):
  
  bill_type, number, congress = utils.split_bill_id(bill_id)

  # for convenience: extract out current title of each type
  official_title = current_title_for(titles, "official")
  short_title = current_title_for(titles, "short")
  popular_title = current_title_for(titles, "popular")

  # add metadata to each action, establish current status
  actions = process_actions(actions, bill_id, official_title, introduced_at)

  # pull out latest status change and the date of it
  status, status_date = latest_status(actions)
  if not status: # default to introduced
    status = "INTRODUCED"
    status_date = introduced_at

  # pull out some very useful history information from the actions
  history = history_from_actions(actions)

  slip_law = slip_law_from(actions)

  return {
    'bill_id': bill_id,
    'bill_type': bill_type,
    'number': number,
    'congress': congress,

    'introduced_at': introduced_at,
    'sponsor': sponsor,
    'cosponsors': cosponsors,

    'actions': actions,
    'history': history,
    'status': status,
    'status_at': status_date,
    'enacted_as': slip_law,
    
    'titles': titles,
    'official_title': official_title,
    'short_title': short_title,
    'popular_title': popular_title,

    'summary': summary,
    'subjects': subjects,

    'related_bills': related_bills,
    'committees': committees,
    'amendments': amendments,

    'updated_at': datetime.datetime.fromtimestamp(time.time()),
  }

def output_bill(bill, options):
  log("[%s] Writing to disk..." % bill['bill_id'])

  # output JSON - so easy!
  utils.write(
    json.dumps(bill, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_bill(bill['bill_id'], "json")
  )

  # output XML
  root = etree.Element("bill")
  root.set("congress", bill['congress'])
  root.set("type", bill['bill_type'])
  root.set("number", bill['number'])
  root.set("updated", utils.format_datetime(bill['updated_at']))
  
  def make_node(parent, tag, text, **attrs):
  	  n = etree.Element(tag)
  	  parent.append(n)
  	  n.text = text
  	  for k, v in attrs.items():
  	  	  if v:
  	  	  	  n.set(k.replace("___", ""), v)
	  return n
  
  make_node(root, "status", bill['status'], datetime=utils.format_datetime(bill['status_at']))
  make_node(root, "introduced", None, datetime=bill['introduced_at'])
  titles = make_node(root, "titles", None)
  for title in bill['titles']:
  	  make_node(titles, "title", title['title'], type=title['type'], ___as=title['as']) # ___ to avoid a Python keyword

  if bill['sponsor']:
    make_node(root, "sponsor", None, **bill['sponsor'])
  else:
    make_node(root, "sponsor", None)

  cosponsors = make_node(root, "cosponsors", None)
  for cosp in bill['cosponsors']:
  	  make_node(cosponsors, "cosponsor", None, **cosp)
  actions = make_node(root, "actions", None)
  for action in bill['actions']:
  	  a = make_node(actions, action['type'], None, datetime=utils.format_datetime(action['acted_at']))
  	  if action.get('text'): make_node(a, "text", action['text'])
  	  if action.get('committee'): make_node(a, "committee", None, name=action['committee'])
  	  for cr in action['references']:
  	  	  make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])
  # TODO committees, related bills
  subjects = make_node(root, "subjects", None)
  for s in bill['subjects']: # top term?
  	  make_node(subjects, "term", None, name=s)
  # TODO amendments
  if bill.get('summary'): make_node(root, "summary", bill['summary'])

  utils.write(
    etree.tostring(root, pretty_print=True),
    output_for_bill(bill['bill_id'], "xml")
  )


def sponsor_for(body):
  match = re.search(r"<b>Sponsor: </b>(No Sponsor|<a href=[^>]+(\d{5}).*>(.*)</a>\s+\[((\w\w)(-(\d+))?)\])", body, re.I)
  if match:
    if (match.group(3) == "No Sponsor") or (match.group(1) == "No Sponsor"):
      return None
    else:
      if len(match.group(4).split('-')) == 2:
        state, district = match.group(4).split('-')
      else:
        state, district = match.group(4), None
      
      thomas_id = str(int(match.group(2)))

      name = match.group(3).strip()
      title, name = re.search("^(Rep|Sen|Del|Com)\.? (.*?)$", name).groups()

      return {
        'title': title,
        'name': name,
        'thomas_id': thomas_id, 
        'state': state, 
        'district': district
      }
  else:
    raise Exception("Choked finding sponsor information.")

def summary_for(body):
  match = re.search("SUMMARY AS OF:</a></b>(.*?)(?:<hr|<div id=\"footer\">)", body, re.S)
  if not match:
    if re.search("<b>SUMMARY:</b><p>\*\*\*NONE\*\*\*", body, re.I):
      return None # expected when no summary
    else:
      raise Exception("Choked finding summary.")

  text = match.group(1).strip()

  # strip out the bold explanation of a new summary, if present
  text = re.sub("\s*<p><b>\(This measure.*?</b></p>\s*", "", text)

  # strip out the intro date thing
  text = re.sub("\d+/\d+/\d+--[^\s].*?(\n|<p>)", "", text)

  # naive stripping of tags, should work okay in this limited context
  text = re.sub("<[^>]+>", "", text)

  # compress and strip whitespace artifacts
  text = re.sub("\s{2,}", " ", text).strip()
  
  return text


def parse_committee_row(rows):
    committee_info = []
    top_committee = None
    for row in rows:
      #ignore header/end row that contain no committee information
      match_header = re.search("</?table", row)
      if match_header:
        continue

      #identifies and pulls out committee name
      #Can handle committee names with letters, white space, dashes, parens, periods, and apostrophes.
      match2 = re.search("(?<=\">)[-.\w\s,()\']+(?=</a>)", row)
      if match2:
        committee = match2.group().strip()
      else:
        raise Exception("Couldn't find committee name.")

      #identifies and pulls out committee activity
      match3 = re.search("(?<=<td width=\"65%\">).*?(?=</td>)", row)
      if match3:
        activity_string = match3.group().strip().lower()
       
        #splits string of activities into activity list
        activity_list = activity_string.split(",")
        
        #strips white space from each activity in list
        activity = []
        for x in activity_list:
          activity.append(x.strip())

      else:
        raise Exception("Couldn't find committee activity.")

      #identifies subcommittees by change in table cell width
      match4 = re.search("<td width=\"5%\">", row)
      if match4:      
        committee_info.append({"committee": top_committee, "activity": activity, "subcommittee": committee})

      else:
        top_committee = committee #saves committee for the next row in case it is a subcommittee
        committee_info.append({"committee": committee, "activity": activity})

    return committee_info

def committees_for(body):

  #grabs entire Committee & Subcommittee table
  match = re.search("COMMITTEE\(S\):<.*?<ul>.*?</table>", body, re.I | re.S)  
  if match: 
    committee_text = match.group().strip()

    #returns empty array for bills not assigned to a committee; e.g. bill_id=hr19-112
    none_match = re.search("\*\*\*NONE\*\*\*", committee_text)
    if none_match:
      committee_info = None

    if not none_match:
      #splits Committee & Subcommittee table up by table row     
      rows = committee_text.split("</tr>")
      committee_info = parse_committee_row(rows)

    return committee_info

  if not match:
    raise Exception("Couldn't find committees section.")

def titles_for(body):
  match = re.search("TITLE\(S\):<.*?<ul>.*?<p><li>(.*?)(?:<hr|<div id=\"footer\">)", body, re.I | re.S)
  if not match:
    raise Exception("Couldn't find titles section.")

  titles = []

  text = match.group(1).strip()
  sections = text.split("<p><li>")
  for section in sections:
    if section.strip() == "":
      continue

    # ensure single newlines between each title in the section
    section = re.sub("\n?<br ?/>", "\n", section)
    section = re.sub("<[^>]+>", "", section) # strip tags

    pieces = section.split("\n")

    full_type, type_titles = pieces[0], pieces[1:]
    if " AS " in full_type:
      type, state = full_type.split(" AS ")
      state = state.replace(":", "").lower()
    else:
      type, state = full_type, None

    if "POPULAR TITLE" in type:
      type = "popular"
    elif "SHORT TITLE" in type:
      type = "short"
    elif "OFFICIAL TITLE" in type:
      type = "official"
    else:
      raise Exception("Unknown title type: " + type)

    for title in type_titles:
      if title.strip() == "":
        continue

      if type == "popular":
        title = re.sub(ur"[\s\u00a0]\(identified.+?$", "", title)

      titles.append({
        'title': title.strip(),
        'as': state,
        'type': type
      })


  return titles


  if len(titles) == 0:
    raise Exception("No titles found.")

  return titles

# the most current title of a given type is the first one in the last 'as' subgroup
def current_title_for(titles, type):
  current_title = None
  current_as = -1 # not None, cause for popular titles, None is a valid 'as'

  for title in titles:
    if title['type'] != type:
      continue
    if title['as'] == current_as:
      continue
    # right type, new 'as', store first one
    current_title = title['title']
    current_as = title['as']

  return current_title


def actions_for(body):
  match = re.search(">ALL ACTIONS:<.*?<dl>(.*?)(?:<hr|<div id=\"footer\">)", body, re.I | re.S)
  if not match:
    if re.search("ALL ACTIONS:((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
      return [] # no actions, can happen for bills reserved for the Speaker
    else:
      raise Exception("Couldn't find action section.")

  actions = []

  text = match.group(1).strip()

  pieces = text.split("\n")
  for piece in pieces:
    if re.search("<strong>", piece) is None:
      continue
    
    action_pieces = re.search("(<dl>)?<dt><strong>(.*?):</strong><dd>(.+?)$", piece)
    if not action_pieces:
      raise Exception("Choked on parsing an action: %s" % piece)

    committee, timestamp, text = action_pieces.groups()

    # timestamp of the action
    if re.search("(am|pm)", timestamp):
      action_time = datetime.datetime.strptime(timestamp, "%m/%d/%Y %I:%M%p")
    else:
      action_time = datetime.datetime.strptime(timestamp, "%m/%d/%Y")
      action_time = datetime.datetime.strftime(action_time, "%Y-%m-%d")

    cleaned_text, references = action_for(text)

    action = {
      'text': cleaned_text,
      'type': "action",
      'acted_at': action_time,
      'references': references
    }
    actions.append(action)

  return actions


# clean text, pull out the action type, any other associated metadata with an action
def action_for(text):
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
    types = re.sub("(\d+) ([a-z])", r"\1; \2", types)

    for reference in re.split("; ?", types):
      if ": " not in reference:
        type, reference = None, reference
      else:
        type, reference = reference.split(": ")

      references.append({'type': type, 'reference': reference})

  return text, references

def introduced_at_for(body):
  doc = fromstring(body)
  
  introduced_at = None
  for meta in doc.cssselect('meta'):
    if meta.get('name') == 'dc.date':
      introduced_at = meta.get('content')
  
  if not introduced_at:
    raise Exception("Couldn't find an introduction date in the meta tags.")

  # maybe silly to parse and re-serialize, but I'd like to make explicit the format we publish dates in
  parsed = datetime.datetime.strptime(introduced_at, "%Y-%m-%d")
  return datetime.datetime.strftime(parsed, "%Y-%m-%d")


def cosponsors_for(body):
  match = re.search("COSPONSORS\((\d+)\).*?<p>(?:</br>)?(.*?)(?:</br>)?(?:<hr|<div id=\"footer\">)", body, re.S)
  if not match:
    none = re.search("COSPONSOR\(S\):</b></a><p>\*\*\*NONE\*\*\*", body)
    if none:
      return [] # no cosponsors, it happens, nothing to be ashamed of
    else:
      raise Exception("Choked finding cosponsors section.")

  count = match.group(1)
  text = match.group(2)

  # fix some bad line breaks
  text = re.sub("</br>", "<br/>", text)

  cosponsors = []

  lines = re.compile("<br ?/>").split(text)
  for line in lines:
    # can happen on stand-alone cosponsor pages
    if line.strip() == "</div>":
      continue

    m = re.search(r"<a href=[^>]+(\d{5}).*>(Rep|Sen) (.+?)</a> \[([A-Z\d\-]+)\]\s*- (\d\d?/\d\d?/\d\d\d\d)(?:\(withdrawn - (\d\d?/\d\d?/\d\d\d\d)\))?", line, re.I)
    if not m:
      raise Exception("Choked scanning cosponsor line: %s" % line)
    
    thomas_id, title, name, district, join_date, withdrawn_date = m.groups()
    
    if len(district.split('-')) == 2:
        state, district_number = district.split('-')
    else:
        state, district_number = district, None

    join_date = datetime.datetime.strptime(join_date, "%m/%d/%Y")
    join_date = datetime.datetime.strftime(join_date, "%Y-%m-%d")
    if withdrawn_date:
      withdrawn_date = datetime.datetime.strptime(withdrawn_date, "%m/%d/%Y")
      withdrawn_date = datetime.datetime.strftime(withdrawn_date, "%Y-%m-%d")

    cosponsors.append({
      'thomas_id': str(int(thomas_id)),
      'title': title,
      'name': name,
      'state': state,
      'district': district_number,
      'sponsored_at': join_date,
      'withdrawn_at': withdrawn_date
    })

  return cosponsors

def subjects_for(body):
  doc = fromstring(body)
  subjects = []
  for meta in doc.cssselect('meta'):
    if meta.get('name') == 'dc.subject':
      subjects.append(meta.get('content'))
  subjects.sort()
      
  return subjects

def related_bills_for(body, congress):
  match = re.search("RELATED BILL DETAILS.*?<p>.*?<table border=\"0\">(.*?)(?:<hr|<div id=\"footer\">)", body, re.S)
  if not match:
    if re.search("RELATED BILL DETAILS:((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
      return []
    else:
      raise Exception("Couldn't find related bills section.")

  text = match.group(1).strip()

  related_bills = []

  for line in re.split("<tr><td", text):
    if (line.strip() == "") or ("Bill:" in line):
      continue

    m = re.search("<a[^>]+>(.+?)</a>.*?<td>(.+?)</td>", line)
    if not m:
      raise Exception("Choked processing related bill line.")

    bill_code, reason = m.groups()

    bill_id = "%s-%s" % (bill_code.lower().replace(".", "").replace(" ", ""), congress)
    
    reasons = {
      "Identical bill identified by CRS": "identical",
      "Related bill identified by CRS": "related",
      "Related bill as identified by the House Clerk's office": "related",
      "passed in House in lieu of this bill": "supersedes",
      "passed in Senate in lieu of this bill": "supersedes",
    }

    reason = reasons.get(reason.strip(), "unknown")

    related_bills.append({
      'bill_id': bill_id,
      'reason': reason
    })


  return related_bills

# get the public or private law number from any enacted action
def slip_law_from(actions):
  for action in actions:
    if action["type"] == "enacted":
      return {
        'law_type': action["law"],
        'congress': action["congress"],
        'number': action["number"]
      }

# given the parsed list of actions from actions_for, run each action
# through metadata extraction and figure out what current status the bill is in
def process_actions(actions, bill_id, title, introduced_date):
  
  status = "INTRODUCED" # every bill is at least introduced
  status_date = introduced_date
  new_actions = []

  for action in actions:
    new_action, new_status = parse_bill_action(action['text'], status, bill_id, title)

    # only change/reflect status change if there was one
    if new_status:
      new_action['status'] = new_status

    # an action can opt-out of inclusion altogether
    if new_action:
      action.update(new_action)
      new_actions.append(action)

  return new_actions

# find the latest status change in a set of processed actions
def latest_status(actions):
  status, status_date = None, None
  for action in actions:
    if action.get('status', None):
      status = action['status']
      status_date = action['acted_at']
  return status, status_date

# look at the final set of processed actions and pull out the major historical events
def history_from_actions(actions):
  
  history = {}
  
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


def parse_bill_action(line, prev_status, bill_id, title):
  """Parse a THOMAS bill action line. Returns attributes to be set in the XML file on the action line."""
  
  bill_type, number, congress = utils.split_bill_id(bill_id)

  status = None
  action = {
    "type": "action"
  }
  
  # If a line starts with an amendment number, this action is on the amendment and cannot
  # be parsed yet.
  m = re.search(r"^(H|S)\.Amdt\.(\d+)", line, re.I)
  if m != None:
    # Process actions specific to amendments separately.
    return None, None
  
  # Otherwise, parse the action line for key actions.
      
  # A House Vote.
  line = re.sub(", the Passed", ", Passed", line); # 106 h4733 and others
  m = re.search(r"(On passage|On motion to suspend the rules and pass the bill|On motion to suspend the rules and agree to the resolution|On motion to suspend the rules and pass the resolution|On agreeing to the resolution|On agreeing to the conference report|Two-thirds of the Members present having voted in the affirmative the bill is passed,?|On motion that the House agree to the Senate amendments?|On motion that the House suspend the rules and concur in the Senate amendments?|On motion that the House suspend the rules and agree to the Senate amendments?|On motion that the House agree with an amendment to the Senate amendments?|House Agreed to Senate Amendments.*?|Passed House)(, the objections of the President to the contrary notwithstanding.?)?(, as amended| \(Amended\))? (Passed|Failed|Agreed to|Rejected)? ?(by voice vote|without objection|by (the Yeas and Nays|Yea-Nay Vote|recorded vote)((:)? \(2/3 required\))?: \d+ - \d+(, \d+ Present)? [ \)]*\((Roll no\.|Record Vote No:) \d+\))", line, re.I)
  if m != None:
    motion, is_override, as_amended, pass_fail, how = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
  
    # print line
    # print m.groups()

    if re.search(r"Passed House|House Agreed to", motion, re.I):
      pass_fail = 'pass'
    elif re.search("(ayes|yeas) had prevailed", line, re.I):
      pass_fail = 'pass'
    elif re.search(r"Pass|Agreed", pass_fail, re.I):
      pass_fail = 'pass'
    else:
      pass_fail = 'fail'
    
    if "Two-thirds of the Members present" in motion:
      is_override = True
    
    if is_override:
      vote_type = "override"
    elif re.search(r"(agree (with an amendment )?to|concur in) the Senate amendment", line, re.I):
      vote_type = "pingpong"
    elif re.search("conference report", line, re.I):
      vote_type = "conference"
    elif bill_type[0] == "h":
      vote_type = "vote"
    else:
      vote_type = "vote2"
    
    roll = None
    m = re.search(r"\((Roll no\.|Record Vote No:) (\d+)\)", how, re.I)
    if m != None:
      how = "roll" # normalize the ugly how
      roll = m.group(2)

    suspension = None
    if roll and "On motion to suspend the rules" in motion:
      suspension = True

    action["type"] = "vote"
    action["vote_type"] = vote_type
    action["how"] = how
    action['where'] = "h"
    action['result'] = pass_fail
    if roll:
      action["roll"] = roll

    # get the new status of the bill after this vote
    new_status = new_status_after_vote(vote_type, pass_fail=="pass", "h", bill_type, suspension, as_amended, title, prev_status)
    if new_status:
      status = new_status
    
  # Passed House, not necessarily by an actual vote (think "deem")
  m = re.search(r"Passed House pursuant to", line, re.I)
  if m != None:
    vote_type = "vote" if (bill_type[0] == "h") else "vote2"
    pass_fail = "pass"

    action["type"] = "vote"
    action["vote_type"] = vote_type
    action["how"] = "by special rule"
    action["where"] = "h"
    action["result"] = pass_fail

    # get the new status of the bill after this vote
    new_status = new_status_after_vote(vote_type, pass_fail=="pass", "h", bill_type, False, False, title, prev_status)
    
    if new_status:
      status = new_status
  
  # A Senate Vote
  m = re.search(r"(Passed Senate|Failed of passage in Senate|Resolution agreed to in Senate|Received in the Senate, considered, and agreed to|Submitted in the Senate, considered, and agreed to|Introduced in the Senate, read twice, considered, read the third time, and passed|Received in the Senate, read twice, considered, read the third time, and passed|Senate agreed to conference report|Cloture \S*\s?on the motion to proceed .*?not invoked in Senate|Cloture on the bill not invoked in Senate|Cloture on the bill invoked in Senate|Cloture invoked in Senate|Cloture on the motion to proceed to the bill invoked in Senate|Cloture on the motion to proceed to the bill not invoked in Senate|Senate agreed to House amendment|Senate concurred in the House amendment)(,?.*,?) (without objection|by Unanimous Consent|by Voice Vote|by Yea-Nay( Vote)?\. \d+\s*-\s*\d+\. Record Vote (No|Number): \d+)", line, re.I)
  if m != None:
    motion, extra, how = m.group(1), m.group(2), m.group(3)
    roll = None
    
    if re.search("passed|agreed|concurred|bill invoked|cloture invoked", motion, re.I):
      pass_fail = "pass"
    else:
      pass_fail = "fail"
      
    voteaction_type = "vote"
    if re.search("over veto", extra, re.I):
      vote_type = "override"
    elif re.search("conference report", motion, re.I):
      vote_type = "conference"
    elif re.search("cloture", motion, re.I):
      vote_type = "cloture"
      voteaction_type = "vote-aux" # because it is not a vote on passage
    elif re.search("Senate agreed to House amendment|Senate concurred in the House amendment", motion, re.I):
      vote_type = "pingpong"
    elif bill_type[0] == "s":
      vote_type = "vote"
    else:
      vote_type = "vote2"
      
    m = re.search(r"Record Vote (No|Number): (\d+)", how, re.I)
    if m != None:
      roll = m.group(2)
      how = "roll"
      
    as_amended = False
    if re.search(r"with amendments|with an amendment", extra, re.I):
      as_amended = True
      
    action["type"] = voteaction_type
    action["vote_type"] = vote_type
    action["how"] = how
    action["result"] = pass_fail
    action["where"] = "s"
    if roll:
      action["roll"] = roll

    # get the new status of the bill after this vote
    new_status = new_status_after_vote(vote_type, pass_fail=="pass", "s", bill_type, False, as_amended, title, prev_status)
    
    if new_status:
      status = new_status
      
  # TODO: Make a new status for this as pre-reported.
  m = re.search(r"Placed on (the )?([\w ]+) Calendar( under ([\w ]+))?[,\.] Calendar No\. (\d+)\.|Committee Agreed to Seek Consideration Under Suspension of the Rules|Ordered to be Reported", line, re.I)
  if m != None:
    # TODO: This makes no sense.
    if prev_status in ("INTRODUCED", "REFERRED"):
      status = "REPORTED"
    
    action["type"] = "calendar"
    
    # TODO: Useless.
    action["calendar"] = m.group(2)
    action["under"] = m.group(4)
    action["number"] = m.group(5)
  
  m = re.search(r"Committee on (.*)\. Reported by", line, re.I)
  if m != None:
    action["type"] = "reported"
    action["committee"] = m.group(1)
    if prev_status in ("INTRODUCED", "REFERRED"):
      status = "REPORTED"
    
  m = re.search(r"Committee on (.*)\. Discharged (by Unanimous Consent)?", line, re.I)
  if m != None:
    action["committee"] = m.group(1)
    action["type"] = "discharged"
    if prev_status in ("INTRODUCED", "REFERRED"):
      status = "REPORTED"
      
  m = re.search("Cleared for White House|Presented to President", line, re.I)
  if m != None:
    action["type"] = "topresident"
    
  m = re.search("Signed by President", line, re.I)
  if m != None:
    action["type"] = "signed"
    
  m = re.search("Pocket Vetoed by President", line, re.I)
  if m != None:
    action["type"] = "vetoed"
    action["pocket"] = "1"
    status = "VETOED:POCKET"

  # need to put this in an else, or this regex will match the pocket veto and override it
  else: 
    m = re.search("Vetoed by President", line, re.I)
    if m != None:
      action["type"] = "vetoed"
      status = "PROV_KILL:VETO"
    
  m = re.search("Became (Public|Private) Law No: ([\d\-]+)\.", line, re.I)
  if m != None:
    action["law"] = m.group(1).lower()
    pieces = m.group(2).split("-")
    action["congress"] = pieces[0]
    action["number"] = pieces[1]
    action["type"] = "enacted"
    if prev_status != "PROV_KILL:VETO" and not prev_status.startswith("VETOED:"):       
      status = "ENACTED:SIGNED"
    else:
      status = "ENACTED:VETO_OVERRIDE"
    
  m = re.search(r"Referred to (the )?((House|Senate|Committee) [^\.]+).?", line, re.I)
  if m != None:
    action["type"] = "referral"
    action["committee"] = m.group(2)
    if prev_status == "INTRODUCED":
      status = "REFERRED"
    
  m = re.search(r"Referred to the Subcommittee on (.*[^\.]).?", line, re.I)
  if m != None:
    action["type"] = "referral"
    action["subcommittee"] = m.group(1)
    if prev_status == "INTRODUCED":
      status = "REFERRED"
    
  m = re.search(r"Received in the Senate and referred to (the )?(.*[^\.]).?", line, re.I)
  if m != None:
    action["type"] = "referral"
    action["committee"] = m.group(2)

  # no matter what it is, sweep the action line for bill IDs of related bills
  bill_ids = utils.extract_bills(line, congress)
  bill_ids = filter(lambda b: b != bill_id, bill_ids)
  if bill_ids and (len(bill_ids) > 0):
    action['bill_ids'] = bill_ids
        
  return action, status

def new_status_after_vote(vote_type, passed, chamber, bill_type, suspension, amended, title, prev_status):
  if vote_type == "vote": # vote in originating chamber
    if passed:
      if bill_type in ("hres", "sres"):
        return 'PASSED:SIMPLERES' # end of life for a simple resolution
      if chamber == "h":
        return 'PASS_OVER:HOUSE' # passed by originating chamber, now in second chamber
      else:
        return 'PASS_OVER:SENATE' # passed by originating chamber, now in second chamber
    if suspension:
      return 'PROV_KILL:SUSPENSIONFAILED' # provisionally killed by failure to pass under suspension of the rules
    if chamber == "h":
      return 'FAIL:ORIGINATING:HOUSE' # outright failure
    else:
      return 'FAIL:ORIGINATING:SENATE' # outright failure
  if vote_type == "vote2": # vote in second chamber
    if passed:
      if bill_type in ("hjres", "sjres") and title.startswith("Proposing an amendment to the Constitution of the United States"):
        return 'PASSED:CONSTAMEND' # joint resolution that looks like an amendment to the constitution
      if bill_type in ("hconres", "sconres"):
        return 'PASSED:CONCURRENTRES' # end of life for concurrent resolutions
      if amended:
        # bills and joint resolutions not constitutional amendments, amended from Senate version.
        # can go back to Senate, or conference committee
        if chamber == "h":
          return 'PASS_BACK:HOUSE' # passed by originating chamber, now in second chamber
        else:
          return 'PASS_BACK:SENATE' # passed by originating chamber, now in second chamber
      else:
        # bills and joint resolutions not constitutional amendments, not amended from Senate version
        return 'PASSED:BILL' # passed by second chamber, now on to president
    if suspension:
      return 'PROV_KILL:SUSPENSIONFAILED' # provisionally killed by failure to pass under suspension of the rules
    if chamber == "h":
      return 'FAIL:SECOND:HOUSE' # outright failure
    else:
      return 'FAIL:SECOND:SENATE' # outright failure
  if vote_type == "cloture":
    if not passed:
      return "PROV_KILL:CLOTUREFAILED"
    else:
      return None
  if vote_type == "override":
    if not passed:
      if bill_type[0] == chamber:
        if chamber == "h":
          return 'VETOED:OVERRIDE_FAIL_ORIGINATING:HOUSE'
        else:
          return 'VETOED:OVERRIDE_FAIL_ORIGINATING:SENATE'
      else:
        if chamber == "h":
          return 'VETOED:OVERRIDE_FAIL_SECOND:HOUSE'
        else:
          return 'VETOED:OVERRIDE_FAIL_SECOND:SENATE'
    else:
      if bill_type[0] == chamber:
        if chamber == "h":
          return 'VETOED:OVERRIDE_PASS_OVER:HOUSE'
        else:
          return 'VETOED:OVERRIDE_PASS_OVER:SENATE'
      else:
        return None # just wait for the enacted line
  if vote_type == "pingpong":
    # This is a motion to accept Senate amendments to the House's original bill
    # or vice versa. If the motion fails, I suppose it is a provisional kill. If it passes,
    # then pingpong is over and the bill has passed both chambers.
    if passed:
      return 'PASSED:BILL'
    else:
      return 'PROV_KILL:PINGPONGFAIL'
  if vote_type == "conference":
    # This is tricky to integrate into status because we have to wait for both
    # chambers to pass the conference report.
    if passed:
      if prev_status.startswith("CONFERENCE:PASSED:"):
        return 'PASSED:BILL'
      else:
        if chamber == "h":
          return 'CONFERENCE:PASSED:HOUSE'
        else:
          return 'CONFERENCE:PASSED:SENATE'
      
  return None

# parse amendments out of undocumented standalone amendments page
def amendments_for_standalone(body, bill_id):
  bill_type, number, congress = utils.split_bill_id(bill_id)

  amendments = []

  for code, chamber, number in re.findall("<a href=\"/cgi-bin/bdquery/z\?d\d+:(SU|SP|HZ)\d+:\">(S|H)\.(?:UP\.)?AMDT\.(\d+)</a>", body, re.I):
    chamber = chamber.lower()

    # there are "senate unprinted amendments" for the 97th and 98th Congresses, with their own numbering scheme
    # make those use 'su' as the type instead of 's'
    amendment_type = chamber
    if code == "SU":
      amendment_type = "su"

    amendments.append({
      'chamber': chamber,
      'amendment_type': amendment_type,
      'number': number,
      'amendment_id': "%s%s-%s" % (amendment_type, number, congress)
    })

  if len(amendments) == 0:
    if not re.search("AMENDMENT\(S\):((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
      raise Exception("Couldn't find amendments section.")

  return amendments

def amendments_for(body, bill_id):
  bill_type, number, congress = utils.split_bill_id(bill_id)
  
  # it is possible in older sessions for the amendments section to not appear at all.
  # if this method is being run, we know the page is not truncated, so if the header
  # is not at all present, assume the page is missing amendments because there are none.
  if not re.search("AMENDMENT\(S\):", body):
    return []

  amendments = []

  for code, chamber, number in re.findall("<b>\s*\d+\.</b>\s*<a href=\"/cgi-bin/bdquery/z\?d\d+:(SU|SP|HZ)\d+:\">(S|H)\.(?:UP\.)?AMDT\.(\d+)\s*</a> to ", body, re.I):
    chamber = chamber.lower()

    # there are "senate unprinted amendments" for the 97th and 98th Congresses, with their own numbering scheme
    # make those use 'su' as the type instead of 's'
    amendment_type = chamber
    if code == "SU":
      amendment_type = "su"

    amendments.append({
      'chamber': chamber,
      'amendment_type': amendment_type,
      'number': number,
      'amendment_id': "%s%s-%s" % (amendment_type, number, congress)
    })

  if len(amendments) == 0:
    if not re.search("AMENDMENT\(S\):((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
      raise Exception("Couldn't find amendments section.")

  return amendments


# are there at least 150 amendments listed in this body? a quick tally
# not the end of the world if it's wrong once in a great while, it just sparks
# a less efficient way of gathering this bill's data
def too_many_amendments(body):
  # example:
  # "<b>150.</b> <a href="/cgi-bin/bdquery/z?d111:SP02937:">S.AMDT.2937 </a> to <a href="/cgi-bin/bdquery/z?d111:HR03590:">H.R.3590</a>"
  amendments = re.findall("(<b>\s*\d+\.</b>\s*<a href=\"/cgi-bin/bdquery/z\?d\d+:(SP|HZ)\d+:\">(S|H)\.AMDT\.\d+\s*</a> to )", body, re.I)
  return (len(amendments) >= 150)

# bills reserved for the speaker are not actual legislation, 
# just markers that the number will not be used for ordinary members' bills
def reserved_for_speaker(body):
  if re.search("OFFICIAL TITLE AS INTRODUCED:((?:(?!\<hr).)+)Reserved for the Speaker", body, re.S | re.I):
    return True
  else:
    return False


# directory helpers

def output_for_bill(bill_id, format):
  bill_type, number, congress = utils.split_bill_id(bill_id)
  return "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, "data.%s" % format)

# defaults to "All Information" page for a bill
def bill_url_for(bill_id, page = "L"):
  bill_type, number, congress = utils.split_bill_id(bill_id)
  thomas_type = utils.thomas_types[bill_type][0]
  congress = int(congress)
  return "http://thomas.loc.gov/cgi-bin/bdquery/z?d%03d:%s%s:@@@%s&summ2=m&" % (congress, thomas_type, number, page)

def bill_cache_for(bill_id, file):
  bill_type, number, congress = utils.split_bill_id(bill_id)
  return "%s/bills/%s/%s%s/%s" % (congress, bill_type, bill_type, number, file)
