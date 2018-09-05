import os
import os.path
import errno
import sys
import traceback
import zipfile
import platform
import re
import htmlentitydefs
import json
from pytz import timezone
import datetime
import time
from lxml import html, etree
import scrapelib
import pprint
import logging
import subprocess
import signal

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
scraper = scrapelib.Scraper(requests_per_minute=120, retry_attempts=3)
scraper.user_agent = "unitedstates/congress (https://github.com/unitedstates/congress)"


def format_datetime(obj):
    if isinstance(obj, datetime.datetime):
        return eastern_time_zone.localize(obj.replace(microsecond=0)).isoformat()
    elif isinstance(obj, datetime.date):
        return obj.isoformat()
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
    return (((int(congress) + 894) * 2) - 1)

# get the three calendar years that the Congress extends through (Jan 3 to Jan 3).


def get_congress_years(congress):
    y1 = get_congress_first_year(congress)
    return (y1, y1 + 1, y1 + 2)

# Get a list of Congresses associated with a particular term.
# XXX: This can be highly unreliable and may be deeply flawed.
# XXX: This would be much simpler if we already included Congresses in the data.


def get_term_congresses(term):
    start_year = int(format_datetime(term["start"])[:4])
    end_year = int(format_datetime(term["end"])[:4])

    start_congress = congress_from_legislative_year(start_year)
    start_congress_years = get_congress_years(start_congress)
    start_congress_first_year = start_congress_years[0]

    if term["type"] in ["sen"]:
        end_congress_years = get_congress_years(start_congress + 2)
        congresses = [start_congress, start_congress + 1, start_congress + 2]
    elif term["type"] in ["prez", "viceprez"] or term["state"] in ["PR"]:
        end_congress_years = get_congress_years(start_congress + 1)
        congresses = [start_congress, start_congress + 1]
    else:
        end_congress_years = start_congress_years
        congresses = [start_congress]

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
    return "%s%s-%s" % (bill_type, bill_number, congress)

# bill_type, bill_number, congress, version_code


def split_bill_version_id(bill_version_id):
    return re.match("^([a-z]+)(\d+)-(\d+)-([a-z\d]+)$", bill_version_id).groups()

# "hjres1234-115-enr"


def build_bill_version_id(bill_type, bill_number, congress, version_code):
    return "%s%s-%s-%s" % (bill_type, bill_number, congress, version_code)


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

        admin(message)  # email if possible

    logging.warning("\nErrors for %s." % len(errors))
    logging.warning("Skipped %s." % len(skips))
    logging.warning("Saved data for %s." % len(saved))

    return saved + skips  # all of the OK's


# Download file at `url`, cache to `destination`.
# Takes many options to customize behavior.
_download_zip_files = {}


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

    timeout = float(options.get('timeout', 30))  # The low level socket api requires a float
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
        for i in xrange(len(dparts) - 1):
            # form the ZIP file name and test if it exists...
            zfn = os.path.join(cache, *dparts[:i + 1]) + ".zip"
            if not os.path.exists(zfn):
                continue

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

            if not test:
                logging.info("Cached: (%s, %s)" % (zfn + "#" + zfn_inner, url))
            if force:
                raise Exception("Cannot re-download a file already cached to a ZIP file.")

            if not is_binary:
                body = body.decode("utf8")
                body = unescape(body)

            return body

    # Load the file from disk if it's already been downloaded and force is False.
    if destination and (not force) and os.path.exists(cache_path):
        if not test:
            logging.info("Cached: (%s, %s)" % (cache_path, url))
        if not needs_content:
            return True
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
                if not needs_content:
                    mkdir_p(os.path.dirname(cache_path))
                    scraper.urlretrieve(url, cache_path, **urlopen_kwargs)
                    return True

                response = scraper.urlopen(url, **urlopen_kwargs)

            if not is_binary:
                body = response  # a subclass of a 'unicode' instance
                if not isinstance(body, unicode):
                    raise ValueError("Content not decoded.")
            else:
                body = response.bytes  # a 'str' instance
                if isinstance(body, unicode):
                    raise ValueError("Binary content improperly decoded.")
        except scrapelib.HTTPError as e:
            logging.error("Error downloading %s:\n\n%s" % (url, format_exception(e)))
            if options.get("return_status_code_on_error"):
                return e.response.status_code
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


def write(content, destination, options={}):
    if options.get("diff"):
        # Instead of writing the file, do a comparison with what's on disk
        # to test any changes. But be nice and replace any update date with
        # what's in the previous file so we avoid spurrious changes. Use
        # how updated_at appears in the JSON and in the XML.
        if os.path.exists(destination):
            with open(destination) as f:
                existing_content = f.read()
            for pattern in ('"updated_at": ".*?"', 'updated=".*?"'):
                m1 = re.search(pattern, existing_content)
                m2 = re.search(pattern, content)
                if m1 and m2:
                    content = content.replace(m2.group(0), m1.group(0))

            # Avoid writing to disk and spawning `diff` by checking if
            # the files match in memory.
            if content == existing_content:
                return

        # Shell `diff` and let it display output directly to the console.
        # Write `content` to disk first so diff can see it. Maybe more
        # efficient to pipe?
        fn = "/tmp/congress-changed-file"
        with open(fn, 'w') as f:
            f.write(content)
        os.system("diff -u %s %s" % (destination, fn))
        os.unlink(fn)
        return

    # Save the content to disk.
    mkdir_p(os.path.dirname(destination))
    f = open(destination, 'w')
    f.write(content)
    f.close()

def write_json(data, destination):
    return write(
        json.dumps(data,
            sort_keys=True,
            indent=2,
            default=format_datetime
        ),
        destination
    )


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
    return [x for x in seq if x not in seen and not seen_add(x)]

import os
import errno

# mkdir -p in python, from:
# http://stackoverflow.com/questions/600268/mkdir-p-functionality-in-python


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
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
        return text  # leave as is

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

        logging.error(body)  # always print it

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


def make_node(parent, tag, text, **attrs):
    """Make a node in an XML document."""
    n = etree.Element(tag)
    parent.append(n)
    n.text = text
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, datetime.datetime):
            v = format_datetime(v)
        n.set(k.replace("___", ""), v)
    return n


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
    mkdir_p(os.path.dirname(filename))
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
        raise CacheError("Could not retrieve potential cache file: %s" % (cache_filename))

    # A cache file has a specific structure.
    if "hash" not in cache_data or "data" not in cache_data:
        raise TypeError("Not a cache file: %s" % (cache_filename))

    # If the hashes don't match, we've retrieved the cache for something else.
    if cache_data["hash"] != file_hash:
        raise CacheError("Hashes do not match: %s, %s" % (file_hash, cache_data["hash"]))

    return cache_data["data"]

# Cache a file.


def cache_write(file_data, filename, file_hash):
    cache_data = {"hash": file_hash, "data": file_data}
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
        lookup_legislator_cache = {}  # from Congress number to list of (moc,term) tuples that might be in that Congress
        for filename in ("legislators-historical", "legislators-current"):
            for moc in yaml_load("congress-legislators/%s.yaml" % (filename)):
                for term in moc["terms"]:
                    for c in xrange(congress_from_legislative_year(int(term['start'][0:4])) - 1,
                                    congress_from_legislative_year(int(term['end'][0:4])) + 1 + 1):
                        lookup_legislator_cache.setdefault(c, []).append((moc, term))

    def to_ascii(name):
        name = name.replace("-", " ")
        if not isinstance(name, unicode):
            return name
        import unicodedata
        return u"".join(c for c in unicodedata.normalize('NFKD', name) if not unicodedata.combining(c))

    # Scan all of the terms that cover 'when' for a match.
    if isinstance(when, datetime.datetime):
        when = when.date()
    when = when.isoformat()
    name_parts = to_ascii(name).split(", ", 1)
    matches = { }
    for moc, term in lookup_legislator_cache[congress]:
        # Make sure the date is surrounded by the term start/end dates.
        if term['start'] > when:
            continue  # comparing ISO-formatted date strings
        if term['end'] < when:
            continue  # comparing ISO-formatted date strings

        # Compare the role type, state, and party, except for people who we know changed party.
        if term['type'] != role_type:
            continue
        if term['state'] != state:
            continue
        if term['party'][0] != party and name not in ("Laughlin", "Crenshaw", "Goode", "Martinez", "Parker", "Emerson", "Tauzin", "Hayes", "Deal", "Forbes"):
            continue

        # When doing process-of-elimination matching, don't match on people we've already seen.
        if moc["id"].get(id_requested) in exclude:
            continue

        # Compare the last name. Allow "Chenoweth" to match "Chenoweth Hage", but also
        # allow "Millender McDonald" to match itself.
        for name_info_rec in [moc['name']] + moc.get('other_names', []):
            # for other_names, check that the record covers the right date range
            if 'start' in name_info_rec and name_info_rec['start'] > when:
                continue  # comparing ISO-formatted date strings
            if 'end' in name_info_rec and name_info_rec['end'] < when:
                continue  # comparing ISO-formatted date strings

            # in order to process an other_name we have to go like this...
            name_info = dict(moc['name'])  # clone
            name_info.update(name_info_rec)  # override with the other_name information

            # check last name
            if name_parts[0] != to_ascii(name_info['last']) \
                    and name_parts[0] not in to_ascii(name_info['last']).split(" "):
                  continue  # no match

            # Compare the first name. Allow it to match either the first or middle name,
            # and an initialized version of the first name (i.e. "E." matches "Eddie").
            # Test the whole string (so that "Jo Ann" is compared to "Jo Ann") but also
            # the first part of a string split (so "E. B." is compared as "E." to "Eddie").
            first_names = (to_ascii(name_info['first']), to_ascii(name_info.get('nickname', "")), to_ascii(name_info['first'])[0] + ".")
            if len(name_parts) >= 2 and \
                    name_parts[1] not in first_names and \
                    name_parts[1].split(" ")[0] not in first_names:
                  continue

            break  # match
        else:
            # no match
            continue

        # This is a possible match. Remember which term matched, but because of term overlaps
        # on Jan 3's, don't key on the term uniquely, only on the moc.
        matches[moc['id'][id_requested]] = term

    # Return if there is a unique match.
    if len(matches) == 0:
        logging.warn("Could not match name %s (%s-%s; %s) to any legislator." % (name, state, party, when))
        return None
    if len(matches) > 1:
        logging.warn("Multiple matches of name %s (%s-%s; %s) to legislators (%s; excludes %s)." % (name, state, party, when, str(matches), str(exclude)))
        return None
    return list(matches)[0]



class UnmatchedIdentifer(Exception):

    def __init__(self, id_type, id_value, desired_id_type):
        super(UnmatchedIdentifer, self).__init__("%s=%s => %s" % (id_type, str(id_value), desired_id_type))

_translate_legislator_id_cache = None

def translate_legislator_id(source_id_type, source_id, dest_id_type):
    global _translate_legislator_id_cache
    # On the first load, cache all of the legislators' ids in memory.
    if not _translate_legislator_id_cache:
        require_congress_legislators_repo()
        _translate_legislator_id_cache = { }
        for filename in ("legislators-historical", "legislators-current"):
            for moc in yaml_load("congress-legislators/%s.yaml" % (filename)):
                for id_type, id_value in moc["id"].items():
                    try:
                        _translate_legislator_id_cache[(id_type, id_value)] = moc['id']
                    except TypeError:
                        # The 'fec' id is a list which is not hashable
                        # and so cannot go in the key of a cached entry.
                        pass

    # Get from mapping.
    try:
        return _translate_legislator_id_cache[(source_id_type, source_id)][dest_id_type]
    except KeyError:
        raise UnmatchedIdentifer(source_id_type, source_id, dest_id_type)

# adapted from https://gist.github.com/tcwalther/ae058c64d5d9078a9f333913718bba95,
# which was based on http://stackoverflow.com/a/21919644/487556.
# This provides a with-block object that prevents Ctrl+C (SIGINT)
# or the TERM signal from interrupting program flow until the
# with-block exits. This is useful to ensure that file write
# operations aren't killed mid-write resulting in a corrupt file.
class NoInterrupt(object):
    def __init__(self, *signals):
        if not signals: signals = [signal.SIGTERM, signal.SIGINT]
        self.sigs = signals        
    def __enter__(self):
        self.signal_received = {}
        self.old_handlers = {}
        for sig in self.sigs:
            def handler(s, frame, sig=sig): # sig=sig ensures the variable is captured by value
                self.signal_received[sig] = (s, frame)
                # Note: in Python 3.5, you can use signal.Signals(sig).name
                logging.info('Signal %s received. Delaying KeyboardInterrupt.' % sig)
            self.old_handlers[sig] = signal.signal(sig, handler)
    def __exit__(self, type, value, traceback):
        # Restore signal handlers that were in place before entering the with-block.
        for sig in self.sigs:
            signal.signal(sig, self.old_handlers[sig])
        # Issue the signals caught during the with-block.
        for sig, args in self.signal_received.items():
            if self.old_handlers[sig]:
                self.old_handlers[sig](*args)
