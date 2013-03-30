import re
import utils
import logging
import json
from utils import download, write
from lxml.html import fromstring, tostring
import datetime
import fdsys
import glob
from lxml import etree

def run(options):
  # ./run amendment_text --year=2013
  
  # Update the MODSs files for the Congressional Record for the given year.
  fdsys.update_sitemap_cache(["CREC"], { "year": options['year'] })
  fdsys.mirror_files(["CREC"], { "year": options['year'], "store": "mods" })

  # Loop through MODS files in the sitemap for the CR for a particular year
  # to find granules for amendment text.
  granules = []
  sitemap = "%s/fdsys/sitemap/%d/CREC.xml" % (utils.cache_dir(), int(options['year']))
  for package_name, lastmod in fdsys.get_sitemap_entries(sitemap):
    # Look for a Text of Amendments section.
    fn = "%s/fdsys/CREC/%d/%s/mods.xml" % (utils.data_dir(), int(options['year']), package_name)
    dom = etree.parse(fn).getroot()
    mods_ns = {"m": "http://www.loc.gov/mods/v3"}
    for n in dom.xpath("m:relatedItem[@type='constituent']", namespaces=mods_ns):
      title = n.xpath("string(m:titleInfo/m:title)", namespaces=mods_ns)
      if title in ('TEXT OF AMENDMENTS',):
      	# We want this granule.
        granule_uri = n.xpath("string(m:identifier[@type='uri'])", namespaces=mods_ns)
        granule_name = re.match(r".*/(.*)", granule_uri).group(1)
        
	    # Mirror the text format of the relevant granules.
        fdsys.mirror_file(options["year"], "CREC", package_name, lastmod, granule_name, ["text"], options)


####

#members = json.load(open("data/members/thomas_senate.json", 'r'))

def amdt_cache_for(amdt_id, file):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/amendments/%s/%s%s/%s" % (congress, amdt_type, amdt_type, number, file)

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

  #attempt to retrieve sponsor info
  try:
    info = json.load(open("data/%s/amendments/samdt/samdt%s/data.json" % (amdt['congress'], amdt['number']), 'r'))
    #data["sponsor"] = info["sponsor"]
    info["sponsor"]["name"] = members[info["sponsor"]["thomas_id"]]["name"]["official_full"]
    info["sponsor"]["party"] = members[info["sponsor"]["thomas_id"]]["terms"][-1]["party"][0]
    #data["sponsor"]["state"] = members[info["sponsor"]["thomas_id"]]["terms"][-1]["state"]
    data["info"] = info
  except Exception, e:
    print e

  write(json.dumps(data, indent=2), "data/%s/amendments/samdt/samdt%s/text.json" % (amdt['congress'], data['number']))
