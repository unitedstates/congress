import utils
from utils import log
import re
from pyquery import PyQuery as pq
import json
from lxml import etree
import time, datetime

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

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}

  body = utils.unescape(body)
  if "</html>" not in body:
    return {'saved': False, 'ok': False, 'reason': "page was truncated"}
  
  bill = parse_bill(bill_id, body, options)
  output_bill(bill, options)

  return {'ok': True, 'saved': True}


def parse_bill(bill_id, body, options):
  bill_type, number, session = utils.split_bill_id(bill_id)

  # do all the raw html parsing

  # introduced_at = introduced_at_for(body)
  sponsor = sponsor_for(body)
  cosponsors = cosponsors_for(body)
  summary = summary_for(body)
  titles = titles_for(body)
  actions = actions_for(body)
  related_bills = related_bills_for(body, session)
  # committees = committees_for(body)
  # amendments = amendments_for(body)
  # subjects = subjects_for(body)


  # post-processing and normalization

  # for convenience: extract out current title of each type
  # current_title = current_title_for(titles)

  # add metadata to each action, establish current state
  actions, state = process_actions(actions, bill_type, titles[-1])

  # pull out some very useful history information from the actions
  history = history_from_actions(actions)

  return {
    'bill_id': bill_id,
    'bill_type': bill_type,
    'number': number,
    'session': session,
    'state': state,
    # 'introduced_at': introduced_at,
    'sponsor': sponsor,
    'summary': summary,
    'actions': actions,
    'history': history,
    'cosponsors': cosponsors,
    'titles': titles,
    'related_bills': related_bills,
    # 'committees': committees,
    # 'amendments': amendments,
    # 'subjects': subjects,

    'updated_at': datetime.datetime.fromtimestamp(time.time())
  }

def output_bill(bill, options):
  log("[%s] Writing to disk..." % bill['bill_id'])

  # output JSON
  utils.write(
    json.dumps(bill, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_bill(bill['bill_id'], "json")
  )

  # output XML
  root = etree.Element("bill")
  root.set("session", bill['session'])
  root.set("type", bill['bill_type'])
  root.set("number", bill['number'])
  root.set("updated", utils.format_datetime(bill['updated_at']))

  utils.write(
    etree.tostring(root, pretty_print=True),
    output_for_bill(bill['bill_id'], "xml")
  )
  


def sponsor_for(body):
  match = re.search(r"<b>Sponsor: </b>(No Sponsor|<a href=[^>]+(\d{5}).*>(.*)</a>\s+\[((\w\w)(-(\d+))?)\])", body, re.I)
  if match:
    if match.group(3) == "No Sponsor":
      return None
    else:
      if len(match.group(4).split('-')) == 2:
        state, district = match.group(4).split('-')
      else:
        state, district = match.group(4), None
      
      thomas_id = int(match.group(2))

      return {
        'name': match.group(3),
        'thomas_id': thomas_id, 
        'state': state, 
        'district': district
      }
  else:
    raise Exception("Choked finding sponsor information.")

def summary_for(body):
  match = re.search("SUMMARY AS OF:</a></b>(.*?)<hr", body, re.S)
  if not match:
    return None # expected when no summary

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


def titles_for(body):
  match = re.search("TITLE\(S\):<.*?<ul>.*?<p><li>(.*?)<hr", body, re.I | re.S)
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


def actions_for(body):
  match = re.search(">ALL ACTIONS:<.*?<dl>(.*?)<hr", body, re.I | re.S)
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

    cleaned_text, considerations = action_for(text)

    action = {
      'text': cleaned_text,
      'type': "action",
      'acted_at': action_time,
      'considerations': considerations
    }
    actions.append(action)

  return actions


# clean text, pull out the action type, any other associated metadata with an action
def action_for(text):
  # strip out links
  text = re.sub(r"</?[Aa]( \S.*?)?>", "", text)

  # remove and extract considerations
  considerations = []
  match = re.search("\s+\(([^)]+)\)\s*$", text)
  if match:
    # remove the matched section
    text = text[0:match.start()] + text[match.end():]

    types = match.group(1)

    # fix use of comma or colon instead of a semi colon between consideration types
    # have seen some accidental capitalization combined with accidental comma, thus the 'T'
    # e.g. "text of Title VII as reported in House: CR H3075-3077, Text omission from Title VII:" (hr5384-109)
    types = re.sub("[,:] ([a-zT])", r"; \1", types)
    # fix "CR:"
    types = re.sub("CR:", "CR", types)
    # fix a missing semicolon altogether between considerations
    # e.g. sres107-112, "consideration: CR S1877-1878 text as"
    types = re.sub("(\d+) ([a-z])", r"\1; \2", types)

    for consideration in re.split("; ?", types):
      if ": " not in consideration:
        type, reference = None, consideration
      else:
        type, reference = consideration.split(": ")

      considerations.append({'type': type, 'reference': reference})

  return text, considerations

def cosponsors_for(body):
  match = re.search("COSPONSORS\((\d+)\).*?<p>(?:</br>)?(.*?)(?:</br>)?<hr", body, re.S)
  if not match:
    none = re.search("COSPONSOR\(S\):</b></a><p>\*\*\*NONE\*\*\*", body)
    if none:
      return [] # no cosponsors, it happens, nothing to be ashamed of
    else:
      raise Exception("Choked finding cosponsors section")

  count = match.group(1)
  text = match.group(2)

  # fix some bad line breaks
  text = re.sub("</br>", "<br/>", text)

  cosponsors = []

  lines = re.compile("<br ?/>").split(text)
  for line in lines:
    m = re.search(r"<a href=[^>]+(\d{5}).*>(Rep|Sen) (.+?)</a> \[([A-Z\d\-]+)\]\s*- (\d\d?/\d\d?/\d\d\d\d)(?:\(withdrawn - (\d\d?/\d\d?/\d\d\d\d)\))?", line, re.I)
    if not m:
      raise Exception("Choked scanning cosponsor line: %s" % line)
    
    thomas_id, title, name, district, join_date, withdrawn_date = m.groups()
    
    if len(district.split('-')) == 2:
        state, district_number = district.split('-')
    else:
        state, district_number = district, None

    join_date = datetime.datetime.strptime(join_date, "%m/%d/%Y")
    if withdrawn_date:
      withdrawn_date = datetime.datetime.strptime(withdrawn_date, "%m/%d/%Y")

    cosponsors.append({
      'thomas_id': int(thomas_id),
      'title': title,
      'name': name,
      'state': state,
      'district': district_number,
      'sponsored_at': join_date,
      'withdrawn_at': withdrawn_date
    })

  return cosponsors

def related_bills_for(body, session):
  match = re.search("RELATED BILL DETAILS.*?<p>.*?<table border=\"0\">(.*?)<hr", body, re.S)
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

    bill_id = "%s-%s" % (bill_code.lower().replace(".", "").replace(" ", ""), session)
    reason = re.sub("^Related bill (as )?", "", reason)

    related_bills.append({
      'bill_id': bill_id,
      'reason': reason
    })


  return related_bills

# given the parsed list of actions from actions_for, run each action
# through metadata extraction and figure out what current state the bill is in
def process_actions(actions, bill_type, title):
  
  state = "INTRODUCED" # every bill is at least introduced
  new_actions = []

  for action in actions:
    new_action, new_state = parse_bill_action(action['text'], state, bill_type, title)

    # only change/reflect state change if there was one
    if new_state:
      state = new_state
      new_action['state'] = new_state

    # an action can opt-out of inclusion altogether
    if new_action:
      action.update(new_action)
      new_actions.append(action)

  return new_actions, state

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


def parse_bill_action(line, prev_state, bill_type, title):
  """Parse a THOMAS bill action line. Returns attributes to be set in the XML file on the action line."""
  
  state = None
  action = {
    "type": "action"
  }
  
  # If a line starts with an amendment number, this action is on the amendment and cannot
  # be parsed yet.
  m = re.match("r^(H|S)\.Amdt\.(\d+)", line, re.I)
  if m != None:
    # Process actions specific to amendments separately.
    return {
      "amendment": m.group(1).lower() + m.group(2)
    }
  
  # Otherwise, parse the action line for key actions.
      
  # A House Vote.
  line = re.sub(", the Passed", ", Passed", line); # 106 h4733 and others
  m = re.search(r"(On passage|On motion to suspend the rules and pass the bill|On motion to suspend the rules and agree to the resolution|On motion to suspend the rules and pass the resolution|On agreeing to the resolution|On agreeing to the conference report|Two-thirds of the Members present having voted in the affirmative the bill is passed,?|On motion that the House agree to the Senate amendments?|On motion that the House suspend the rules and concur in the Senate amendments?|On motion that the House suspend the rules and agree to the Senate amendments?|On motion that the House agree with an amendment to the Senate amendments?|House Agreed to Senate Amendments.*?|Passed House)(, the objections of the President to the contrary notwithstanding.?)?(, as amended| \(Amended\))? (Passed|Failed|Agreed to|Rejected)? ?(by voice vote|without objection|by (the Yeas and Nays|Yea-Nay Vote|recorded vote)((:)? \(2/3 required\))?: \d+ - \d+(, \d+ Present)? [ \)]*\((Roll no\.|Record Vote No:) \d+\))", line, re.I)
  if m != None:
    motion, is_override, as_amended, pass_fail, how = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    
    if re.search(r"Passed House|House Agreed to", motion, re.I):
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

    # get the new state of the bill after this vote
    new_state = new_state_after_vote(vote_type, pass_fail=="pass", "h", bill_type, suspension, as_amended, title, prev_state)
    if new_state:
      state = new_state
    
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

    # get the new state of the bill after this vote
    new_state = new_state_after_vote(vote_type, pass_fail=="pass", "h", bill_type, False, False, title, prev_state)
    
    if new_state:
      state = new_state
  
  # A Senate Vote
  m = re.search(r"(Passed Senate|Failed of passage in Senate|Resolution agreed to in Senate|Received in the Senate, considered, and agreed to|Submitted in the Senate, considered, and agreed to|Introduced in the Senate, read twice, considered, read the third time, and passed|Received in the Senate, read twice, considered, read the third time, and passed|Senate agreed to conference report|Cloture \S*\s?on the motion to proceed .*?not invoked in Senate|Cloture on the bill not invoked in Senate|Cloture on the bill invoked in Senate|Cloture on the motion to proceed to the bill invoked in Senate|Cloture on the motion to proceed to the bill not invoked in Senate|Senate agreed to House amendment|Senate concurred in the House amendment)(,?.*,?) (without objection|by Unanimous Consent|by Voice Vote|by Yea-Nay( Vote)?\. \d+\s*-\s*\d+\. Record Vote (No|Number): \d+)", line, re.I)
  if m != None:
    motion, extra, how = m.group(1), m.group(2), m.group(3)
    roll = None
    
    if re.search("passed|agreed|concurred|bill invoked", motion, re.I):
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

    # get the new state of the bill after this vote
    new_state = new_state_after_vote(vote_type, pass_fail=="pass", "s", bill_type, False, as_amended, title, prev_state)
    
    if new_state:
      state = new_state
      
  # TODO: Make a new state for this as pre-reported.
  m = re.search(r"Placed on (the )?([\w ]+) Calendar( under ([\w ]+))?[,\.] Calendar No\. (\d+)\.|Committee Agreed to Seek Consideration Under Suspension of the Rules|Ordered to be Reported", line, re.I)
  if m != None:
    # TODO: This makes no sense.
    if prev_state in ("INTRODUCED", "REFERRED"):
      state = "REPORTED"
    
    action["type"] = "calendar"
    
    # TODO: Useless.
    action["calendar"] = m.group(2)
    action["under"] = m.group(4)
    action["number"] = m.group(5)
  
  m = re.search(r"Committee on (.*)\. Reported by", line, re.I)
  if m != None:
    action["type"] = "reported"
    action["committee"] = m.group(1)
    if prev_state in ("INTRODUCED", "REFERRED"):
      state = "REPORTED"
    
  m = re.search(r"Committee on (.*)\. Discharged (by Unanimous Consent)?", line, re.I)
  if m != None:
    action["committee"] = m.group(1)
    action["type"] = "discharged"
    if prev_state in ("INTRODUCED", "REFERRED"):
      state = "REPORTED"
      
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
    state = "VETOED:POCKET"

  # need to put this in an else, or this regex will match the pocket veto and override it
  else: 
    m = re.search("Vetoed by President", line, re.I)
    if m != None:
      action["type"] = "vetoed"
      state = "PROV_KILL:VETO"
    
  m = re.search("Became (Public|Private) Law No: ([\d\-]+)\.", line, re.I)
  if m != None:
    action["type"] = "enacted"
    if prev_state != "PROV_KILL:VETO" and not prev_state.startswith("VETOED:"):       
      state = "ENACTED:SIGNED"
    else:
      state = "ENACTED:VETO_OVERRIDE"
    
  m = re.search(r"Referred to (the )?((House|Senate|Committee) [^\.]+).?", line, re.I)
  if m != None:
    action["type"] = "referral"
    action["committee"] = m.group(2)
    if prev_state == "INTRODUCED":
      state = "REFERRED"
    
  m = re.search(r"Referred to the Subcommittee on (.*[^\.]).?", line, re.I)
  if m != None:
    action["type"] = "referral"
    action["subcommittee"] = m.group(1)
    if prev_state == "INTRODUCED":
      state = "REFERRED"
    
  m = re.search(r"Received in the Senate and referred to (the )?(.*[^\.]).?", line, re.I)
  if m != None:
    action["type"] = "referral"
    action["committee"] = m.group(2)
        
  return action, state

def new_state_after_vote(vote_type, passed, chamber, bill_type, suspension, amended, title, prev_state):
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
    # This is tricky to integrate into state because we have to wait for both
    # chambers to pass the conference report.
    if passed:
      if prev_state.startswith("CONFERENCE:PASSED:"):
        return 'PASSED:BILL'
      else:
        if chamber == "h":
          return 'CONFERENCE:PASSED:HOUSE'
        else:
          return 'CONFERENCE:PASSED:SENATE'
      
  return None

def output_for_bill(bill_id, format):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "data/bills/%s/%s/%s%s/%s" % (session, bill_type, bill_type, number, "data.%s" % format)

# "All Information" page for a bill
def bill_url_for(bill_id):
  bill_type, number, session = utils.split_bill_id(bill_id)
  thomas_type = utils.thomas_types[bill_type][0]
  return "http://thomas.loc.gov/cgi-bin/bdquery/z?d%s:%s%s:@@@L&summ2=m&" % (session, thomas_type, number)

def bill_cache_for(bill_id, file):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "bills/%s/%s/%s%s/%s" % (session, bill_type, bill_type, number, file)