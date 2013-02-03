import utils
import os, os.path
import re
import json
import datetime
import logging

import fdsys

def run(options):
  bill_id = options.get('bill_id', None)
  bill_version_id = options.get('bill_version_id', None)

  # using a specific bill or version overrides the congress flag/default
  if bill_id:
    bill_type, number, congress = utils.split_bill_id(bill_id)
  elif bill_version_id:
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  else:
    congress = options.get('congress', utils.current_congress())

  if bill_version_id:
    to_fetch = [bill_version_id]
  else:
    to_fetch = bill_version_ids_for(congress, options)
    if not to_fetch:
      logging.error("Error figuring out which bills to download, aborting.")
      return None

  limit = options.get('limit', None)
  if limit:
    to_fetch = to_fetch[:int(limit)]

  logging.warn("Going to fetch %i bill versions for congress #%s" % (len(to_fetch), congress))
  
  saved_versions = utils.process_set(to_fetch, fetch_version, options)


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


# an output text-versions.json for every bill
def output_for_bill_version(bill_version_id):
  bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  return "%s/%s/bills/%s/%s%s/text-versions/%s/data.json" % (utils.data_dir(), congress, bill_type, bill_type, number, version_code)


# cache a file for an individual bill version
def version_cache_for(bill_version_id, filename):
  bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  return "%s/%s/bills/%s/%s%s/versions/%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, version_code, filename)


# e.g. BILLS-113hr302ih
def filename_for(bill_version_id):
  bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  return "BILLS-%s%s%s%s" % (congress, bill_type, number, version_code)



# given an individual bill version ID, download at least the MODs file 
# (and, if requested with --store, the PREMIS file and text documents too)
# and produce a text-versions.json with version codes, version names, 
# the date of publication, and URLs to the MODs, PREMIS, and original docs
def fetch_version(bill_version_id, options):
  logging.info("\n[%s] Fetching..." % bill_version_id)
  
  bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  # bill_id = "%s%s-%s" % (bill_type, number, congress)

  mods_filename = filename_for(bill_version_id)
  mods_cache = version_cache_for(bill_version_id, "mods.xml")
  issued_on, urls = fdsys.document_info_for(mods_filename, mods_cache, options)
  
  bill_version = {
    'issued_on': issued_on,
    'urls': urls,
    'version_code': version_code,
    'bill_version_id': bill_version_id
  }

  # 'bill_version_id': bill_version_id,
  #   'version_code': version_code

  utils.write(
    json.dumps(bill_version, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_bill_version(bill_version_id)
  )

  return {'ok': True, 'saved': True}