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
  
  # get the mapping from THOMAS's committee names to THOMAS's committee IDs
  # found on the advanced search page. committee_names[congress][name] = ID
  # with subcommittee names as the committee name plus a pipe plus the subcommittee
  # name.
  committee_names = bill_info.fetch_committee_names(congress, options)

  errors = []
  saved = []
  skips = []

  for bill_id in to_fetch:
    try:
      results = bill_info.fetch_bill(bill_id, committee_names, options)
    except Exception, e:
      if options.get('raise', False):
        raise
      else:
        errors.append((bill_id, e))
        continue

    if results.get('ok', False):
      if results.get('saved', False):
        saved.append(bill_id)
        logging.info("[%s] Updated bill" % bill_id)
      else:
        skips.append(bill_id)
        logging.error("[%s] Skipping bill: %s" % (bill_id, results['reason']))
    else:
      errors.append((bill_id, results))
      logging.error("[%s] Error: %s" % (bill_id, results['reason']))

  if len(errors) > 0:
    message = "\nErrors for %s bills:\n" % len(errors)
    for bill_id, error in errors:
      if isinstance(error, Exception):
        message += "[%s] Exception:\n\n" % bill_id
        message += utils.format_exception(error)
      else:
        message += "[%s] %s" % (bill_id, error)
    utils.admin(message) # email if possible

  logging.error("\nSkipped %s bills." % len(skips))
  logging.warning("Saved data for %s bills." % len(saved))


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
  
