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
    fetch_bill(bill_id, options)
  else:
    log("To run this task directly, supply a bill_id.")


# download and cache landing page for bill
# can raise an exception under various conditions
def fetch_bill(bill_id, options):
  log("[%s] Fetching..." % bill_id)

  body = utils.download(
    bill_url_for(bill_id), 
    bill_cache_for(bill_id, "information.html"),
    options.get('force', False))

  body = utils.unescape(body)

  doc = pq(body, parser='html')
  
  bill_type, number, session = utils.split_bill_id(bill_id)
  sponsor = sponsor_for(body)
  summary = summary_for(body)
  actions = actions_for(body)

  output_bill({
    'bill_id': bill_id,
    'bill_type': bill_type,
    'number': number,
    'session': session,
    'sponsor': sponsor,
    'summary': summary,
    'actions': actions
  }, options)


def output_bill(bill, options):
  log("[%s] Writing to disk..." % bill['bill_id'])

  # output JSON
  utils.write(
    json.dumps(bill, sort_keys=True, indent=2), 
    output_for_bill(bill['bill_id'], "json")
  )

  # output XML
  root = etree.Element("bill")
  root.set("session", bill['session'])
  root.set("type", bill['bill_type'])
  root.set("number", bill['number'])
  root.set("updated", utils.format_datetime(time.time()))

  utils.write(
    etree.tostring(root, pretty_print=True),
    output_for_bill(bill['bill_id'], "xml")
  )
  


def sponsor_for(body):
  match = re.search(r"<b>Sponsor: </b>(No Sponsor|<a [^>]+>(.*)</a>\s+\[((\w\w)(-(\d+))?)\])", body, re.I)
  if match:
    if match.group(1) == "No Sponsor":
      return None
    else:
      return (match.group(2), match.group(3))
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

def actions_for(body):
  match = re.search(">ALL ACTIONS:<.*?<dl>(.*?)<hr", body, re.S)
  if not match:
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

    for consideration in match.group(1).split("; "):
      if ": " not in consideration:
        type, reference = None, consideration
      else:
        type, reference = consideration.split(": ")

      considerations.append({'type': type, 'reference': reference})

  return (text, "action", considerations, {})




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