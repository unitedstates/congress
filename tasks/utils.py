import os, os.path, errno, sys, traceback, zipfile
import platform
import re, html.entities
import json
from pytz import timezone
import datetime, time
from lxml import html, etree
import scrapelib
import pprint
import logging
import subprocess

import smtplib
import email.utils
from email.mime.text import MIMEText
import getpass


# read in an opt-in config file for changing directories and supplying email settings
# returns None if it's not there, and this should always be handled gracefully
path = "config.yml"
if os.path.exists(path):
  # Don't use a cached config file, just in case, and direct_yaml_load is not yet defined.
  import yaml
  config = yaml.load(open(path))
else:
  config = None


eastern_time_zone = timezone('US/Eastern')

# scraper should be instantiated at class-load time, so that it can rate limit appropriately
scraper = scrapelib.Scraper(requests_per_minute=120, follow_robots=False, retry_attempts=3)
scraper.user_agent = "unitedstates/congress (https://github.com/unitedstates/congress)"

def format_datetime(obj):
  if isinstance(obj, datetime.datetime):
    return eastern_time_zone.localize(obj.replace(microsecond=0)).isoformat()
  elif isinstance(obj, datetime.date):
    return obj.isoformat()
  elif isinstance(obj, str):
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

# Get a list of Congresses associated with a particular term.
# XXX: This can be highly unreliable and may be deeply flawed.
# XXX: This would be much simpler if we already included Congresses in the data.
def get_term_congresses(term):
  start_year = int(format_datetime(term["start"])[:4])
  end_year = int(format_datetime(term["end"])[:4])

  start_congress = congress_from_legislative_year(start_year)
  start_congress_years = get_congress_years(start_congress)
  start_congress_first_year = start_congress_years[0]

  if term["type"] in [ "sen" ]:
    end_congress_years = get_congress_years(start_congress + 2)
    congresses = [ start_congress, start_congress + 1, start_congress + 2 ]
  elif term["type"] in [ "prez", "viceprez" ] or term["state"] in [ "PR" ]:
    end_congress_years = get_congress_years(start_congress + 1)
    congresses = [ start_congress, start_congress + 1 ]
  else:
    end_congress_years = start_congress_years
    congresses = [ start_congress ]

  end_congress_last_year = end_congress_years[2]

  valid_congresses = (start_year >= start_congress_first_year) and (end_year <= end_congress_last_year)

#  if not valid_congresses:
#    print term["type"], start_congress, (start_year, start_congress_first_year), (end_year, end_congress_last_year)

  return congresses if valid_congresses else []

# bill_type, bill_number, congress
def split_bill_id(bill_id):
  return re.match("^([a-z]+)(\d+)-(\d+)$", bill_id).groups()

# "hjres1234-115"
def build_bill_id(bill_type, bill_number, congress):
  return "%s%s-%s" % ( bill_type, bill_number, congress )

# bill_type, bill_number, congress, version_code
def split_bill_version_id(bill_version_id):
  return re.match("^([a-z]+)(\d+)-(\d+)-([a-z\d]+)$", bill_version_id).groups()

# "hjres1234-115-enr"
def build_bill_version_id(bill_type, bill_number, congress, version_code):
  return "%s%s-%s-%s" % ( bill_type, bill_number, congress, version_code )

def split_vote_id(vote_id):
  # Sessions are either four-digit years for modern day votes or a digit or letter
  # for historical votes before sessions were basically calendar years.
  return re.match("^(h|s)(\d+)-(\d+).(\d\d\d\d|[0-9A-Z])$", vote_id).groups()

# nomination_type (always PN), nomination_number, congress
#   nomination_number is usually a number, but can be hyphenated, e.g. PN64-01-111
#   which would produce a nomination_number of "64-01"
def split_nomination_id(nomination_id):
  try:
    return re.match("^([A-z]{2})([\d-]+)-(\d+)$", nomination_id).groups()
  except Exception as e:
    logging.error("Unabled to parse %s" % nomination_id)
    return (None, None, None)

def process_set(to_fetch, fetch_func, options, *extra_args):
  errors = []
  saved = []
  skips = []

  for id in to_fetch:
    try:
      results = fetch_func(id, options, *extra_args)
    except Exception as e:
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

  timeout = float(options.get('timeout', 30)) # The low level socket api requires a float
  urlopen_kwargs = {'timeout': timeout}

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
    for i in range(len(dparts)-1):
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
        response = scraper.urlopen(url, 'POST', postdata, **urlopen_kwargs)
      else:

        # If we're just downloading the file and the caller doesn't
        # need the response data, then starting wget to download the
        # file is much faster for large files. Don't know why. Something
        # hopefully we can improve in scrapelib in the future.
        #
        # needs_content is currently only set to false when downloading
        # bill text files like PDFs.
        #
        # Skip this fast path if wget is not present in its expected location.
        with open(os.devnull, 'w') as tempf:
          if platform.system() == 'Windows':
            wget_exists = (subprocess.call("where wget", stdout=tempf, stderr=tempf, shell=True) == 0)
          else:
            wget_exists = (subprocess.call("which wget", stdout=tempf, stderr=tempf, shell=True) == 0)

        if not needs_content and wget_exists:

          mkdir_p(os.path.dirname(cache_path))
          if subprocess.call(["wget", "-q", "-O", cache_path, url]) == 0:
            return True
          else:
            # wget failed. when that happens it leaves a zero-byte file on disk, which
            # for us means we've created an invalid file, so delete it.
            os.unlink(cache_path)
            return None

        response = scraper.urlopen(url, **urlopen_kwargs)

      if not is_binary:
        body = response # a subclass of a 'unicode' instance
        if not isinstance(body, str): raise ValueError("Content not decoded.")
      else:
        body = response.bytes # a 'str' instance
        if isinstance(body, str): raise ValueError("Binary content improperly decoded.")
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
  return dict(list(dict1.items()) + list(dict2.items()))

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
    remove_re = re.compile('[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]')
    return remove_re.sub('', str)

  def fixup(m):
    text = m.group(0)
    if text[:2] == "&#":
      # character reference
      try:
        if text[:3] == "&#x":
          return chr(int(text[3:-1], 16))
        else:
          return chr(int(text[2:-1]))
      except ValueError:
        pass
    else:
      # named entity
      try:
        text = chr(html.entities.name2codepoint[text[1:-1]])
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
    print("Exception logging message to admin, halting as to avoid loop")
    print(format_exception(exception))

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
thomas_types_2 = dict( (v[0], k) for (k, v) in list(thomas_types.items()) )  # map e.g. { SE: sres, ...}

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
  if 'body' in options:
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
        # on House Administration appears just as "House Administration" and in the 104th/105th
        # Congresses appears as "House Oversight" (likewise the full name is House Committee
        # on House Oversight --- it's the House Administration committee still).
        if name == "House House Administration": name = "House Administration"
        if name == "House House Oversight": name = "House Oversight"

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
    committee_names["House Homeland Security"] = committee_names["House Homeland Security (Select)"]
  if congress in range(108,113):
    committee_names["House Intelligence"] = committee_names["House Intelligence (Permanent Select)"]

def make_node(parent, tag, text, **attrs):
  """Make a node in an XML document."""
  n = etree.Element(tag)
  parent.append(n)
  n.text = text
  for k, v in list(attrs.items()):
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

# Return a subset of a mapping type
def slice_map(m, *args):
    n = {}
    for arg in args:
        if arg in m:
            n[arg] = m[arg]
    return n

# Load a YAML file directly.
def direct_yaml_load(filename):
  import yaml
  try:
    from yaml import CLoader as Loader, CDumper as Dumper
  except ImportError:
    from yaml import Loader, Dumper
  return yaml.load(open(filename), Loader=Loader)

# Load a pickle file.
def pickle_load(filename):
  import pickle
  return pickle.load(open(filename))

# Write to a pickle file.
def pickle_write(data, filename):
  import pickle
  return pickle.dump(data, open(filename, "w"))

# Get the hash used to verify the contents of a file.
def get_file_hash(filename):
  import hashlib
  return hashlib.sha1(open(filename).read()).hexdigest()

# Get the location of the cached version of a file.
def get_cache_filename(filename):
  return os.path.join(cache_dir(), filename + '.pickle')

# Check if the cached file is newer.
def check_cached_file(filename, cache_filename):
  return (os.path.exists(cache_filename) and os.stat(cache_filename).st_mtime > os.stat(filename).st_mtime)

# Problem with finding a cache entry.
class CacheError(LookupError):
  pass

# Load a cached file.
def cache_load(cache_filename, file_hash):
  try:
    cache_data = pickle_load(cache_filename)
  except IOError:
    raise CacheError("Could not retrieve potential cache file: %s" % ( cache_filename ))

  # A cache file has a specific structure.
  if "hash" not in cache_data or "data" not in cache_data:
    raise TypeError("Not a cache file: %s" % ( cache_filename ))

  # If the hashes don't match, we've retrieved the cache for something else.
  if cache_data["hash"] != file_hash:
    raise CacheError("Hashes do not match: %s, %s" % ( file_hash, cache_data["hash"] ))

  return cache_data["data"]

# Cache a file.
def cache_write(file_data, filename, file_hash):
  cache_data = { "hash": file_hash, "data": file_data }
  return pickle_write(cache_data, filename)

# Attempt to load a cached version of a YAML file before loading the YAML file directly.
def yaml_load(filename):
  file_hash = get_file_hash(filename)
  cache_filename = get_cache_filename(filename)

  # Try to load a cached version of the requested YAML file.
  try:
    yaml_data = cache_load(cache_filename, file_hash)
  except CacheError:
    # We don't have a cached version of the requested YAML file available, so we have to load it directly.
    logging.warn("Using original YAML file...")

    # Load the requested YAML file directly.
    yaml_data = direct_yaml_load(filename)

    # Cache the YAML data so we can retrieve it more quickly next time.
    cache_write(yaml_data, cache_filename, file_hash)
  else:
    # We have a cached version of the requested YAML file available, so we can use it.
    logging.info("Using cached YAML file...")

  return yaml_data

# Make sure we have the congress-legislators repository available.
has_congress_legislators_repo = False
def require_congress_legislators_repo():
  global has_congress_legislators_repo

  # Once we have the congress-legislators repo, we don't need to keep getting it.
  if has_congress_legislators_repo:
    return

  # Clone the congress-legislators repo if we don't have it.
  if not os.path.exists("congress-legislators"):
    logging.warn("Cloning the congress-legislators repo...")
    os.system("git clone -q --depth 1 https://github.com/unitedstates/congress-legislators congress-legislators")

  if os.environ.get("UPDATE_CONGRESS_LEGISLATORS") != "NO":
    # Update the repo so we have the latest.
    logging.warn("Updating the congress-legislators repo...")
    # these two == git pull, but git pull ignores -q on the merge part so is less quiet
    os.system("cd congress-legislators; git fetch -pq; git merge --ff-only -q origin/master")

  # We now have the congress-legislators repo.
  has_congress_legislators_repo = True

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
    for filename in ("legislators-historical", "legislators-current"):
      for moc in yaml_load("congress-legislators/%s.yaml" % ( filename )):
        for term in moc["terms"]:
          for c in range(congress_from_legislative_year(int(term['start'][0:4]))-1,
            congress_from_legislative_year(int(term['end'][0:4]))+1+1):
            lookup_legislator_cache.setdefault(c, []).append( (moc, term) )

  def to_ascii(name):
    name = name.replace("-", " ")
    if not isinstance(name, str): return name
    import unicodedata
    return "".join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))

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
    if term['party'][0] != party and name not in ("Laughlin", "Crenshaw", "Goode", "Martinez", "Parker", "Emerson", "Tauzin", "Hayes", "Deal", "Forbes"): continue

    # When doing process-of-elimination matching, don't match on people we've already seen.
    if moc["id"].get(id_requested) in exclude: continue

    # Compare the last name. Allow "Chenoweth" to match "Chenoweth Hage", but also
    # allow "Millender McDonald" to match itself.
    for name_info_rec in [moc['name']] + moc.get('other_names', []):
      # for other_names, check that the record covers the right date range
      if 'start' in name_info_rec and name_info_rec['start'] > when: continue # comparing ISO-formatted date strings
      if 'end' in name_info_rec and name_info_rec['end'] < when: continue # comparing ISO-formatted date strings

      # in order to process an other_name we have to go like this...
      name_info = dict(moc['name']) # clone
      name_info.update(name_info_rec) # override with the other_name information

      # check last name
      if name_parts[0] != to_ascii(name_info['last']) \
        and name_parts[0] not in to_ascii(name_info['last']).split(" "): continue # no match

      # Compare the first name. Allow it to match either the first or middle name,
      # and an initialized version of the first name (i.e. "E." matches "Eddie").
      # Test the whole string (so that "Jo Ann" is compared to "Jo Ann") but also
      # the first part of a string split (so "E. B." is compared as "E." to "Eddie").
      first_names = (to_ascii(name_info['first']), to_ascii(name_info.get('nickname', "")), to_ascii(name_info['first'])[0] + ".")
      if len(name_parts) >= 2 and \
        name_parts[1] not in first_names and \
        name_parts[1].split(" ")[0] not in first_names: continue

      break # match
    else:
      # no match
      continue

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

# Create a map from one piece of legislators data to another.
# 'map_from' and 'map_to' are plain text terms used for the logging output and the filenames.
# 'map_function' is the function that actually does the mapping from one value to another.
# 'filename' is the source of the data to be mapped. (Default: "legislators-current")
# 'legislators_map' is the base object to build the map on top of; it's primarily used to combine maps using create_combined_legislators_map(). (Default: {})
def create_legislators_map(map_from, map_to, map_function, filename="legislators-current", legislators_map={}):
  # Make sure we have the congress-legislators repo available.
  require_congress_legislators_repo()

  cache_filename = get_cache_filename("map-%s-%s-%s" % ( map_from.lower().replace(" ", "_"), map_to.lower().replace(" ", "_"), filename ))

  # Check if the cached pickle file is newer than the original YAML file.
  if check_cached_file("congress-legislators/%s.yaml" % ( filename ), cache_filename):
    # The pickle file is newer, so it's probably safe to use the cached map.
    logging.info("Using cached map from %s to %s for %s..." % ( map_from, map_to, filename ))
    legislators_map = pickle_load(cache_filename)
  else:
    # The YAML file is newer, so we have to generate a new map.
    logging.warn("Generating new map from %s to %s for %s..." % ( map_from, map_to, filename ))

    # Load the YAML file and create a map based on the provided map function.
    # Because we'll be caching the YAML file in a pickled file, create the cache
    # directory where that will be stored.
    if not os.path.exists("cache/congress-legislators"): os.mkdir("cache/congress-legislators")
    for item in yaml_load("congress-legislators/%s.yaml" % ( filename )):
      legislators_map = map_function(legislators_map, item)

    # Save the new map to a new pickle file.
    pickle_write(legislators_map, cache_filename)

  return legislators_map

# Create a legislators map combining data from multiple legislators files.
# 'map_from', 'map_to', 'map_function' are passed directly to create_legislators_map().
# 'filenames' is the list of the sources of the data to be mapped. (Default: [ "executive", "legislators-historical", "legislators-current" ])
def create_combined_legislators_map(map_from, map_to, map_function, filenames=[ "executive", "legislators-historical", "legislators-current" ]):
  combined_legislators_map = {}

  for filename in filenames:
    combined_legislators_map = create_legislators_map(map_from, map_to, map_function, filename, combined_legislators_map)

  return combined_legislators_map

# Generate a map between a person's many IDs.
person_id_map = {}
def generate_person_id_map():
  def map_function(person_id_map, person):
    for source_id_type, source_id in list(person["id"].items()):
      # Instantiate this ID type.
      if source_id_type not in person_id_map:
        person_id_map[source_id_type] = {}

      # Certain ID types have multiple IDs.
      source_ids = source_id if isinstance(source_id, list) else [source_id]

      for source_id in source_ids:
        # Instantiate this value for this ID type.
        if source_id not in person_id_map[source_id_type]:
          person_id_map[source_id_type][source_id] = {}

        # Loop through all the ID types and values and map them to this ID type.
        for target_id_type, target_id in list(person["id"].items()):
          # Don't map an ID type to itself.
          if target_id_type != source_id_type:
            person_id_map[source_id_type][source_id][target_id_type] = target_id

    return person_id_map

  # Make the person ID map available in the global space.
  global person_id_map

  person_id_map = create_combined_legislators_map("person", "ID", map_function)

# Return the map generated by generate_person_id_map().
def get_person_id_map():
  global person_id_map

  # If the person ID map is not available yet, generate it.
  if not person_id_map:
    generate_person_id_map()

  return person_id_map

# Get a particular ID for a person from another ID.
# 'source_id_type' is the ID type provided to identify the person.
# 'source_id' is the provided ID of the aforementioned type.
# 'target_id_type' is the desired ID type for the aforementioned person.
def get_person_id(source_id_type, source_id, target_id_type):
  person_id_map = get_person_id_map()
  if source_id_type not in person_id_map: raise KeyError("'%s' is not a valid ID type." % ( source_id_type ))
  if source_id not in person_id_map[source_id_type]: raise KeyError("'%s' is not a valid '%s' ID." % ( source_id, source_id_type ))
  if target_id_type not in person_id_map[source_id_type][source_id]: raise KeyError("No corresponding '%s' ID for '%s' ID '%s'." % ( target_id_type, source_id_type, source_id ))
  return person_id_map[source_id_type][source_id][target_id_type]



# Generate a map from a person to the Congresses they served during.
person_congresses_map = {}
def generate_person_congresses_map():
  def map_function(person_congresses_map, person):
    try:
      bioguide_id = person["id"]["bioguide"]
    except KeyError:
#      print person["id"], person["name"]
      return person_congresses_map

    if bioguide_id not in person_congresses_map:
      person_congresses_map[bioguide_id] = []

    for term in person["terms"]:
      for congress in get_term_congresses(term):
        person_congresses_map[bioguide_id].append(congress)

    person_congresses_map[bioguide_id].sort()

    return person_congresses_map

  # Make the person congresses map available in the global space.
  global person_congresses_map

  person_congresses_map = create_combined_legislators_map("person", "Congresses", map_function)

# Return the map generated by generate_person_congresses_map().
def get_person_congresses_map():
  global person_congresses_map

  # If the person Congresses map is not available yet, generate it.
  if not person_congresses_map:
    generate_person_congresses_map()

  return person_congresses_map

# Get a list of Congresses that a person served during.
# 'person_id' is the ID of the desired person.
# 'person_id_type' is the ID type provided. (Default: "bioguide")
def get_person_congresses(person_id, person_id_type="bioguide"):
  bioguide_id = person_id if person_id_type == "bioguide" else get_person_id(person_id_type, person_id, "bioguide")

  person_congresses_map = get_person_congresses_map()

  if bioguide_id not in person_congresses_map:
    raise KeyError("No known Congresses for BioGuide ID '%s'." % ( bioguide_id ))

  return person_congresses_map[bioguide_id]

# Generate a map from a Congress to the persons who served during it.
congress_persons_map = {}
def generate_congress_persons_map():
  def map_function(congress_persons_map, person):
    try:
      bioguide_id = person["id"]["bioguide"]
    except KeyError:
#      print person["id"], person["name"]
      return congress_persons_map

    for term in person["terms"]:
      for congress in get_term_congresses(term):
        if congress not in congress_persons_map:
          congress_persons_map[congress] = set()

        congress_persons_map[congress].add(bioguide_id)

    return congress_persons_map

  # Make the person congresses map available in the global space.
  global congress_persons_map

  congress_persons_map = create_combined_legislators_map("Congress", "persons", map_function)

# Return the map generated by generate_congress_persons_map().
def get_congress_persons_map():
  global congress_persons_map

  # If the Congress persons map is not available yet, generate it.
  if not congress_persons_map:
    generate_congress_persons_map()

  return congress_persons_map

# Get a list of persons who served during a particular Congress.
# 'congress' is the desired Congress.
def get_congress_persons(congress):
  congress_persons_map = get_congress_persons_map()

  if congress not in congress_persons_map:
    raise KeyError("No known persons for Congress '%s'." % ( congress ))

  return congress_persons_map[congress]

# XXX: This exception is deprecated. (It has a typo.) Only use in relation to get_govtrack_person_id().
class UnmatchedIdentifer(Exception):
  def __init__(self, id_type, id_value, help_url):
    super(UnmatchedIdentifer, self).__init__("%s=%s %s" % (id_type, str(id_value), help_url))

# XXX: This function is deprecated. Use get_person_id() instead.
def get_govtrack_person_id(source_id_type, source_id):
  try:
    govtrack_person_id = get_person_id(source_id_type, source_id, "govtrack")
  except KeyError:
    see_also = ""
    if source_id_type == "thomas":
      see_also = "http://beta.congress.gov/member/xxx/" + source_id
    logging.error("GovTrack ID not known for %s %s. (%s)" % (source_id_type, str(source_id), see_also))
    raise UnmatchedIdentifer(source_id_type, source_id, see_also)

  return govtrack_person_id
