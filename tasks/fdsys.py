# Downloads documents from GPO FDSys, using their sitemaps
# to efficiently determine what needs to be updated.
#
# ./run fdsys --list
# Dumps a list of the names of GPO's collections and the years
# they have data in (since most collections are divided by year
# of document publication).
#
# ./run fdsys --collections=BILLS --bulkdata=False
# Download bill text (from the primary FDSys BILLS collection;
# there's also a bulk data BILLS collection but it has less it
# it).
#
#   Options:
#
#   --collections=BILLS,BILLSTATUS,STATUTE,...
#   Restricts the downloads to just the named collections. For
#   BILLS, you should probably also specify --bulkdata=True/False.
#   If omitted, downloads files from all collections.
#
#   --bulkdata=True|False
#   Download regular document collections or bulk data collections.
#   If omitted, downloads all. But there's a problem-
#   The BILLS collection occurs both as a regular documents
#   collection (bill text in multiple formats) and as a bulk
#   data collection (just XML starting recently). This flag is
#   how you can distinguish which one you want.
#
#   --years=2001[,2002,2004]
#   Comma-separated list of years to download from (does not
#   apply to bulk data collections which are not divided by
#   year).
#
#   --store=mods,pdf,text,xml,premis
#   Save the MODS, PDF, text, XML, or PREMIS file associated
#   with each package. If omitted, stores every file for each
#   package.
#
#   --filter="regex"
#   Only stores files that match the regex. Regular collections
#   are matched against the package name (i.e. BILLS-113hconres66ih)
#   while bulk data items are matched against the their file path
#   (i.e. 113/1/hconres/BILLS-113hconres66ih.xml).
#
#   --granules
#   Some collections, like STATUTE, have "granules" inside each
#   package (a package is a volume of the Statutes at Large, while
#   a granule is an extracted portion for a particular public law).
#   With --granules, saves the individual granules instead of the
#   main package files.
#
#   --cached|--force
#   Always/never use the cache.

import os.path
from lxml import etree, html
import json
import re
import logging
import os.path
import utils
from bill_info import output_for_bill
from tasks import Task, merge, unwrap_text_in_html


class Fdsys(Task):

    NAMESPACES = {'x': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    SITEMAP_BASE_URL = 'https://www.gpo.gov/smap/'
    BULKDATA_BASE_URL = 'https://www.gpo.gov/fdsys/bulkdata/'
    BULK_BILLSTATUS_FILENAME = 'fdsys_billstatus.xml'

    def __init__(self, options=None, config=None):
        super(Fdsys, self).__init__(options, config)
        self.fetch_collections = filter(None, set(options.get("collections", '').split(","))) or None
        self.listing = []

    def run(self):
        """
        GPO FDSys organizes its sitemaps by publication year (the date of
        original print publication) and then by colletion (bills, statutes,
        etc.). There are additional unconnected sitemaps for each bulk
        data collection.

        @return: saves
        @rtype: None
        """

        # Update our cache of the complete FDSys sitemap and download package
        # files as requested in the command-line options.
        self.update_sitemap_cache()
    
        # With --list, just output all of the available data on FDSys
        # (the collection names, and the years each collection is available in, etc.).
        if self.options.get('list', False):
            listing = sorted(map(self.format_item_for_listing, self.listing))
            for item in listing:
                print item

    def update_sitemap_cache(self):
        """
        Updates the local cache of the complete FDSys sitemap trees,
        only downloading changed sitemap files.

        @return: None
        @rtype: None
        """

        # with --bulkdata=False, or not specified
        if self.options.get('bulkdata', None) in (None, False):
            # Process the main sitemap index for all of the document collections.
            self.update_sitemap(self.SITEMAP_BASE_URL + "fdsys/sitemap.xml", None, [])
    
        # with --bulkdata=True, or not specified
        if self.options.get("bulkdata", None) in (None, True):
            # Scrape FDSys for a list of the names of the bulk data collections.
            # (The last modified date from the directory listing on this page is
            # not an indication of the lastmod dates within sitemaps.)
            #
            # Note that "BILLS" appears both as a regular collection and as a
            # bulk data collection - both are bill text.
            fdsys_bulkdata_list = self.download(self.BULKDATA_BASE_URL,
                                                'fdsys/sitemap/bulkdata.html',
                                                self.options)
            bulk_data_collections = re.findall(
                r"<a href=\"bulkdata/(\w+)\"\s*>[^<]*</a>[^<]*</td>[^<]*<td>([^<]+)",
                fdsys_bulkdata_list)
    
            # Process the bulk data collections sitemaps.
            for collection, timestamp in bulk_data_collections:
                self.update_sitemap(self.SITEMAP_BASE_URL + 'bulkdata/{0}/sitemapindex.xml'.format(collection),
                    None, [])
    
    def update_sitemap(self, url, current_lastmod, how_we_got_here):
        """
        Updates the local cache of a sitemap file.

        @param url:
        @type url:
        @param current_lastmod:
        @type current_lastmod:
        @param how_we_got_here:
        @type how_we_got_here:
        @return:
        @rtype:
        """

        # What is this sitemap for?
        subject = self.extract_sitemap_subject_from_url(url, how_we_got_here)
    
        # For debugging, remember what URLs we are stepping through.
        how_we_got_here = how_we_got_here + [url]
    
        # Does the user want to process this sitemap?
        if self.skip_sitemap(subject):
            return
    
        # Where to cache the sitemap and a file where we store its current <lastmod> date
        # (which comes from a parent sitemap)?
        (cache_file, lastmod_cache_file) = self.get_sitemap_cache_files(subject)
        lastmod_cache_file = os.path.join(self.storage.cache_dir, lastmod_cache_file)
    
        # Download anew if the current_lastmod doesn't match the stored lastmod
        # in our cache, and if --cache is not specified. Or if --force is given.
        # If we're not downloading it, load it from disk because we still have
        # to process each sitemap to ensure we've downloaded all of the package
        # files the user wants.
        download = self.should_download_sitemap(lastmod_cache_file, current_lastmod)
    
        # Download, or just retrieve from cache.
        if download:
            logging.warn("Downloading: %s" % url)
        body = self.download(url, cache_file, merge(self.options, {'force': download, 'binary': True}))
        if not body:
            raise Exception("Failed to download %s" % url)
    
        # Write the current last modified date to disk so we know the next time whether
        # we need to fetch the file --- if we just downloaded it.
        if download and current_lastmod:
            utils.write(current_lastmod, lastmod_cache_file)
    
        # Load the XML.
        try:
            sitemap = etree.fromstring(body)
        except etree.XMLSyntaxError as e:
            raise Exception("XML syntax error in %s: %s" % (url, str(e)))
    
        # Process the entries.
        if sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex":
    
            # This is a sitemap index. Process the sitemaps listed in this
            # sitemapindex recursively.
            for node in sitemap.xpath("x:sitemap", namespaces=self.NAMESPACES):
                # Get URL and lastmod date of the sitemap.
                url = str(node.xpath("string(x:loc)", namespaces=self.NAMESPACES))
                lastmod = str(node.xpath("string(x:lastmod)", namespaces=self.NAMESPACES))
                self.update_sitemap(url, lastmod, how_we_got_here)
        
        elif sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
    
            # This is a regular sitemap with content items listed.
    
            # For the --list command, remember that this sitemap had some data.
            # And then return --- don't download any package files.
            if self.options.get("list"):
                self.listing.append(subject)
                return
    
            # Process the items.
            for node in sitemap.xpath("x:url", namespaces=self.NAMESPACES):
                url = str(node.xpath("string(x:loc)", namespaces=self.NAMESPACES))
                lastmod = str(node.xpath("string(x:lastmod)", namespaces=self.NAMESPACES))
    
                if not subject.get("bulkdata"):
                    # This is a regular collection item.
                    #
                    # Get the "package" name, i.e. a particular document (which has
                    # one or more file formats within it).
                    m = re.match("https://www.gpo.gov/fdsys/pkg/(.*)/content-detail.html", url)
                    if not m:
                        raise Exception("Unmatched package URL (%s) at %s." % (url, "->".join(how_we_got_here)))
                    package_name = m.group(1)
                    if self.options.get("filter") and not re.search(self.options["filter"], package_name):
                        continue
                    self.mirror_package(subject, package_name, lastmod, url)
    
                else:
                    # This is a bulk data item. Extract components of the URL.
                    m = re.match("https://www.gpo.gov/fdsys/bulkdata/%s/(.+)" % re.escape(subject["collection"]), url)
                    if not m:
                        raise Exception("Unmatched bulk data file URL (%s) at %s." % (url, "->".join(how_we_got_here)))
                    item_path = m.group(1)
                    if self.options.get("filter") and not re.search(self.options["filter"], item_path):
                        continue
                    self.mirror_bulkdata_file(subject, url, item_path, lastmod)
        
        else:
            raise Exception("Unknown sitemap type (%s) at the root sitemap of %s." % (sitemap.tag, url))

    def extract_sitemap_subject_from_url(self, url, how_we_got_here):
        # The root of the main documents collections sitemap.
        if url == self.SITEMAP_BASE_URL + "fdsys/sitemap.xml":
            return {}
    
        # A year sitemap under the main documents root.
        m = re.match(re.escape(self.SITEMAP_BASE_URL) + r"fdsys/sitemap_(\d+)/sitemap_\d+.xml$", url)
        if m:
            return {"year": m.group(1)}
    
        # A regular collection sitemap.
        m = re.match(re.escape(self.SITEMAP_BASE_URL) + r"fdsys/sitemap_(\d+)/\d+_(.*)_sitemap.xml$", url)
        if m:
            return {"year": m.group(1), "collection": m.group(2)}
    
        # The root of a bulkdata collection. Bulk data sitemaps
        # aren't grouped by year in the same way the regular
        # collections are.
        m = re.match(re.escape(self.SITEMAP_BASE_URL) + r"bulkdata/(.*)/sitemapindex.xml$", url)
        if m:
            return {"bulkdata": True, "collection": m.group(1)}
    
        # Bulk data collections have subdivisions, like for BILLS it's
        # subdivided by Congress+bill-type strings (like "113s" for
        # 113th Congress, "S." (senate) bills).
        m = re.match(re.escape(self.SITEMAP_BASE_URL) + r"bulkdata/(.*)/([^/]+)/sitemap.xml$", url)
        if m:
            return {"bulkdata": True, "collection": m.group(1), "grouping": m.group(2)}
    
        raise ValueError("Unrecognized sitemap URL: " + url + " (" + "->".join(how_we_got_here) + ")")

    def skip_sitemap(self, subject):
        # Which years should we download? All if none is specified.
        if "year" in subject and self.options.get("years", "").strip() != "":
            only_years = set(self.options.get("years").split(","))
            if subject["year"] not in only_years:
                return True
    
        # Which collections should we download? All if none is specified.
        if "collection" in subject and self.options.get("collections", "").strip() != "":
            only_collections = set(self.options.get("collections").split(","))
            if subject["collection"] not in only_collections:
                return True
    
        return False
    
    def get_sitemap_cache_files(self, subject):
        # Where should we store the local cache of the sitemap XML and a file
        # that stores its <lastmod> date for when we last downloaded it? Returns
        # a path relative to the cache root.
    
        cache_file = "fdsys/sitemap"
        
        if "year" in subject:
            # The main document collections have years, but the bulk data
            # collections don't.
            cache_file = os.path.join(cache_file, subject["year"])
        
        if "collection" in subject:
            # The root sitemap for the main collections doesn't have a "collection" name.
            cache_file = os.path.join(cache_file, subject["collection"])
    
        if "grouping" in subject:
            # Some bulk data sitemaps have what we're calling groupings.
            cache_file = os.path.join(cache_file, subject["grouping"])
    
        cache_file = os.path.join(cache_file, "sitemap.xml")
    
        lastmod_cache_file = cache_file.replace(".xml", "-lastmod.txt")
    
        return (cache_file, lastmod_cache_file)

    def should_download_sitemap(self, lastmod_cache_file, current_lastmod):
        # Download a sitemap or just read from our cache?
    
        if not current_lastmod:
            # No lastmod is known for this file (it's the root of a sitemap
            # tree - this is the first web request).
            return True
    
        elif self.options.get("force", False):
            # User requests downloading everything.
            return True
    
        elif self.options.get("cached", False):
            # User requests downloading nothing.
            return False
    
        else:
            # Download if the lastmod from the parent sitemap doesn't agree with
            # the lastmod stored on disk.
            return current_lastmod != self.storage.read(lastmod_cache_file)

    def format_item_for_listing(self, item):
        """

        @param item:
        @type item:
        @return:
        @rtype:
        """
        # Helper function for the --list command.
    
        ret = item["collection"]
        if item.get("bulkdata"):
            ret += " (bulkdata)"
    
        if item.get("year"):
            # for regular collections
            ret += " " + item["year"]
    
        if item.get("grouping"):
            # for bulk data collections
            ret += " " + item["grouping"]
    
        return ret

    def mirror_package(self, sitemap, package_name, lastmod, content_detail_url):
        """
        Create a local mirror of a FDSys package.

        @param sitemap:
        @type sitemap:
        @param package_name:
        @type package_name:
        @param lastmod:
        @type lastmod:
        @param content_detail_url:
        @type content_detail_url:
        @return:
        @rtype:
        """
    
        if not self.options.get("granules", False):
            # Most packages are just a package. This is the usual case.
            self.mirror_package_or_granule(sitemap, package_name, None, lastmod)
        else:
            # In some collections, like STATUTE, each document has subparts which are not
            # described in the sitemap. Load the main HTML page and scrape for the sub-files.
            # In the STATUTE collection, the MODS information in granules is redundant with
            # information in the top-level package MODS file. But the only way to get granule-
            # level PDFs is to go through the granules.
            content_index = utils.download(content_detail_url,
                                           "fdsys/package/{0}/{1}/{2}.html".format(sitemap["year"], sitemap["collection"], package_name),
                                           utils.merge(self.options, {
                                               'binary': True,
                                           }))
            if not content_index:
                raise Exception("Failed to download %s" % content_detail_url)
            for link in html.fromstring(content_index).cssselect("table.page-details-data-table td.rightLinkCell a"):
                if link.text == "More":
                    m = re.match("granule/(.*)/(.*)/content-detail.html", link.get("href"))
                    if not m or m.group(1) != package_name:
                        raise Exception("Unmatched granule URL %s" % link.get("href"))
                    granule_name = m.group(2)
                    self.mirror_package_or_granule(sitemap, package_name, granule_name, lastmod)
    
    def mirror_package_or_granule(self, sitemap, package_name, granule_name, lastmod):
        # Where should we store the file? Each collection has a different
        # file system layout (for BILLS, we put bill text along where the
        # bills scraper puts bills).
        path = self.get_output_path(sitemap, package_name, granule_name)
        if not path:
            return  # should skip
    
        # Get the lastmod times of the files previously saved for this package.
        file_lastmod = {}
        lastmod_cache_file = path + "/lastmod.json"
        if os.path.exists(lastmod_cache_file):
            file_lastmod = json.load(open(lastmod_cache_file))
    
        # Try downloading files for each file type.
        targets = self.get_package_files(package_name, granule_name)
        for file_type, (file_url, relpath) in targets.items():
            # Does the user want to save this file type? If the user didn't
            # specify --store, save everything. Otherwise only save the
            # file types asked for.
            if self.options.get("store", "") and file_type not in self.options["store"].split(","):
                continue
    
            # Do we already have this file updated? The file_lastmod JSON
            # stores the lastmod from the sitemap at the time we downloaded
            # the individual file.
            if file_lastmod.get(file_type) == lastmod:
                if not self.options.get("force", False):
                    continue
    
            # With --cached, skip if the file is already downloaded.
            file_path = os.path.join(path, relpath)
            if self.storage.exists(file_path) and self.options.get("cached", False):
                continue
    
            # Download.
            logging.warn("Downloading: " + file_path)
            data = self.download(file_url, file_path, utils.merge(self.options, {
                'binary': True,
                'force': True, # decision to cache was made above
                'to_cache': False,
                'return_status_code_on_error': True,
                # an old optimization, but it conflicts with return_status_code_on_error
                #'needs_content': (file_type == "text" and file_path.endswith(".html")),
            }))

            # Download failed?
            if data == 404:
                # Not all packages have all file types. Just check the ones we know
                # must be there.
                if file_type in ("pdf", "zip"):
                    # expected to be present for all packages
                    raise Exception("Failed to download %s %s (404)" % (package_name, file_type))
                elif sitemap["collection"] == "BILLS" and file_type in ("text", "mods"):
                    # expected to be present for bills
                    raise Exception("Failed to download %s %s (404)" % (package_name, file_type))
            elif not data or isinstance(data, int):
                # There was some other error - skip the rest. Don't
                # update file_lastmod!
                continue
    
            # Update the lastmod of the downloaded file. If the download failed,
            # because of a 404, we still update this to indicate that the file
            # definitively does not exist. We won't try fetcihng it again.
            file_lastmod[file_type] = lastmod
    
            # The "text" format files are put in an HTML container. Unwrap it into a .txt file.
            # TODO: Encoding? The HTTP content-type header says UTF-8, but do we trust it?
            #       html.fromstring does auto-detection.
            if file_type == "text" and file_path.endswith(".html"):
                file_path_text = file_path[0:-4] + "txt"
                logging.info("Unwrapping HTML to: " + file_path_text)
                with self.storage.fs.open(file_path_text, 'w') as f:
                    f.write(unwrap_text_in_html(data))
    
        # Write the current last modified date back to disk so we know the next time whether
        # we need to fetch the files for this sitemap item. Assuming we fetched anything.
        if file_lastmod:
            utils.write(json.dumps(file_lastmod), lastmod_cache_file)

    @staticmethod
    def get_bill_id_for_package(package_name, with_version=True, restrict_to_congress=None):
        """

        @param package_name:
        @type package_name:
        @param with_version:
        @type with_version:
        @param restrict_to_congress:
        @type restrict_to_congress:
        @return:
        @rtype:
        """

        m = re.match(r'BILL(?:S|STATUS)-(\d+)([a-z]+)(\d+)([a-z][a-z0-9]*|)$', package_name)
        if not m:
            raise Exception('Unmatched bill document package name: ' + package_name)
        congress, bill_type, bill_number, version_code = m.groups()
    
        if restrict_to_congress and int(congress) != int(restrict_to_congress):
            return None

        if not with_version:
            return '{0}{1}-{2}'.format(bill_type, bill_number, congress), version_code #'%s%s-%s' % (bill_type, bill_number, congress), version_code
        else:
            return '{0}{1}-{2}-{3}'.format(bill_type, bill_number, congress, version_code)

    def get_output_path(self, sitemap, package_name, granule_name):
        """
        Where to store the document files?

        @param sitemap:
        @type sitemap:
        @param package_name:
        @type package_name:
        @param granule_name:
        @type granule_name:
        @return:
        @rtype:
        """
        # The path will depend a bit on the collection.
        if sitemap["collection"] == "BILLS":
            # Store with the other bill data.
            bill_and_ver = self.get_bill_id_for_package(package_name, with_version=False,
                                                        restrict_to_congress=self.options.get("congress"))
            if not bill_and_ver:
                return None  # congress number does not match options["congress"]
            bill_id, version_code = bill_and_ver
            return output_for_bill(bill_id, "text-versions/" + version_code, is_data_dot=False)
        else:
            # Store in fdsys/COLLECTION/YEAR/PKGNAME[/GRANULE_NAME].
            path = "%s/fdsys/%s/%s/%s" % (self.storage.data_dir, sitemap["collection"], sitemap["year"], package_name)
            if granule_name:
                path += "/" + granule_name
            return path

    @staticmethod
    def get_package_files(package_name, granule_name):
        """
        What URL are the package files at? Return a tuple of the remote URL
        and a relative filename for storing it locally.

        @param package_name:
        @type package_name: str
        @param granule_name:
        @type granule_name: str
        @return: dictionary of paths to the resource files
        @rtype: dict
        """
    
        baseurl = "https://www.gpo.gov/fdsys/pkg/{0}".format(package_name)
    
        if not granule_name:
            # For regular packages, the URL layout is...
            baseurl2 = baseurl
            file_name = package_name
        else:
            # For granules, the URL layout is...
            baseurl2 = "https://www.gpo.gov/fdsys/granule/{0}/{1}".format(package_name, granule_name)
            file_name = granule_name
    
        ret = {
           'mods': (baseurl2 + "/mods.xml",                  "mods.xml"),
            'pdf': (baseurl + "/pdf/" + file_name + ".pdf",  "document.pdf"),
            'xml': (baseurl + "/xml/" + file_name + ".xml",  "document.xml"),
           'text': (baseurl + "/html/" + file_name + ".htm", "document.html"),  # text wrapped in HTML!
         'premis': (baseurl + "/premis.xml",                 "premis.xml")
        }
    
        if granule_name:
            # Granules don't have PREMIS files.
            del ret['premis']
    
        if package_name.startswith("STATUTE-"):
            # Statutes at Large don't have XML.
            del ret['xml']
    
        return ret

    def mirror_bulkdata_file(self, sitemap, url, item_path, lastmod):
        """
        Downloading bulk data files.

        @param sitemap:
        @type sitemap:
        @param url:
        @type url:
        @param item_path:
        @type item_path:
        @param lastmod:
        @type lastmod:
        @return:
        @rtype:
        """

        # Where should we store the file?
        path = "%s/fdsys/%s/%s" % (self.storage.data_dir, sitemap["collection"], item_path)
    
        # For BILLSTATUS, store this along with where we store the rest of bill
        # status data.
        if sitemap["collection"] == 'BILLSTATUS':
            bill_id, version_code = self.get_bill_id_for_package(os.path.splitext(os.path.basename(item_path))[0],
                                                                 with_version=False)
            path = output_for_bill(bill_id, self.BULK_BILLSTATUS_FILENAME, is_data_dot=False)
    
        # Where should we store the lastmod found in the sitemap so that
        # we can tell later if the file has changed?
        lastmod_cache_file = os.path.splitext(path)[0] + "-lastmod.txt"
    
        # Do we already have this file up to date?
        if self.storage.exists(lastmod_cache_file) and not self.options.get('force', False):
            if lastmod == utils.read(lastmod_cache_file):
                return
    
        # With --cached, skip if the file is already downloaded.
        if os.path.exists(path) and self.options.get("cached", False):
            return
    
        # Download.
        logging.warn("Downloading: " + path)
        data = utils.download(url, path, utils.merge(self.options, {
            'binary': True,
            'force': True, # decision to cache was made above
            'to_cache': False,
        }))
        if not data:
            # Something failed.
            return
    
        # Write the current last modified date back to disk so we know the next time whether
        # we need to fetch the file again.
        self.storage.write(lastmod, lastmod_cache_file)
