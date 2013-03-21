import re
import utils
import logging
from lxml.html import fromstring
from lxml.html import clean

def amdt_cache_for(amdt_id, file):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/amendments/%s/%s%s/%s" % (congress, amdt_type, amdt_type, number, file)

def fetch_amendment_text(body, amdt_id, options):
    #mimicking the regex approach in actions_for()
    #follow the "TEXT OF AMENDMENT [AS SUBMITTED]" link from the info page we've already scraped (cached as information.html)
    try:
        landing_page_url = "http://thomas.loc.gov" + re.search("TEXT OF AMENDMENT.*?<a href=\"(.*?)\">", body, re.I | re.S).group(1)
    except:
        logging.info("Couldn't find link to text. May not be posted yet.")
        return None
        
    landing_body = utils.download(landing_page_url,
      amdt_cache_for(amdt_id, "text_links.html"),
      {"force": True})

    #this sometimes gets us to a landing page with a second "TEXT OF AMENDMENT" link, so try and follow it again
    try:
      landing_page_url = "http://thomas.loc.gov" + re.search("TEXT OF AMENDMENT.*?<a href=\"(.*?)\">", landing_body, re.I | re.S).group(1)
      landing_body = utils.download(landing_page_url, 
        amdt_cache_for(amdt_id, "text_links.html"),
        {"force": True})
    except Exception, e:
      logging.info("No secondard landing page detected")

    #get print friendly version
    print_friendly_url = re.search("<a href=\"(.+?)\"><em>Print", landing_body)
    if not print_friendly_url:
        logging.info("No print friendly url detected")
        return None

    #try downloading pfv
    try:
        print_friendly_url = "http://thomas.loc.gov" + print_friendly_url.group(1)
        logging.info(print_friendly_url)
        fulltext = fromstring(utils.download(print_friendly_url, 
            amdt_cache_for(amdt_id, "fulltext.html"), options))

        #very lazy, but can't figure out encoding right this second
        parsed = "\n".join(fulltext.xpath("//p/text()")).replace('&nbsp;', " ").encode('utf-8')
        return parsed
    
    except Exception, e:
        logging.info(e)
        logging.info(print_friendly_url.groups())
        return None
    
    '''      
    pages = [x for x in cr.xpath("//a") if len(x.xpath("text()"))]

    logging.info("Found %i pages in the Congressional record to scan" % len(pages))
    for page in pages:
      logging.info("Page %s" % page.xpath("text()"))
                              
    '''
