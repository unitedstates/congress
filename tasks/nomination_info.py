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
            info[label] = data

  '''
  #TO DO
  ## Process the raw info from the page to extract home state, dates, etc
  '''  
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
  return "%s/nomination/%s/%s" % (congress, number, file)

def output_nomination(nomination, options):
  logging.info("[%s] Writing to disk..." % nomination['nomination_id'])

  # output JSON - so easy!
  utils.write(
    json.dumps(nomination, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_nomination(nomination['nomination_id'], "json")
  )

#for testing purposes only
fetch_nomination("PN100-112", {}) 
fetch_nomination("PN1-113", {}) 
fetch_nomination("PN900-102", {}) 