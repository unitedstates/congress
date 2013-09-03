import utils
import logging
import re
import json
from datetime import datetime
from lxml import etree
import time
from lxml.html import fromstring

# can be run on its own, just require a nomination_id (e.g. PN2094-112)
def run(options):
  nomination_id = options.get('nomination_id', None)

  if nomination_id:
    result = fetch_nomination(nomination_id, options)
    logging.warn("\n%s" % result)
  else:
    logging.error("To run this task directly, supply a bill_id.")

# download and cache page for nomination
def fetch_nomination(nomination_id, options={}):
  logging.info("\n[%s] Fetching..." % nomination_id)

  # fetch committee name map, if it doesn't already exist
  nomination_type, number, congress = utils.split_nomination_id(nomination_id)
  if not number:
    return {'saved': False, 'ok': False, 'reason': "Couldn't parse %s" % nomination_id }

  # fetch bill details body
  body = utils.download(
    nomination_url_for(nomination_id),
    nomination_cache_for(nomination_id, "information.html"), options)

  if not body:
    return {'saved': False, 'ok': False, 'reason': "failed to download"}

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}

  '''
  # TO DO
  ## detect group nominations, particularly for military promotions
  ## detect when a group nomination is split into sub nominations because of divergent Senate action
  '''

  nomination = parse_nomination(nomination_id, body, options)
  output_nomination(nomination, options)
  return {'ok': True, 'saved': True}

def parse_nomination(nomination_id, body, options):
  nomination_type, number, congress = utils.split_nomination_id(nomination_id)

  #remove (and store) comments, which contain some info for the nomination but also mess up the parser
  facts = re.findall("<!--(.+?)-->", body)
  body = re.sub("<!--.+?-->", "", body)

  doc = fromstring(body)
  info = { 'nomination_id': nomination_id, 'actions': [] }

  #the markup on these pages is a disaster, so we're going to use a heuristic based on boldface, inline tags followed by text
  for pair in doc.xpath('//span[@class="elabel"]|//strong'):
    if pair.tail:
        label, data = pair.text.replace(':', '').strip(), pair.tail.strip()

        # handle actions separately
        if label.split(" ")[-1] == "Action":
            pieces = re.split("\s+\-\s+", data)

            location = label.split(" ")[0].lower()

            # use 'acted_at', even though it's always a date, to be consistent
            # with acted_at field on bills and amendments
            acted_at = datetime.strptime(pieces[0], "%B %d, %Y").strftime("%Y-%m-%d")

            # join rest back together (in case action itself has a hyphen)
            text = str.join(" - ", pieces[1:len(pieces)])

            info['actions'].append({
              "type": "action",
              "location": location,
              "acted_at": acted_at,
              "text": text
            })

        else:
            # let's handle these cases one by one
            if label == "Organization":
              info["organization"] = data

            elif label == "Control Number":
              info["control_number"] = data

            elif label == "Referred to":
              info["referred_to"] = data

            elif label == "Reported by":
              info["reported_by"] = data

            elif label == "Nomination":
              # sanity check - verify nomination_id matches
              if nomination_id != data:
                raise Exception("Whoa! Mismatched nomination ID.")

            elif label == "Date Received":
              # Note: Will break with the 1000th congress in year 3789
              match = re.search("(\d{2,3})[stndhr]{2}", data)
              if match:
                info["congress"] = int(match.group(1))
              else:
                raise Exception("Choked, couldn't find Congress in \"%s\"" % data)

              # Doc format is: "January 04, 1995 (104th Congress)"
              info["received_on"] = datetime.strptime(data.split(" (")[0], "%B %d, %Y").strftime("%Y-%m-%d")

            elif label == "Nominee":
              # remove final clause if there
              info["nominee"] = data.split(", vice")[0]
            else:
              logging.info("Unrecognized label: %s" % label)

  '''
  Some of the data is structured fine as is (e.g. Organization, Referred to, Reported by)
  Some needs processing, like date and nominee
  '''

  if not info.get("received_on", None):
    raise Exception("Choked, couldn't find received date.")

  if not info.get("nominee", None):
    raise Exception("Choked, couldn't find nominee info.")

  # get overview from the text of the nomination
  try:
    (name, state, position) = re.search("(.+?), of (.+?), to be (.+?)", info["nominee"]).groups()
  except Exception, e:
    raise Exception("Couldn't parse %s" % info["nominee"])

  info["name"] = name
  info["state_name"] = re.sub("^the ", "", state) #the District -> District

  # if we want to test whether the info in the comments align with the info gleaned from text, can ask if name == facts[-3]
  # doesn't handle suffixes at the moment
  # info["parsed"] = re.search("([A-z-'\s,\.]+),\s([A-z-\']+)([A-z-\'\.\s]*)", facts[-4]).groups()
  info["position"] = facts[-5]
  info["state"] = facts[-6][2:]

  return info

# directory helpers
def output_for_nomination(nomination_id, format):
  nomination_type, number, congress = utils.split_nomination_id(nomination_id)
  return "%s/%s/nominations/%s/%s" % (utils.data_dir(), congress, number, "data.%s" % format)

def nomination_url_for(nomination_id):
  nomination_type, number, congress = utils.split_nomination_id(nomination_id)
  return "http://thomas.loc.gov/cgi-bin/ntquery/z?nomis:%03d%s%05d00:/" % (int(congress), nomination_type.upper(), int(number))

def nomination_cache_for(nomination_id, file):
  nomination_type, number, congress = utils.split_nomination_id(nomination_id)
  return "%s/nominations/%s/%s" % (congress, number, file)

def output_nomination(nomination, options):
  logging.info("[%s] Writing to disk..." % nomination['nomination_id'])

  # output JSON - so easy!
  utils.write(
    json.dumps(nomination, sort_keys=True, indent=2, default=utils.format_datetime),
    output_for_nomination(nomination['nomination_id'], "json")
  )