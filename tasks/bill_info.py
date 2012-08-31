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

  skipped, error = False, False

  body = utils.unescape(body)

  if "</html>" not in body:
    return {'saved': False, 'ok': False, 'reason': "page was truncated"}
  
  bill_type, number, session = utils.split_bill_id(bill_id)
  sponsor = sponsor_for(body)
  cosponsors = cosponsors_for(body)
  summary = summary_for(body)
  actions = actions_for(body)
  titles = titles_for(body)
  related_bills = related_bills_for(body, session)
  # committees = committees_for(body)
  # amendments = amendments_for(body)
  # subjects = subjects_for(body)

  output_bill({
    'bill_id': bill_id,
    'bill_type': bill_type,
    'number': number,
    'session': session,
    'sponsor': sponsor,
    'summary': summary,
    'actions': actions,
    'cosponsors': cosponsors,
    'titles': titles,
    'related_bills': related_bills,
    # 'committees': committees,
    # 'amendments': amendments,
    # 'subjects': subjects,

    'updated_at': datetime.datetime.fromtimestamp(time.time())
  }, options)

  return {'ok': True, 'saved': True}


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

    cleaned_text, action_type, considerations, other = action_for(text)

    action = {
      'text': cleaned_text,
      'type': action_type,
      'acted_at': action_time,
      'considerations': considerations
    }
    action.update(other)
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

  return (text, "action", considerations, {})

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
      'thomas_id': thomas_id,
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