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
