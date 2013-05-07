import utils
import os, os.path
import re
from lxml import html, etree
import logging

import bill_info

def run(options):
  bill_id = options.get('bill_id', None)
  
  search_state = { }

  if bill_id:
    bill_type, number, congress = utils.split_bill_id(bill_id)
    to_fetch = [bill_id]
  else:
    congress = options.get('congress', utils.current_congress())
    to_fetch = bill_ids_for(congress, options, bill_states=search_state)
    if not to_fetch:
      if options.get("fast", False):
        logging.warn("No bills changed.")
      else:
        logging.error("Error figuring out which bills to download, aborting.")
      return None

    limit = options.get('limit', None)
    if limit:
      to_fetch = to_fetch[:int(limit)]

  logging.warn("Going to fetch %i bills from congress #%s" % (len(to_fetch), congress))
  
  saved_bills = utils.process_set(to_fetch, bill_info.fetch_bill, options)
  
  save_bill_search_state(saved_bills, search_state)

# page through listings for bills of a particular congress
def bill_ids_for(congress, options, bill_states={}):
  
  # override if we're actually using this method to get amendments
  doing_amendments = options.get('amendments', False)

  bill_ids = []

  bill_type = options.get('bill_type' if not doing_amendments else 'amendment_type', None)
  if bill_type:
    bill_types = [bill_type]
  else:
    bill_types = utils.thomas_types.keys()
    
  for bill_type in bill_types:
    
    # This sub is re-used for pulling amendment IDs too.
    if (bill_type in ('samdt', 'hamdt')) != doing_amendments: continue

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
        options)

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
        bill_id = "%s-%s" % (code, congress)
        
        if options.get("fast", False):
          fast_cache_path = utils.cache_dir() + "/" + bill_info.bill_cache_for(bill_id, "search_result.html")
          old_state = utils.read(fast_cache_path)

          # Compare all of the output in the search result's <p> tag, which
          # has last major action, number of cosponsors, etc. to a cache on
          # disk to see if any major information about the bill changed.
          parent_node = link.getparent() # the <p> tag containing the whole search hit
          parent_node.remove(parent_node.xpath("b")[0]) # remove the <b>###.</b> node that isn't relevant for comparison
          new_state = etree.tostring(parent_node) # serialize this tag

          if old_state == new_state:
            logging.info("No change in search result listing: %s" % bill_id)
            continue
          
          bill_states[bill_id] = new_state
        
        bill_ids.append(bill_id)

      if len(links) < 100:
        break

      offset += 100

      # sanity check, while True loops are dangerous
      if offset > 100000:
        break

  return utils.uniq(bill_ids)

def save_bill_search_state(saved_bills, search_state):
  # For --fast mode, cache the current search result listing (in search_state)
  # to disk so we can detect major changes to the bill through the search
  # listing rather than having to parse the bill.
  for bill_id in saved_bills:
    if bill_id in search_state:
      fast_cache_path = utils.cache_dir() + "/" + bill_info.bill_cache_for(bill_id, "search_result.html")
      new_state = search_state[bill_id]
      utils.write(new_state, fast_cache_path)

def page_for(congress, bill_type, offset):
  thomas_type = utils.thomas_types[bill_type][0]
  congress = int(congress)
  return "http://thomas.loc.gov/cgi-bin/bdquery/d?d%03d:%s:./list/bss/d%03d%s.lst:[[o]]" % (congress, offset, congress, thomas_type)

def page_cache_for(congress, bill_type, offset):
  return "%s/bills/pages/%s/%i.html" % (congress, bill_type, offset)
