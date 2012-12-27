import utils
import os
import re
import time
from lxml import html
import logging

import bill_info

def run(options):
  bill_id = options.get('bill_id', None)

  if bill_id:
    bill_type, number, congress = utils.split_bill_id(bill_id)
    to_fetch = [bill_id]
  else:
    congress = options.get('congress', utils.current_congress())
    to_fetch = bill_ids_for(congress, options)
    if not to_fetch:
      logging.error("Error figuring out which bills to download, aborting.")
      return None

    limit = options.get('limit', None)
    if limit:
      to_fetch = to_fetch[:int(limit)]

  if options.get('pages_only', False):
    return None

  print "Going to fetch %i bills from congress #%s" % (len(to_fetch), congress)
  
  utils.process_set(to_fetch, bill_info.fetch_bill, options)


# page through listings for bills of a particular congress
def bill_ids_for(congress, options):
  bill_ids = []

  bill_type = options.get('bill_type', None)
  if bill_type:
    bill_types = [bill_type]
  else:
    bill_types = utils.thomas_types.keys()

  for bill_type in bill_types:
    
    # match only links to landing pages of this bill type
    # it shouldn't catch stray links outside of the confines of the 100 on the page,
    # but if it does, no big deal
    link_pattern = "^\s*%s\d+\s*$" % utils.thomas_types[bill_type][1]

    # loop through pages and collect the links on each page until 
    # we hit a page with < 100 results, or no results
    offset = 0
    while True:
      # download page, find the matching links
      page = utils.download(
        page_for(congress, bill_type, offset),
        page_cache_for(congress, bill_type, offset),
        options.get('force', False))

      if not page:
        logging.error("Couldn't download page with offset %i, aborting" % offset)
        return None

      # extract matching links
      doc = html.document_fromstring(page)
      links = doc.xpath(
        "//a[re:match(text(), '%s')]" % link_pattern, 
        namespaces={"re": "http://exslt.org/regular-expressions"})

      # extract the bill ID from each link
      for link in links:
        code = link.text.lower().replace(".", "").replace(" ", "")
        bill_ids.append("%s-%s" % (code, congress))

      if len(links) < 100:
        break

      offset += 100

      # sanity check, while True loops are dangerous
      if offset > 100000:
        break

  return utils.uniq(bill_ids)



def page_for(congress, bill_type, offset):
  thomas_type = utils.thomas_types[bill_type][0]
  congress = int(congress)
  return "http://thomas.loc.gov/cgi-bin/bdquery/d?d%03d:%s:./list/bss/d%03d%s.lst:[[o]]" % (congress, offset, congress, thomas_type)

def page_cache_for(congress, bill_type, offset):
  return "%s/bills/pages/%s/%i.html" % (congress, bill_type, offset)
