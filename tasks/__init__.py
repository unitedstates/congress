import os
import os.path
import re
import errno
import logging
import subprocess
import htmlentitydefs
import traceback
import sys
import socket
import pickle
import hashlib
import yaml
import json
import datetime
from pytz import timezone

from pydoc import locate
from abc import ABCMeta, abstractmethod

import scrapelib
from lxml import html, etree
import zipfile
import fs
import fs.errors
import smtplib
import email.utils
from email.mime.text import MIMEText
import fs


class Storage:

    class CacheError(LookupError):
        pass

    def __init__(self, options=None):
        self.options = options or {}
        self.fs = locate(options['filesystem'] if 'filesystem' in self.options else 'fs.osfs.OSFS')('.')
        self.download_zip_files = {}

    def exists(self, destination):
        return self.fs.exists(destination)

    def read(self, destination):
        if self.exists(destination):
            with self.fs.open(destination) as f:
                return f.read()

    def remove(self, destination):
        self.fs.remove(destination)

    def diff(self, content, destination):
        # Instead of writing the file, do a comparison with what's on disk
        # to test any changes. But be nice and replace any update date with
        # what's in the previous file so we avoid spurrious changes. Use
        # how updated_at appears in the JSON and in the XML.
        if self.fs.exists(destination):
            with self.fs.open(destination) as f:
                existing_content = f.read()
                for pattern in ('"updated_at": ".*?"', 'updated=".*?"'):
                    m1 = re.search(pattern, existing_content)
                    m2 = re.search(pattern, content)
                    if m1 and m2:
                        content = content.replace(m2.group(0), m1.group(0))

                # Avoid writing to disk and spawning `diff` by checking if the files match in memory.
                if content == existing_content:
                    return

        # Shell `diff` and let it display output directly to the console.
        # Write `content` to disk first so diff can see it. Maybe more
        # efficient to pipe?
        fn = "cache/congress-changed-file"
        with self.fs.open(fn, 'wb') as f:
            f.write(content)
        os.system("diff -u {0} {1}".format(destination, fn))
        self.remove(fn)
        return True

    def write(self, content, destination, options=None):
        """
        Writes content to a destination. Options available to check for a diff first or lastmod first.

        @param content: what to write to the file
        @type content: (str|binary)
        @param destination: path to where to write to the file
        @type destination: str
        @param options: dictionary of options
        @type options: dict[str, str]
        @return: path to the destination file
        @rtype: str
        """
        options = options or {}
        directory, filename = os.path.split(destination)

        # check diff first if specified
        if options.get('diff', False) and self.diff(content, destination) is None:
            return

        # save the content to disk.
        self.mkdir_p(directory)

        # write content to file
        with self.fs.open(destination, 'wb') as f:
            f.write(content)

        # write cache file if specified
        if options.get('lastmod', False):
            with self.fs.open(Storage.lastmod_path(destination), 'w') as f:
                f.write(options.get('lastmod'))

        return destination

    def mkdir_p(self, path):
        try:
            self.fs.makedir(path, recursive=True, allow_recreate=True)
        except fs.errors.ResourceInvalidError:
            pass
        except:
            raise

    def pickle_load(self, filename):
        return pickle.load(self.fs.open(filename, mode='rb'))

    def pickle_write(self, data, filename):
        self.mkdir_p(os.path.dirname(filename))
        pickle.dump(data, self.fs.open(filename, mode='wb'))

    def cache_write(self, file_data, filename, file_hash):
        cache_data = {"hash": file_hash, "data": file_data}
        return self.pickle_write(cache_data, filename)

    def cache_load(self, cache_filename, file_hash):
        try:
            cache_data = self.pickle_load(cache_filename)
        except (IOError, fs.errors.ResourceNotFoundError):
            raise self.CacheError("Could not retrieve potential cache file: {0}".format(cache_filename))

        # A cache file has a specific structure.
        if "hash" not in cache_data or "data" not in cache_data:
            raise TypeError("Not a cache file: {0}".format(cache_filename))

        # If the hashes don't match, we've retrieved the cache for something else.
        if cache_data["hash"] != file_hash:
            raise self.CacheError("Hashes do not match: %s, %s" % (file_hash, cache_data["hash"]))

        return cache_data["data"]

    def get_file_hash(self, filename):
        return hashlib.sha1(self.read(filename).encode('ascii', 'ignore')).hexdigest()

    def get_cache_filename(self, filename):
        return os.path.join(self.cache_dir, filename + '.pickle')

    def direct_yaml_load(self, filename):
        try:
            from yaml import CLoader as Loader, CDumper as Dumper
        except ImportError:
            from yaml import Loader, Dumper
        return yaml.load(self.fs.open(filename), Loader=Loader)

    def yaml_load(self, filename):
        file_hash = self.get_file_hash(filename)
        cache_filename = self.get_cache_filename(filename)

        # Try to load a cached version of the requested YAML file.
        try:
            yaml_data = self.cache_load(cache_filename, file_hash)
        except self.CacheError:
            # We don't have a cached version of the requested YAML file available, so we have to load it directly.
            logging.warn("Using original YAML file...")

            # Load the requested YAML file directly.
            yaml_data = self.direct_yaml_load(filename)

            # Cache the YAML data so we can retrieve it more quickly next time.
            self.cache_write(yaml_data, cache_filename, file_hash)
        else:
            # We have a cached version of the requested YAML file available, so we can use it.
            logging.info("Using cached YAML file...")

        return yaml_data

    def write_json(self, data, destination):
        return self.write(json.dumps(data, sort_keys=True, indent=2, default=format_datetime), destination)

    @staticmethod
    def lastmod_path(destination):
        return os.path.splitext(destination)[0] + '-lastmod.txt'

    @property
    def cache_dir(self):
        try:
            path = self.options['config']['output']['cache']
        except KeyError:
            # The pyfilesystem filesystem requires an absolute path.
            path = fs.path.abspath('cache')
        return path

    @property
    def test_cache_dir(self):
        return "test/fixtures/cache"

    @property
    def data_dir(self):
        try:
            path = self.options['config']['output']['data']
        except KeyError:
            # The pyfilesystem filesystem requires an absolute path.
            path = fs.path.abspath('data')
        return path


class Task:
    __metaclass__ = ABCMeta

    HAS_CONGRESS_LEGISLATORS_REPO = False
    LOOKUP_LEGISLATOR_CACHE = {}
    LOOKUP_LEGISLATOR_BY_ID_CACHE = {}
    COMMITTEE_NAMES = {}
    EASTERN_TIME_ZONE = timezone('US/Eastern')

    def __init__(self, options=None, config=None):
        self.options = options or {}
        self.config = config or {}
        self.storage = Storage(options['output'] if 'output' in self.options else None)
        socket.setdefaulttimeout(self.config.get('timeout', 10))
        self.scraper = scrapelib.Scraper(
            requests_per_minute=safeget(self.config, 120, 'scrape', 'requests_per_minute'),
            retry_attempts=safeget(self.config, 3, 'scrape', 'retry_attempts')
        )
        self.scraper.user_agent = "unitedstates/congress (https://github.com/unitedstates/congress)"

    @abstractmethod
    def run(self):
        """
        To be implemented by subclasses.
        """
        pass

    def require_congress_legislators_repo(self):
        """
        Once we have the congress-legislators repo, we don't need to keep getting it.

        @return:
        @rtype:
        """
        if self.HAS_CONGRESS_LEGISLATORS_REPO:
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
        self.HAS_CONGRESS_LEGISLATORS_REPO = True

    def send_email(self, message):
        settings = self.config['email']

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

    def admin(self, body):
        try:
            if isinstance(body, Exception):
                body = format_exception(body)

            logging.error(body)  # always print it

            details = self.config.get('email', None)
            if details:
                self.send_email(body)

        except Exception as exception:
            print "Exception logging message to admin, halting as to avoid loop"
            print format_exception(exception)

    def fetch_committee_names(self, congress):
        congress = int(congress)
        committee_names = self.COMMITTEE_NAMES

        # Parse the THOMAS advanced search pages for the names that THOMAS uses for
        # committees on bill pages, and map those to the IDs for the committees that are
        # listed on the advanced search pages (but aren't shown on bill pages).
        if not self.options.get('test', False):
            logging.info("[%d] Fetching committee names..." % congress)

        # allow body to be passed in from fixtures
        if self.options.has_key('body'):
            body = self.options['body']
        else:
            body = self.download(
                "http://thomas.loc.gov/home/LegislativeData.php?&n=BSS&c=%d" % congress,
                "%s/meta/thomas_committee_names.html" % congress)

        for chamber, options in re.findall('>Choose (House|Senate) Committees</option>(.*?)</select>', body, re.I | re.S):
            for name, id in re.findall(r'<option value="(.*?)\{(.*?)}">', options, re.I | re.S):
                id = str(id).upper()
                name = name.strip().replace("  ", " ")  # weirdness
                if id.endswith("00"):
                    # Map chamber + committee name to its ID, minus the 00 at the end. On bill pages,
                    # committees appear as e.g. "House Finance." Except the JCSE.
                    if id != "JCSE00":
                        name = chamber + " " + name

                    # Correct for some oddness on THOMAS (but not on Congress.gov): The House Committee
                    # on House Administration appears just as "House Administration" and in the 104th/105th
                    # Congresses appears as "House Oversight" (likewise the full name is House Committee
                    # on House Oversight --- it's the House Administration committee still).
                    if name == "House House Administration":
                        name = "House Administration"
                    if name == "House House Oversight":
                        name = "House Oversight"

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
        if congress in range(108, 113):
            committee_names["House Intelligence"] = committee_names["House Intelligence (Permanent Select)"]

    def process_set(self, to_fetch, fetch_func, *extra_args):
        errors = []
        saved = []
        skips = []

        for id in to_fetch:
            try:
                results = fetch_func(id, *extra_args)
            except Exception, e:
                if self.options.get('raise', False):
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

            self.admin(message)  # email if possible

        logging.warning("\nErrors for %s." % len(errors))
        logging.warning("Skipped %s." % len(skips))
        logging.warning("Saved data for %s." % len(saved))

        return saved + skips  # all of the OK's

    def download(self, url, destination=None, options=None):

        options = options or {}

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
                cache = self.storage.test_cache_dir if test else self.storage.cache_dir
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
                zf = self.storage.download_zip_files.get(zfn)
                if not zf:
                    zf = zipfile.ZipFile(zfn, "r")
                    self.storage.download_zip_files[zfn] = zf
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
        if destination and (not force) and self.storage.exists(cache_path):
            if not test:
                logging.info("Cached: (%s, %s)" % (cache_path, url))
            if not needs_content:
                return True
            with self.storage.fs.open(cache_path, 'r') as f:
                body = f.read()
            if not is_binary:
                body = body.decode("utf8")

        # Download from the network and cache to disk.
        else:
            try:
                logging.info("Downloading: %s" % url)

                if postdata:
                    response = self.scraper.post(url, postdata, **urlopen_kwargs)
                else:
                    response = self.scraper.get(url, **urlopen_kwargs)

                if not is_binary:
                    body = response.text  # a subclass of a 'unicode' instance
                    if not isinstance(body, unicode):
                        raise ValueError("Content not decoded.")
                else:
                    body = response.content # a 'str' instance
                    if isinstance(body, unicode):
                        raise ValueError("Binary content improperly decoded.")
            except scrapelib.HTTPError as e:
                logging.error("Error downloading %s:\n\n%s" % (url, format_exception(e)))
                return None

            # don't allow 0-byte files
            if (not body) or (not body.strip()):
                return None

            # cache content to disk
            if destination:
                self.storage.write(body if is_binary else body.encode("utf8"), cache_path, options)

        if not is_binary:
            body = unescape(body)

        return body

    def lookup_legislator_by_id(self, id_type, id):
        # Look up a legislator by their id.

        # On the first load, cache all of the legislators' ids in memory.
        if not self.LOOKUP_LEGISLATOR_BY_ID_CACHE:
            self.require_congress_legislators_repo()
            for filename in ("legislators-historical", "legislators-current"):
                for moc in self.storage.yaml_load("congress-legislators/%s.yaml" % (filename)):
                    for k, v in moc["id"].items():
                        try:
                            self.LOOKUP_LEGISLATOR_BY_ID_CACHE[(k, v)] = moc
                        except TypeError:
                            # The 'fec' id is a list which is not hashable
                            # and so cannot go in the key of LOOKUP_LEGISLATOR_BY_ID_CACHE.
                            pass

        # Get from mapping.
        return self.LOOKUP_LEGISLATOR_BY_ID_CACHE[(id_type, id)]

    def lookup_legislator(self, congress, role_type, name, state, party, when, id_requested, exclude=set()):
        # This is a basic lookup function given the legislator's name, state, party,
        # and the date of the vote.

        # On the first load, cache all of the legislators' terms in memory.
        # Group by Congress so we can limit our search later to be faster.
        if not self.LOOKUP_LEGISLATOR_CACHE:
            self.require_congress_legislators_repo()
            for filename in ("legislators-historical", "legislators-current"):
                for moc in self.storage.yaml_load("congress-legislators/%s.yaml" % (filename)):
                    for term in moc["terms"]:
                        for c in xrange(congress_from_legislative_year(int(term['start'][0:4])) - 1,
                                        congress_from_legislative_year(int(term['end'][0:4])) + 1 + 1):
                            self.LOOKUP_LEGISLATOR_CACHE.setdefault(c, []).append((moc, term))

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
        matches = []
        for moc, term in self.LOOKUP_LEGISLATOR_CACHE[congress]:
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


# Utility Functions

def ordinalize(n):
    """
    Turns a number into an ordinal representation takenly shamelessly from
    http://stackoverflow.com/questions/9647202/ordinal-numbers-replacement

    @param n:
    @type n:
    @return:
    @rtype:
    """
    return "%d%s" % (n,"tsnrhtdd"[(n/10%10!=1)*(n%10<4)*n%10::4])


def safeget(dct, default, *keys):
    """

    @param dct:
    @type dct:
    @param default:
    @type default:
    @param keys:
    @type keys:
    @return:
    @rtype:
    """
    for key in keys:
        try:
            dct = dct[key]
        except:
            return default
    return dct


def unescape(text):
    """

    @param text:
    @type text:
    @return:
    @rtype:
    """

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


def format_exception(e):
    """

    @param e:
    @type e:
    @return:
    @rtype:
    """
    exc_type, exc_value, exc_traceback = sys.exc_info()
    return "\n".join(traceback.format_exception(exc_type, exc_value, exc_traceback))


def merge(dict1, dict2):
    """

    @param dict1:
    @type dict1:
    @param dict2:
    @type dict2:
    @return:
    @rtype:
    """
    return dict(dict1.items() + dict2.items())


def unwrap_text_in_html(data):
    """

    @param data:
    @type data:
    @return:
    @rtype:
    """
    text_content = unicode(html.fromstring(data).text_content())
    return text_content#.encode("utf8")


def format_datetime(obj):
    """

    @param obj:
    @type obj:
    @return:
    @rtype:
    """
    eastern_time_zone = timezone('US/Eastern')
    if isinstance(obj, datetime.datetime):
        return eastern_time_zone.localize(obj.replace(microsecond=0)).isoformat()
    elif isinstance(obj, datetime.date):
        return obj.isoformat()
    elif isinstance(obj, (str, unicode)):
        return obj
    else:
        return None


def current_legislative_year(date=None):
    """

    @param date:
    @type date:
    @return:
    @rtype:
    """
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
    """

    @param congress:
    @type congress:
    @return:
    @rtype:
    """
    return ((int(congress) + 894) * 2) - 1


def current_congress():
    """

    @return:
    @rtype:
    """
    year = current_legislative_year()
    return congress_from_legislative_year(year)


def congress_from_legislative_year(year):
    """

    @param year:
    @type year:
    @return:
    @rtype:
    """
    return ((year + 1) / 2) - 894


def uniq(seq):
    """

    @param seq:
    @type seq:
    @return:
    @rtype:
    """
    seen = set()
    seen_add = seen.add
    return [x for x in seq if x not in seen and not seen_add(x)]


def make_node(parent, tag, text, **attrs):
    """
    Make a node in an XML document.

    @param parent:
    @type parent:
    @param tag:
    @type tag:
    @param text:
    @type text:
    @param attrs:
    @type attrs:
    @return:
    @rtype:
    """
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


def neighborhood(iterable):
    iterator = iter(iterable)
    prev = None
    item = iterator.next()  # throws StopIteration if empty.
    for next in iterator:
        yield (prev,item,next)
        prev = item
        item = next
    yield (prev,item,None)
