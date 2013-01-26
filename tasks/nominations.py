import utils
import os, os.path
import re
from lxml import html, etree
import logging

import nomination_info

def run(options):
  nomination_id = options.get('nomination_id', None)
  
  if nomination_id:
    nomination_type, number, congress = utils.split_nomination_id(nomination_id)
    to_fetch = [nomination_id]
  else:
    congress = options.get('congress', utils.current_congress())
    to_fetch = nomination_ids_for(congress, options)
    if not to_fetch:
      if options.get("fast", False):
        logging.warn("No nominations changed.")
      else:
        logging.error("Error figuring out which nominations to download, aborting.")
      return None

    limit = options.get('limit', None)
    if limit:
      to_fetch = to_fetch[:int(limit)]

  logging.warn("Going to fetch %i nominations from congress #%s" % (len(to_fetch), congress))
  
  saved_nominations = utils.process_set(to_fetch, nomination_info.fetch_nomination, options)  

# page through listings for bills of a particular congress
def nomination_ids_for(congress, options = {}):  
  nomination_ids = []

  page = page_for(congress)
  if not page:
    logging.error("Couldn't download page for %d congress" % congress)
    return None

  # extract matching links
  doc = html.document_fromstring(page)
  nomination_ids = doc.xpath('//div[@id="content"]/p[2]/a/text()')
  nomination_ids = [x.split(' ')[1] for x in nomination_ids]

  return utils.uniq(nomination_ids)

def page_cache_for(congress):
  return "%s/nominations/pages/search.html" % congress
  
#unlike bills.py, we're going to fetch the page instead of producing the URL, since a POST is required (I think)
#currently only gets civilian nominations
#TO DO: include military
def page_for(congress):
  congress = int(congress)
  postdata = {
    "database": "nominations",
    "MaxDocs":'',
    "querytype":"phrase",
    "query":"",
    "Stemming":"Yes",
    "congress":"%d" % congress,
    "CIVcategory":"on",
    "committee":"",
    "LBDateSel":"FLD606",
    "EBSDate":"",
    "EBEDate":"",
    "sort":"sh_docid_c",
    "submit":"SEARCH"
  }

  page = utils.download("http://thomas.loc.gov/cgi-bin/thomas",
        page_cache_for(congress), 
        { 'postdata': postdata }
  )
  return page 