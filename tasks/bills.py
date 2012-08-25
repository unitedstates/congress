import utils
from utils import log
import os
import time
from lxml import html

def run(options):
  session = options.get('session', utils.current_session())
  bill_id = options.get('bill_id', None)

  if bill_id:
    to_fetch = [bill_id]
  else:
    to_fetch = bill_ids_for(session, options)
    if not to_fetch:
      log("Error figuring out which bills to download, aborting.")
      return None

    limit = options.get('limit', None)
    if limit:
      to_fetch = to_fetch[:int(limit)]

  print "Going to fetch %i bills from session #%s" % (len(to_fetch), session)

  for bill_id in to_fetch:
    # fetch_bill(bill_id, options)
    log("Updated bill %s" % bill_id)


# page through listings for bills of a particular session
def bill_ids_for(session, options):
  bill_ids = []

  bill_type = options.get('bill_type', None)
  if bill_type:
    bill_types = [bill_type]
  else:
    bill_types = thomas_types.keys()

  for bill_type in bill_types:
    
    # match only links to landing pages of this bill type
    # it shouldn't catch stray links outside of the confines of the 100 on the page,
    # but if it does, no big deal
    link_pattern = "^\s*%s\d+\s*$" % thomas_types[bill_type][1]

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
        bill_ids.append(link.text.lower().replace(".", "").replace(" ", ""))

      if len(links) < 100:
        break

      offset += 100

      # sanity check, while True loops are dangerous
      if offset > 10000:
        break

      # rate-limit
      time.sleep(0.5)

  return utils.uniq(bill_ids)


# download and cache landing page for bill
def fetch_bill(bill_id, options):
  body = utils.download(
    handle_for(bill_id), 
    handle_cache_for(bill_id, "home.html"),
    options.get('force', False))

  print body


# helpers

def handle_for(bill_id):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "http://hdl.loc.gov/loc.uscongress/legislation.%s%s%s" % (session, bill_type, number)

def handle_cache_for(bill_id, file):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "data/bills/%s/%s%s/%s" % (session, bill_type, number, file)

def page_for(session, bill_type, offset):
  thomas_type = thomas_types[bill_type][0]
  return "http://thomas.loc.gov/cgi-bin/bdquery/d?d%s:%s:./list/bss/d%s%s.lst:[[o]]" % (session, offset, session, thomas_type)

def page_cache_for(session, bill_type, offset):
  return "data/bills/%s/pages/%s/%i.html" % (session, bill_type, offset)


# useful translations

thomas_types = {
  'hr': ('HR', 'H.R.'),
  'hres': ('HE', 'H.RES.'),
  'hjres': ('HJ', 'H.J.RES.'),
  'hconres': ('HC', 'H.CON.RES.'),
  's': ('SN', 'S.'),
  'sres': ('SE', 'S.RES.'),
  'sjres': ('SJ', 'S.J.RES.'),
  'sconres': ('SC', 'S.CON.RES.'),
}  