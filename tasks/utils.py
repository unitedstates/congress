import os, os.path, errno, sys, traceback, zipfile
import re, htmlentitydefs
import yaml, json
from pytz import timezone
import datetime, time
from lxml import html, etree
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


eastern_time_zone = timezone('US/Eastern')

# scraper should be instantiated at class-load time, so that it can rate limit appropriately
scraper = scrapelib.Scraper(requests_per_minute=120, follow_robots=False, retry_attempts=3)
scraper.user_agent = "unitedstates/congress (https://github.com/unitedstates/congress)"

govtrack_person_id_map = None

class UnmatchedIdentifer(Exception):
  def __init__(self, id_type, id_value, help_url):
    super(UnmatchedIdentifer, self).__init__("%s=%s %s" % (id_type, str(id_value), help_url))

def format_datetime(obj):
  if isinstance(obj, datetime.datetime):
    return eastern_time_zone.localize(obj.replace(microsecond=0)).isoformat()
  elif isinstance(obj, (str, unicode)):
    return obj
  else:
    return None

def current_congress():
  year = current_legislative_year()
  return congress_from_legislative_year(year)

def congress_from_legislative_year(year):
  return ((year + 1) / 2) - 894

def current_legislative_year(date=None):
  if not date:
    date = datetime.datetime.now()

  year = date.year

  if date.month == 1:
    if date.day == 1 or date.day == 2:
      return date.year - 1
    elif date.day == 3 and date.hour < 12:
      return date.year - 1
    else:
      return date.year
  else:
    return date.year

def get_congress_first_year(congress):
  return (((int(congress)+894)*2) - 1)

# get the three calendar years that the Congress extends through (Jan 3 to Jan 3).
def get_congress_years(congress):
  y1 = get_congress_first_year(congress)
  return (y1, y1+1, y1+2)

# bill_type, bill_number, congress
def split_bill_id(bill_id):
  return re.match("^([a-z]+)(\d+)-(\d+)$", bill_id).groups()

# bill_type, bill_number, congress, version_code
def split_bill_version_id(bill_version_id):
  return re.match("^([a-z]+)(\d+)-(\d+)-([a-z\d]+)$", bill_version_id).groups()

def split_vote_id(bill_id):
  return re.match("^(h|s)(\d+)-(\d+).(\d\d\d\d)$", bill_id).groups()

# nomination_type, congress, nomination_number
# I think it's always PN, but might as well include
def split_nomination_id(nomination_id):
  try:
    return re.match("^([A-z]{2})(\d+)-(\d+)$", nomination_id).groups()
  except Exception, e:
    logging.error("Unabled to parse %s" % nomination_id)
    return (None, None, None)

def process_set(to_fetch, fetch_func, options, *extra_args):
  errors = []
  saved = []
  skips = []

  for id in to_fetch:
    try:
      results = fetch_func(id, options, *extra_args)
    except Exception, e:
      if options.get('raise', False):
        raise
      else:
        errors.append((id, e, format_exception(e)))
        continue

    if results.get('ok', False):
      if results.get('saved', False):
        saved.append(id)
        logging.info("[%s] Updated" % id)
      else:
        skips.append(id)
        logging.warn("[%s] Skipping: %s" % (id, results['reason']))
    else:
      errors.append((id, results, None))
      logging.error("[%s] Error: %s" % (id, results['reason']))

  if len(errors) > 0:
    message = "\nErrors for %s items:\n" % len(errors)
    for id, error, msg in errors:
      message += "\n\n"
      if isinstance(error, Exception):
        message += "[%s] Exception:\n\n" % id
        message += msg
      else:
        message += "[%s] %s" % (id, error)

    admin(message) # email if possible

  logging.warning("\nErrors for %s." % len(errors))
  logging.warning("Skipped %s." % len(skips))
  logging.warning("Saved data for %s." % len(saved))

  return saved + skips # all of the OK's


# Download file at `url`, cache to `destination`.
# Takes many options to customize behavior.
_download_zip_files = { }
def download(url, destination=None, options={}):
  # uses cache by default, override (True) to ignore
  force = options.get('force', False)

  # saves in cache dir by default, override (False) to save to exact destination
  to_cache = options.get('to_cache', True)

  # unescapes HTML encoded characters by default, set this (True) to not do that
  is_binary = options.get('binary', False)

  # used by test suite to use special (versioned) test cache dir
  test = options.get('test', False)

  # if need a POST request with data
  postdata = options.get('postdata', False)

  # caller cares about actually bytes or only success/fail
  needs_content = options.get('needs_content', True) or not is_binary or postdata

  # form the path to the file if we intend on saving it to disk
  if destination:
    if to_cache:
      if test:
        cache = test_cache_dir()
      else:
        cache = cache_dir()
      cache_path = os.path.join(cache, destination)

    else:
      cache_path = destination

  # If we are working in the cache directory, look for a zip file
  # anywhere along the path like "cache/93/bills.zip", and see if
  # the file is already cached inside it (e.g. as 'bills/pages/...").
  # If it is, and force is true, then raise an Exception because we
  # can't update the ZIP file with new content (I imagine it would
  # be very slow). If force is false, return the content from the
  # archive.
  if destination and to_cache:
    dparts = destination.split(os.sep)
    for i in xrange(len(dparts)-1):
      # form the ZIP file name and test if it exists...
      zfn = os.path.join(cache, *dparts[:i+1]) + ".zip"
      if not os.path.exists(zfn): continue

      # load and keep the ZIP file instance in memory because it's slow to instantiate this object
      zf = _download_zip_files.get(zfn)
      if not zf:
        zf = zipfile.ZipFile(zfn, "r")
        _download_zip_files[zfn] = zf
        logging.warn("Loaded: %s" % zfn)

      # see if the inner file exists, and if so read the bytes
      try:
        zfn_inner = os.path.join(*dparts[i:])
        body = zf.read(zfn_inner)
      except KeyError:
        # does not exist
        continue

      if not test: logging.info("Cached: (%s, %s)" % (zfn + "#" + zfn_inner, url))
      if force: raise Exception("Cannot re-download a file already cached to a ZIP file.")

      if not is_binary:
        body = body.decode("utf8")
        body = unescape(body)

      return body

  # Load the file from disk if it's already been downloaded and force is False.
  if destination and (not force) and os.path.exists(cache_path):
    if not test: logging.info("Cached: (%s, %s)" % (cache_path, url))
    if not needs_content: return True
    with open(cache_path, 'r') as f:
      body = f.read()
    if not is_binary:
      body = body.decode("utf8")

  # Download from the network and cache to disk.
  else:
    try:
      logging.info("Downloading: %s" % url)

      if postdata:
        response = scraper.urlopen(url, 'POST', postdata)
      else:
        if not needs_content:
          import subprocess
          mkdir_p(os.path.dirname(cache_path))
          return True if (subprocess.call(["wget", "-q", "-O", cache_path, url]) == 0) else None
        response = scraper.urlopen(url)

      if not is_binary:
        body = response # a subclass of a 'unicode' instance
        if not isinstance(body, unicode): raise ValueError("Content not decoded.")
      else:
        body = response.bytes # a 'str' instance
        if isinstance(body, unicode): raise ValueError("Binary content improperly decoded.")
    except scrapelib.HTTPError as e:
      logging.error("Error downloading %s:\n\n%s" % (url, format_exception(e)))
      return None

    # don't allow 0-byte files
    if (not body) or (not body.strip()):
      return None

    # cache content to disk
    if destination:
      write(body if is_binary else body.encode("utf8"), cache_path)

  if not is_binary:
    body = unescape(body)

  return body

def write(content, destination):
  mkdir_p(os.path.dirname(destination))
  f = open(destination, 'w')
  f.write(content)
  f.close()

def read(destination):
  if os.path.exists(destination):
    with open(destination) as f:
      return f.read()

# dict1 gets overwritten with anything in dict2
def merge(dict1, dict2):
  return dict(dict1.items() + dict2.items())

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
  msg['Subject'] = settings['subject']

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
  'hamdt': ('HZ', 'H.AMDT.'),
  'samdt': ('SP', 'S.AMDT.'),
  'supamdt': ('SU', 'S.UP.AMDT.'),
}
thomas_types_2 = dict( (v[0], k) for (k, v) in thomas_types.items() )  # map e.g. { SE: sres, ...}

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
      options)

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
  if congress == 104:
    committee_names["House Oversight"] = committee_names["House House Oversight"]
  if congress == 108:
    # This appears to be a mistake, a subcommittee appearing as a full committee. Map it to
    # the full committee for now.
    committee_names["House Antitrust (Full Committee Task Force)"] = committee_names["House Judiciary"]

def make_node(parent, tag, text, **attrs):
  """Make a node in an XML document."""
  n = etree.Element(tag)
  parent.append(n)
  n.text = text
  for k, v in attrs.items():
    if v is None: continue
    if isinstance(v, datetime.datetime):
      v = format_datetime(v)
    n.set(k.replace("___", ""), v)
  return n

# Correct mistakes on THOMAS
def thomas_corrections(thomas_id):

  # C.A. Dutch Ruppersberger
  if thomas_id == "02188": thomas_id = "01728"

  # Pat Toomey
  if thomas_id == "01594": thomas_id = "02085"

  return thomas_id

def yaml_load(file_name):
  import yaml
  try:
    from yaml import CLoader as Loader, CDumper as Dumper
  except ImportError:
    from yaml import Loader, Dumper
  return yaml.load(open(file_name), Loader=Loader)

def require_congress_legislators_repo():
  # Clone the congress-legislators repo if we don't have it.
  if not os.path.exists("cache/congress-legislators"):
    logging.warn("Cloning the congress-legislators repo into the cache directory...")
    os.system("git clone -q --depth 1 https://github.com/unitedstates/congress-legislators cache/congress-legislators")

  # Update the repo so we have the latest.
  logging.warn("Updating the congress-legislators repo...")
  os.system("cd cache/congress-legislators; git fetch -pq") # these two == git pull, but git pull ignores -q on the merge part so is less quiet
  os.system("cd cache/congress-legislators; git merge --ff-only -q origin/master")

lookup_legislator_cache = []
def lookup_legislator(congress, role_type, name, state, party, when, id_requested, exclude=set()):
  # This is a basic lookup function given the legislator's name, state, party,
  # and the date of the vote.

  # On the first load, cache all of the legislators' terms in memory.
  # Group by Congress so we can limit our search later to be faster.
  global lookup_legislator_cache
  if not lookup_legislator_cache:
    require_congress_legislators_repo()
    lookup_legislator_cache = { } # from Congress number to list of (moc,term) tuples that might be in that Congress
    for fn in ('legislators-historical', 'legislators-current'):
      for moc in yaml_load("cache/congress-legislators/" + fn + ".yaml"):
        for term in moc["terms"]:
          for c in xrange(congress_from_legislative_year(int(term['start'][0:4]))-1,
            congress_from_legislative_year(int(term['end'][0:4]))+1+1):
            lookup_legislator_cache.setdefault(c, []).append( (moc, term) )

  def to_ascii(name):
    name = name.replace("-", " ")
    if not isinstance(name, unicode): return name
    import unicodedata
    return u"".join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))

  # Scan all of the terms that cover 'when' for a match.
  if isinstance(when, datetime.datetime): when = when.date()
  when = when.isoformat()
  name_parts = to_ascii(name).split(", ", 1)
  matches = []
  for moc, term in lookup_legislator_cache[congress]:
    # Make sure the date is surrounded by the term start/end dates.
    if term['start'] > when: continue # comparing ISO-formatted date strings
    if term['end'] < when: continue # comparing ISO-formatted date strings

    # Compare the role type, state, and party, except for people who we know changed party.
    if term['type'] != role_type: continue
    if term['state'] != state: continue
    if term['party'][0] != party and name not in ("Laughlin", "Crenshaw", "Goode", "Martinez"): continue

    # When doing process-of-elimination matching, don't match on people we've already seen.
    if moc["id"].get(id_requested) in exclude: continue

    # Compare the last name. Allow "Chenoweth" to match "Chenoweth Hage", but also
    # allow "Millender McDonald" to match itself.
    if name_parts[0] != to_ascii(moc['name']['last']) and \
      name_parts[0] not in to_ascii(moc['name']['last']).split(" "): continue

    # Compare the first name. Allow it to match either the first or middle name,
    # and an initialized version of the first name (i.e. "E." matches "Eddie").
    # Test the whole string (so that "Jo Ann" is compared to "Jo Ann") but also
    # the first part of a string split (so "E. B." is compared as "E." to "Eddie").
    first_names = (to_ascii(moc['name']['first']), to_ascii(moc['name'].get('nickname', "")), to_ascii(moc['name']['first'])[0] + ".")
    if len(name_parts) >= 2 and \
      name_parts[1] not in first_names and \
      name_parts[1].split(" ")[0] not in first_names: continue

    # This is a possible match.
    matches.append((moc, term))

  # Return if there is a unique match.
  if len(matches) == 0:
    logging.warn("Could not match name %s (%s-%s; %s) to any legislator." % (name, state, party, when))
    return None
  if len(matches) > 1:
    logging.warn("Multiple matches of name %s (%s-%s; %s) to legislators (excludes %s)." % (name, state, party, when, str(exclude)))
    return None
  return matches[0][0]['id'][id_requested]

def get_govtrack_person_id(source_id_type, source_id):
  # Load the legislators database to map various IDs to GovTrack IDs.
  # Cache in a pickled file because loading the whole YAML db is super slow.
  global govtrack_person_id_map
  import os, os.path, pickle

  # On the first call to this function...
  if not govtrack_person_id_map:
    require_congress_legislators_repo()

    govtrack_person_id_map = { }
    for fn in ('legislators-historical', 'legislators-current'):
      # Check if the pickled file is older than the YAML files.
      cachefn = os.path.join(cache_dir(), fn + '-id-map')
      if os.path.exists(cachefn) and os.stat(cachefn).st_mtime > os.stat("cache/congress-legislators/%s.yaml" % fn).st_mtime:
        # Pickled file is newer, so use it.
        m = pickle.load(open(cachefn))
      else:
        # Make a new mapping. Load the YAML file and create
        # a master map from (id-type, id) to GovTrack ID,
        # where id-type is e.g. thomas, lis, bioguide. Then
        # save it to a pickled file.
        logging.warn("Making %s ID map..." % fn)
        m = { }
        for moc in yaml_load("cache/congress-legislators/" + fn + ".yaml"):
          if "govtrack" in moc["id"]:
            for k, v in moc["id"].items():
              if k in ('bioguide', 'lis', 'thomas'):
                m[(k,v)] = moc["id"]["govtrack"]
        pickle.dump(m, open(cachefn, "w"))

      # Combine the mappings from the historical and current files.
      govtrack_person_id_map.update(m)

  # Now do the lookup.
  if (source_id_type, source_id) not in govtrack_person_id_map:
      see_also = ""
      if source_id_type == "thomas":
        see_also = "http://beta.congress.gov/member/xxx/" + source_id
      logging.error("GovTrack ID not known for %s %s. (%s)" % (source_id_type, str(source_id), see_also))
      raise UnmatchedIdentifer(source_id_type, source_id, see_also)
  return govtrack_person_id_map[(source_id_type, source_id)]

