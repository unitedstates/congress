import re
import utils
import logging
from lxml.html import fromstring, tostring

def amdt_cache_for(amdt_id, file):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/amendments/%s/%s%s/%s" % (congress, amdt_type, amdt_type, number, file)

def fetch_amendment_text(body, amdt, options):
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
