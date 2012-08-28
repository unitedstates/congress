import os, errno, socket
import time
import re
import iso8601
from dateutil import tz
from pytz import timezone
import datetime, time
from lxml import html

import urllib
import urllib2
from urllib2 import HTTPError, URLError

import pprint

def log(object):
  if isinstance(object, str):
    print object
  else:
    pprint.pprint(object)

def EST():
  return tz.gettz("America/New_York")

def in_est(dt):
  return dt.astimezone(EST())

def current_session(year=None):
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
      response = urllib2.urlopen(url)
      body = response.read()
    except socket.timeout, e:
      try:
        log("Timeout, re-downloading: %s" % url)
        time.sleep(2)
        response = urllib2.urlopen(url)
        body = response.read()
      except (URLError, socket.timeout), e:
        log(e.reason)
        return None      

    except URLError, e:
      log(e.reason)
      return None

    # cache content to disk
    write(body, cache)

    # rate-limit but only if we used the network
    time.sleep(0.5)

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

def format_datetime(v):
  if type(v) == float:
    v = datetime.datetime.fromtimestamp(v)
  if type(v) == datetime.datetime:
    v = v.replace(microsecond=0, tzinfo=timezone("US/Eastern"))
  return v.isoformat()


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