import os, errno, sys, traceback
import time
import re, htmlentitydefs
from dateutil import tz
import yaml
from pytz import timezone
import datetime, time
from lxml import html
import scrapelib
import pprint
import logging

import smtplib
import email.utils
from email.mime.text import MIMEText
import getpass


# read in an opt-in config file for changing directories and supplying email settings
# returns None if it's not there, and this should always be handled gracefully
path = "config.yml"
if os.path.exists(path):
  config = yaml.load(open(path, 'r'))
else:
  config = None


# scraper should be instantiated at class-load time, so that it can rate limit appropriately
scraper = scrapelib.Scraper(requests_per_minute=120, follow_robots=False, retry_attempts=3)


def format_datetime(obj):
  if isinstance(obj, datetime.datetime):
    return obj.replace(microsecond=0, tzinfo=timezone("US/Eastern")).isoformat()
  elif isinstance(obj, str):
    return obj
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

def download(url, destination, force=False, options={}):
  test = options.get('test', False)

  if test:
    cache = test_cache_dir()
  else:
    cache = cache_dir()

  cache_path = os.path.join(cache, destination)

  if not force and os.path.exists(cache_path):
    if not test: logging.info("Cached: (%s, %s)" % (cache, url))
    with open(cache_path, 'r') as f:
      body = f.read()
  else:
    try:
      logging.info("Downloading: %s" % url)
      response = scraper.urlopen(url)
      body = str(response)
    except scrapelib.HTTPError as e:
      logging.error("Error downloading %s:\n\n%s" % (url, format_exception(e)))
      return None

    # don't allow 0-byte files
    if (not body) or (not body.strip()):
      return None

    # cache content to disk
    write(body, cache_path)

  return unescape(body)

def write(content, destination):
  mkdir_p(os.path.dirname(destination))
  f = open(destination, 'w')
  f.write(content)
  f.close()

# de-dupe a list, taken from:
# http://stackoverflow.com/questions/480214/how-do-you-remove-duplicates-from-a-list-in-python-whilst-preserving-order
def uniq(seq):
    seen = set()
    seen_add = seen.add
    return [ x for x in seq if x not in seen and not seen_add(x)]

import os, errno

# mkdir -p in python, from:
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

  def remove_unicode_control(str):
    remove_re = re.compile(u'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]')
    return remove_re.sub('', str)

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

  text = re.sub("&#?\w+;", fixup, text)
  text = remove_unicode_control(text)
  return text

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

# uses config values if present
def cache_dir():
  cache = None

  if config:
    output = config.get('output', None)
    if output:
      cache = output.get('cache', None)

  if not cache:
    cache = "cache"

  return cache

def test_cache_dir():
  return "test/fixtures/cache"

# uses config values if present
def data_dir():
  data = None

  if config:
    output = config.get('output', None)
    if output:
      data = output.get('data', None)

  if not data:
    data = "data"

  return data

# if email settings are supplied, email the text - otherwise, just print it
def admin(body):
  try:
    if isinstance(body, Exception):
      body = format_exception(body)

    logging.error(body) # always print it

    if config:
      details = config.get('email', None)
      if details:
        send_email(body)
    
  except Exception as exception:
    print "Exception logging message to admin, halting as to avoid loop"
    print format_exception(exception)

def format_exception(exception):
  exc_type, exc_value, exc_traceback = sys.exc_info()
  return "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

# this should only be called if the settings are definitely there
def send_email(message):
  settings = config['email']

  # adapted from http://www.doughellmann.com/PyMOTW/smtplib/
  msg = MIMEText(message)
  msg.set_unixfrom('author')
  msg['To'] = email.utils.formataddr(('Recipient', settings['to']))
  msg['From'] = email.utils.formataddr((settings['from_name'], settings['from']))
  msg['Subject'] = "%s - %i" % (settings['subject'], int(time.time()))

  server = smtplib.SMTP(settings['hostname'])
  try:
    server.ehlo()
    if settings['starttls'] and server.has_extn('STARTTLS'):
      server.starttls()
      server.ehlo()

    server.login(settings['user_name'], settings['password'])
    server.sendmail(settings['from'], [settings['to']], msg.as_string())
  finally:
    server.quit()

  logging.info("Sent email to %s" % settings['to'])


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


# cached committee map to map names to IDs
committee_names = {}

# get the mapping from THOMAS's committee names to THOMAS's committee IDs
# found on the advanced search page. committee_names[congress][name] = ID
# with subcommittee names as the committee name plus a pipe plus the subcommittee
# name.
def fetch_committee_names(congress, options):
  congress = int(congress)
  
  # Parse the THOMAS advanced search pages for the names that THOMAS uses for
  # committees on bill pages, and map those to the IDs for the committees that are
  # listed on the advanced search pages (but aren't shown on bill pages).
  if not options.get('test', False): logging.info("[%d] Fetching committee names..." % congress)
  
  # allow body to be passed in from fixtures
  if options.has_key('body'):
    body = options['body']
  else:
    body = download(
      "http://thomas.loc.gov/home/LegislativeData.php?&n=BSS&c=%d" % congress, 
      "%s/meta/thomas_committee_names.html" % congress,
      options.get('force', False), options)

  for chamber, options in re.findall('>Choose (House|Senate) Committees</option>(.*?)</select>', body, re.I | re.S):
    for name, id in re.findall(r'<option value="(.*?)\{(.*?)}">', options, re.I | re.S):
      id = str(id).upper()
      name = name.strip().replace("  ", " ") # weirdness
      if id.endswith("00"):
        # Map chamber + committee name to its ID, minus the 00 at the end. On bill pages,
        # committees appear as e.g. "House Finance." Except the JCSE.
        if id != "JCSE00":
          name = chamber + " " + name
        
        # Correct for some oddness on THOMAS (but not on Congress.gov): The House Committee
        # on House Administration appears just as "House Administration".
        if name == "House House Administration": name = "House Administration"

        committee_names[name] = id[0:-2]
        
      else:
        # map committee ID + "|" + subcommittee name to the zero-padded subcommittee numeric ID
        committee_names[id[0:-2] + "|" + name] = id[-2:]
        
  # Correct for a limited number of other ways committees appear, owing probably to the
  # committee name being changed mid-way through a Congress.
  if congress == 95:
    committee_names["House Intelligence (Select)"] = committee_names["House Intelligence (Permanent Select)"]
  if congress == 96:
    committee_names["Senate Human Resources"] = "SSHR"
  if congress == 97:
    committee_names["Senate Small Business (Select)"] = committee_names["Senate Small Business"]
  if congress == 98:
    committee_names["Senate Indian Affairs (Select)"] = committee_names["Senate Indian Affairs (Permanent Select)"]
  if congress == 100:
    committee_names["HSPO|Hoc Task Force on Presidential Pay Recommendation"] = committee_names["HSPO|Ad Hoc Task Force on Presidential Pay Recommendation"]
  if congress == 103:
    committee_names["Senate Indian Affairs (Permanent Select)"] = committee_names["Senate Indian Affairs"]
  if congress == 108:
    # This appears to be a mistake, a subcommittee appearing as a full committee. Map it to
    # the full committee for now.
    committee_names["House Antitrust (Full Committee Task Force)"] = committee_names["House Judiciary"]
