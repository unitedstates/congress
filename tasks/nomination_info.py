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
        if label.split(" ")[-1] == "Action":
            data = re.split("\s+\-\s+", data)
            info['actions'].append((label, data[0], data[1]))
        else:
            info[label.lower()] = data

  '''
  Some of the data is structured fine as is (e.g. Organization, Referred to, Reported by)
  Some needs processing, like date and nominee
  '''
  
  # Doc format is: "January 04, 1995 (104th Congress)"
  info["date"] = datetime.strptime(info["date received"].split(" (")[0], "%B %d, %Y").strftime("%Y-%m-%d")
  # Note: Will break with the 1000th congress in year 3789
  info["congress"] = int(re.search("(\d{2,3})[stndhr]{2}", info["date received"]).group(1))
  
  # remove final caluse if there
  info["nominee"] = info["nominee"].split(", vice")[0]
  
  # get overview from the text of the nomination
  try:
    (name, state, position) = re.search("(.+?), of (.+?), to be (.+?)", info["nominee"]).groups()
  except Exception, e:
    logging.error("Couldn't parse %s" % info["nominee"])
    (name, state, position) = ("", "", "")    
    
  info["name"] = name
  info["state"] = re.sub("^the ", "", state) #the District -> District
  info["parsed"] = ""
  info["position"] = ""
  info["st_abbr"] = ""

  # if we want to test whether the info in the comments align with the info gleaned from text, can ask if name == facts[-3]
  #doesn't handle suffixes at the moment
  info["parsed"] = re.search("([A-z-'\s,\.]+),\s([A-z-\']+)([A-z-\'\.\s]*)", facts[-4]).groups()
  info["position"] = facts[-5]
  info["st_abbr"] = facts[-6][2:]
  
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