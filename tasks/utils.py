import os, errno, socket
import time
import re, htmlentitydefs
import iso8601
from dateutil import tz
from pytz import timezone
import datetime, time
from lxml import html

import urllib
import urllib2
from urllib2 import HTTPError, URLError

import scrapelib

import pprint

# scraper should be instantiated at class-load time, so that it can rate limit appropriately
scraper = scrapelib.Scraper(requests_per_minute=120, follow_robots=False, retry_attempts=3)

def log(object):
  if isinstance(object, str):
    print object
  else:
    pprint.pprint(object)

def format_datetime(obj):
  if isinstance(obj, datetime.datetime):
    return obj.replace(microsecond=0, tzinfo=timezone("US/Eastern")).isoformat()
  else:
    return None

def EST():
  return tz.gettz("America/New_York")

def in_est(dt):
  return dt.astimezone(EST())

def current_congress(year=None):
  if not year:
    year = datetime.datetime.now().year
  return ((year + 1) / 2) - 894

def split_bill_id(bill_id):
  return re.match("^([a-z]+)(\d+)-(\d+)$", bill_id).groups()

def download(url, destination, force=False):
  cache = "cache/%s" % destination
  if not force and os.path.exists(cache):
    log("Cached: (%s, %s)" % (cache, url))
    with open(cache, 'r') as f:
      body = f.read()
  else:
    try:
      log("Downloading: %s" % url)
      response = scraper.urlopen(url)
      body = str(response)
    except HTTPError as e:
      log("Error downloading %s" % url)
      return None

    # cache content to disk
    write(body, cache)

  return body

def write(content, destination):
  mkdir_p(os.path.dirname(destination))
  f = open(destination, 'w')
  f.write(content)
  f.close()

def fetch_html(url):
  try:
    log("Fetching: %s" % url)
    response = urllib2.urlopen(url)
    body = response.read()
    return html.document_fromstring(body)
  except URLError, e:
    log(e.reason)
    return None

# de-dupe a list, taken from:
# http://stackoverflow.com/questions/480214/how-do-you-remove-duplicates-from-a-list-in-python-whilst-preserving-order
def uniq(seq):
    seen = set()
    seen_add = seen.add
    return [ x for x in seq if x not in seen and not seen_add(x)]

import os, errno

# mdir -p in python, from:
# http://stackoverflow.com/questions/600268/mkdir-p-functionality-in-python
def mkdir_p(path):
  try:
    os.makedirs(path)
  except OSError as exc: # Python >2.5
    if exc.errno == errno.EEXIST:
      pass
    else: 
      raise

def xpath_regex(doc, element, pattern):
  return doc.xpath(
    "//%s[re:match(text(), '%s')]" % (element, pattern), 
    namespaces={"re": "http://exslt.org/regular-expressions"})

# taken from http://effbot.org/zone/re-sub.htm#unescape-html
def unescape(text):
  def fixup(m):
    text = m.group(0)
    if text[:2] == "&#":
      # character reference
      try:
        if text[:3] == "&#x":
          return unichr(int(text[3:-1], 16))
        else:
          return unichr(int(text[2:-1]))
      except ValueError:
        pass
    else:
      # named entity
      try:
        text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
      except KeyError:
        pass
    return text # leave as is
  return re.sub("&#?\w+;", fixup, text)

def extract_bills(text, session):
  bill_ids = []
  
  p = re.compile('((S\.|H\.)(\s?J\.|\s?R\.|\s?Con\.| ?)(\s?Res\.)*\s?\d+)', flags=re.IGNORECASE)
  bill_matches = p.findall(text)
  
  if bill_matches:
    for b in bill_matches:
      bill_text = "%s-%s" % (b[0].lower().replace(" ", '').replace('.', '').replace("con", "c"), session)
      if bill_text not in bill_ids:
        bill_ids.append(bill_text)
  
  return bill_ids

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