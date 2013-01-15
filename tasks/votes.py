import utils, json, iso8601, datetime
import os, os.path
import re, urlparse
import time, datetime
from lxml import html, etree
import logging

import vote_info

def run(options):
  vote_id = options.get('vote_id', None)

  if vote_id:
    vote_chamber, vote_number, congress, session_year = utils.split_vote_id(vote_id)
    to_fetch = [vote_id]
  else:
    congress = options.get('congress', utils.current_congress())
    session_year = options.get('session', str(datetime.datetime.now().year))
    to_fetch = vote_ids_for_house(congress, session_year, options) + vote_ids_for_senate(congress, session_year, options)
    if not to_fetch:
      if not options.get("fast", False):
        logging.error("Error figuring out which votes to download, aborting.")
      else:
        logging.error("No new or recent votes.")
      return None

    limit = options.get('limit', None)
    if limit:
      to_fetch = to_fetch[:int(limit)]

  if options.get('pages_only', False):
    return None

  logging.warn("Going to fetch %i votes from congress #%s session %s" % (len(to_fetch), congress, session_year))
  
  utils.process_set(to_fetch, vote_info.fetch_vote, options)

# page through listing of House votes of a particular congress and session
def vote_ids_for_house(congress, session_year, options):
  vote_ids = []

  index_page = "http://clerk.house.gov/evs/%s/index.asp" % session_year
  group_page = r"ROLL_(\d+)\.asp"
  link_pattern = r"http://clerk.house.gov/cgi-bin/vote.asp\?year=%s&rollnumber=(\d+)" % session_year
  
  # download index page, find the matching links to the paged listing of votes
  page = utils.download(
    index_page,
    "%s/votes/%s/pages/house.html" % (congress, session_year),
    options.get('force', False))

  if not page:
    logging.error("Couldn't download House vote index page, aborting")
    return None

  # extract matching links
  doc = html.document_fromstring(page)
  links = doc.xpath(
    "//a[re:match(@href, '%s')]" % group_page, 
    namespaces={"re": "http://exslt.org/regular-expressions"})

  for link in links:
    # get some identifier for this inside page for caching
    grp = re.match(group_page, link.get("href")).group(1)
    
    # download inside page, find the matching links
    page = utils.download(
      urlparse.urljoin(index_page, link.get("href")),
      "%s/votes/%s/pages/house_%s.html" % (congress, session_year, grp),
      options.get('force', False))
  
    if not page:
      logging.error("Couldn't download House vote group page (%s), aborting" % grp)
      continue
      
    doc = html.document_fromstring(page)
    votelinks = doc.xpath(
      "//a[re:match(@href, '%s')]" % link_pattern, 
      namespaces={"re": "http://exslt.org/regular-expressions"})
      
    for votelink in votelinks:
      num = re.match(link_pattern, votelink.get("href")).group(1)
      vote_id = "h" + num + "-" + str(congress) + "." + session_year
      if not should_process(vote_id, options): continue
      vote_ids.append(vote_id)
          
  return utils.uniq(vote_ids)

def vote_ids_for_senate(congress, session_year, options):
  session_num = int(session_year) - utils.get_congress_first_year(int(congress)) + 1
	
  vote_ids = []
  
  page = utils.download(
    "http://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_%s_%d.xml" % (congress, session_num),
    "%s/votes/%s/pages/senate.xml" % (congress, session_year),
    options.get('force', False),
    is_xml=True)

  if not page:
    logging.error("Couldn't download Senate vote XML index, aborting")
    return None
  
  dom = etree.fromstring(page)
  for vote in dom.xpath("//vote"):
    num = int(vote.xpath("vote_number")[0].text)
    vote_id = "s" + str(num) + "-" + str(congress) + "." + session_year
    if not should_process(vote_id, options): continue
    vote_ids.append(vote_id)
  return vote_ids
  
def should_process(vote_id, options):
  if not options.get("fast", False): return True
  
  # If --fast is used, only download new votes or votes taken in the last
  # three days (when most vote changes and corrections should occur).
  f = vote_info.output_for_vote(vote_id, "json")
  if not os.path.exists(f):
	return True
	
  v = json.load(open(f))
  now = utils.eastern_time_zone.localize(datetime.datetime.now())
  return (now - iso8601.parse_date(v["date"])) < datetime.timedelta(days=3)
  
