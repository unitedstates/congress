import os
import re
import iso8601
from dateutil import tz
import datetime

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
  return re.match("([a-z]+)(\d+)-(\d+)", bill_id).groups()

def download(url, destination):
  if os.path.exists(destination):
    log("Cached: %s" % url)
    with open(destination, 'r') as f:
      return f.read()
  else:
    return download_now(url, destination)

def download_now(url, destination):
  try:
    log("Downloading: %s" % url)
    response = urllib2.urlopen(url)
    body = response.read()
  except URLError, e:
    log(e.reason)
    return None

  # cache content to disk
  os.makedirs(os.path.dirname(destination))
  f = open(destination, 'w')
  f.write(body)
  f.close()

  return body