import re
import iso8601
from dateutil import tz
import datetime

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