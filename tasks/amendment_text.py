import re
import utils
import logging
import json
from utils import download, write
from lxml.html import fromstring, tostring
import datetime
import fdsys

def amdt_cache_for(amdt_id, file):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/amendments/%s/%s%s/%s" % (congress, amdt_type, amdt_type, number, file)

def output_for_bill(bill_id, format):
  bill_type, number, congress = utils.split_bill_id(bill_id)
  return "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, "data.%s" % format)

def fetch_amendment_text(body, amdt, options):  
  year,month,day = amdt['submitted_at'].split('-')
  #accord to GPO, 2=Monday - 6=Friday
  weekday = datetime.datetime.strptime(amdt['submitted_at'], "%Y-%m-%d").weekday() + 2
  
  url = 'http://www.gpo.gov/fdsys/browse/collection.action?collectionCode=CREC&browsePath=%s/%s/%s-%s\/%s/%s' % (year,month,month,day,weekday,'SENATE')
  body = download(url, "fdsys/package/%s/%s/%s/toc.html" % (year, 'CREC', amdt['submitted_at']))

  #the amendments are identified a little differently on different days, so it's best to start with a specific search then fall back
  text_link = re.findall("TEXT OF AMENDMENTS(.*?)<a href=\"http://www.gpo.gov:80/(fdsys/pkg/CREC-\d+-\d+-\d+/html/CREC-\d+-\d+-\d+-[A-z]+\d+-[A-z]+[0-9-]+)\.htm", body, re.I | re.S)
  if not len(text_link):
    text_link = re.findall("AMENDMENT(.*?)<a href=\"http://www.gpo.gov:80/(fdsys/pkg/CREC-\d+-\d+-\d+/html/CREC-\d+-\d+-\d+-[A-z]+\d+-[A-z]+\d+-\d+)\.htm", body, re.I | re.S)
    if not len(text_link):
      logging.info("Couldn't find link to text of %s on %s in Congressional Record" % (amdt['amendment_id'], amdt['submitted_at']))
      exit()
      return None
    
  text_link = "http://www.gpo.gov:80/" + text_link[0][1] + ".htm"
  body = download(text_link, "fdsys/package/%s/%s/%s/amendments.html" % (year, 'CREC', amdt['submitted_at']))
  amend = re.findall("SA " + amdt['number'] + "\. (Mr?s?\.) ([A-Z'ca-]+) (\(.*?\))?(.*?)\n\n(.*?)______", body, re.DOTALL)
  try:
    text = [x.strip() for x in amend[0]]
  except:
    logging.info("Couldn't find the amendment in the text")
    return None
  
  data = {
    'number': amdt['number'],
    'sponsored_by': text[1].title(),
    'cosponsors': text[2],
    'intro': re.sub("\s+", " ", text[3]),
    'text': text[4]
  }
  write(json.dumps(data, indent=2), "data/%s/amendments/samdt/samdt%s/text.json" % (amdt['congress'], data['number']))
  
def fetch_amendment_text_old(body, amdt, options):
    #mimicking the regex approach in actions_for()
    #follow the "TEXT OF AMENDMENT [AS SUBMITTED]" link from the info page we've already scraped (cached as information.html)
    try:
        landing_page_url = "http://thomas.loc.gov" + re.search("TEXT OF AMENDMENT.*?<a href=\"(.*?)\">", body, re.I | re.S).group(1)
    except:
        logging.info("Couldn't find link to text. May not be posted yet.")
        return None
        
    landing_body = utils.download(landing_page_url,
      amdt_cache_for(amdt["amendment_id"], "text_links.html"),
      {"force": True})

    #this sometimes gets us to a landing page with a second "TEXT OF AMENDMENT" link, so try and follow it again
    try:
      landing_page_url = "http://thomas.loc.gov" + re.search("TEXT OF AMENDMENT.*?<a href=\"(.*?)\">", landing_body, re.I | re.S).group(1)
      landing_body = utils.download(landing_page_url, 
        amdt_cache_for(amdt["amendment_id"], "text_links.html"),
        {"force": True})
    except Exception, e:
      logging.info("No secondard landing page detected")

    #get print friendly version
    print_friendly_url = re.search("<a href=\"(.+?)\"><em>Print", landing_body)
    if not print_friendly_url:
        logging.info("No print friendly url detected")
        return None

    #try downloading pfv
    #try:
    print_friendly_url = "http://thomas.loc.gov" + print_friendly_url.group(1)
    logging.info(print_friendly_url)
    fulltext = fromstring(utils.download(print_friendly_url, 
        amdt_cache_for(amdt["amendment_id"], "fulltext.html"), options).replace("&nbsp;", ""))

    #get raw text just of amendments. Many pages have multiple amendments on, since these pages
    #directly reflect the Congressional Record
    contents = "\n".join([x.text_content() for x in fulltext.xpath("//div[@id='container']/p")]) + "END"

    #Make a regex to find the amendment we want
    #Tacking on "END" is dump, but I'm drawing a \s
    rep = "SA " + amdt["number"] + "\. (.*?)(SA \d+\.|END$)"
    
    fulltext = re.search(rep, contents, re.DOTALL)
    if fulltext:
      text = "\n".join(fulltext.groups()[:2]).encode('ascii', 'replace')
      return text

    logging.info("Couldn't find amendment on the text. (Check cache for raw HTML)")
    return False



#members = json.load(open("data/members/thomas_senate.json", 'r'))

#take a link from gpo to text of amendments and parse it
#this does not belong here
def fetch_amendment_text_from_gpo(url, session):
    text = download(url, "record/" + url.split("pkg/")[1].replace('/', '-'))
    text = re.sub("\[\[Page S\d+\]\]", "", text)
    #amends = re.findall("SA (\d+)\. (Mr?s?\.) ([A-Z-']+) (\(.*?\))?(.*?)", text, re.DOTALL)
    
    amends = re.findall("SA (\d+)\. (Mr?s?\.) ([A-Z'ca-]+) (\(.*?\))?(.*?)\n\n(.*?)______", text, re.DOTALL)
    for amend in amends:
        text = [x.strip() for x in amend]
        data = {
            'number': text[0],
            'sponsored_by': text[2].title(),
            'cosponsors': text[3],
            'intro': re.sub("\s+", " ", text[4]),
            'text': text[5]
        }

        try:
          info = json.load(open("data/%d/amendments/samdt/samdt%s/data.json" % (session, amend[0]), 'r'))
        except Exception, e:
          print e
          continue
        data["sponsor"] = info["sponsor"]
        data["sponsor"]["name"] = members[info["sponsor"]["thomas_id"]]["name"]["official_full"]
        data["sponsor"]["party"] = members[info["sponsor"]["thomas_id"]]["terms"][-1]["party"]
        data["sponsor"]["state"] = members[info["sponsor"]["thomas_id"]]["terms"][-1]["state"]
        write(json.dumps(data, indent=2), "data/%d/amendments/samdt/samdt%s/cr_text.json" % (session, amend[0]))


#fetch_amendment_text_from_gpo('http://www.gpo.gov/fdsys/pkg/CREC-2013-03-20/html/CREC-2013-03-20-pt1-PgS2038.htm', 113)
#fetch_amendment_text_from_gpo('http://www.gpo.gov/fdsys/pkg/CREC-2013-03-21/html/CREC-2013-03-21-pt1-PgS2169.htm', 113)
#fetch_amendment_text_from_gpo('http://www.gpo.gov/fdsys/pkg/CREC-2013-03-22/html/CREC-2013-03-22-pt1-PgS2343.htm', 113)

