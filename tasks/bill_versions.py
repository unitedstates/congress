import utils
import os, os.path
import re
import datetime
import logging

import fdsys

def run(options):
  bill_id = options.get('bill_id', None)

  if bill_id:
    bill_type, number, congress = utils.split_bill_id(bill_id)
    to_fetch = bill_version_ids_for(congress, options)
  else:
    congress = options.get('congress', utils.current_congress())
    to_fetch = bill_version_ids_for(congress, options)
    if not to_fetch:
      logging.error("Error figuring out which bills to download, aborting.")
      return None

  limit = options.get('limit', None)
  if limit:
    to_fetch = to_fetch[:int(limit)]

  logging.warn("Going to fetch %i bill versions for congress #%s" % (len(to_fetch), congress))
  
  saved_versions = utils.process_set(to_fetch, fetch_bill, options)


# uses downloaded/cached FDSys sitemap to find all available bill version IDs for this Congress
# a version ID is a "[bill_id]-[version_code]"
def bill_version_ids_for(only_congress, options):
  years = utils.get_congress_years(only_congress)
  only_bill_id = options.get('bill_id', None)

  version_ids = []

  for year in years:

    # don't bother fetching future years
    if year > datetime.datetime.now().year:
      continue
    
    # ensure BILLS sitemap for this year is present
    entries = fdsys.entries_from_collection(year, "BILLS", None, options)

    # some future years may not be ready yet
    if not entries:
      continue

    for entry in entries:
      url, lastmod = entry
      congress, bill_id, bill_version_id = split_url(url)

      # a year may have other congresses in it
      if int(congress) != int(only_congress):
        continue

      # we may be focused on a single bill OD
      if only_bill_id and (bill_id != only_bill_id):
        continue

      version_ids.append(bill_version_id)

  return version_ids


# returns congress, bill_id, and bill_version_id
def split_url(url):
  congress, bill_type, bill_number, version_code = re.match(r"http://www.gpo.gov/fdsys/pkg/BILLS-(\d+)([a-z]+)(\d+)(\D.*)/content-detail.html", url).groups()
  bill_id = "%s%s-%s" % (bill_type, bill_number, congress)
  bill_version_id = "%s-%s" % (bill_id, version_code)

  return congress, bill_id, bill_version_id


# cache a versions.json file for every bill
def version_cache(bill_id):
  return bill_info.bill_cache_for(bill_id, "versions.json")