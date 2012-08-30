import utils
from utils import log
import os
import time
from lxml import html

import bill_info

def run(options):
  bill_id = options.get('bill_id', None)

  if bill_id:
    bill_type, number, session = utils.split_bill_id(bill_id)
    to_fetch = [bill_id]
  else:
    session = options.get('session', utils.current_session())
    to_fetch = bill_ids_for(session, options)
    if not to_fetch:
      log("Error figuring out which bills to download, aborting.")
      return None

    limit = options.get('limit', None)
    if limit:
      to_fetch = to_fetch[:int(limit)]


  print "Going to fetch %i bills from session #%s" % (len(to_fetch), session)

  errors = []
  saved = []
  skips = []

  for bill_id in to_fetch:
    results = bill_info.fetch_bill(bill_id, options)
    
    if results.get('ok', False):
      if results.get('saved', False):
        saved.append(bill_id)
        log("[%s] Updated bill" % bill_id)
      else:
        skips.append(bill_id)
        log("[%s] Skipping bill: %s" % (bill_id, results['reason']))
    else:
      errors.append(results)
      log("[%s] Error: %s" % (bill_id, results['reason']))

  if len(errors) > 0:
    log("Errors:")
    for error in errors:
      log("[%s] Error: %s" % (bill_id, results['reason']))

  log("Skipped %s bills." % len(skips))
  log("Saved data for %s bills." % len(successes))


# page through listings for bills of a particular session
def bill_ids_for(session, options):
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
        page_for(session, bill_type, offset),
        page_cache_for(session, bill_type, offset),
        options.get('force', False))

      if not page:
        log("Couldn't download page with offset %i, aborting" % offset)
        return None

      # extract matching links
      doc = html.document_fromstring(page)
      links = doc.xpath(
        "//a[re:match(text(), '%s')]" % link_pattern, 
        namespaces={"re": "http://exslt.org/regular-expressions"})

      # extract the bill ID from each link
      for link in links:
        code = link.text.lower().replace(".", "").replace(" ", "")
        bill_ids.append("%s-%s" % (code, session))

      if len(links) < 100:
        break

      offset += 100

      # sanity check, while True loops are dangerous
      if offset > 10000:
        break

  return utils.uniq(bill_ids)



def page_for(session, bill_type, offset):
  thomas_type = utils.thomas_types[bill_type][0]
  return "http://thomas.loc.gov/cgi-bin/bdquery/d?d%s:%s:./list/bss/d%s%s.lst:[[o]]" % (session, offset, session, thomas_type)

def page_cache_for(session, bill_type, offset):
  return "bills/%s/pages/%s/%i.html" % (session, bill_type, offset)