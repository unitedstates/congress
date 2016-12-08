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
#   --congress=113[,114]
#   Comma-separated list of congresses to download from (only for
#   BILLSTATUS). Alternate format:
#
#   --congress=">113"
#   Specify a number to get all congresses *after* the value (only for
#   BILLSTATUS) The quotes are necessary for this format.
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

from lxml import etree, html
import glob
import json
import re
import logging
import os.path
import zipfile
import utils

# globals
fdsys_baseurl = "https://www.gpo.gov/smap/"
BULKDATA_BASE_URL = "https://www.gpo.gov/fdsys/bulkdata/"
FDSYS_BILLSTATUS_FILENAME = "fdsys_billstatus.xml"

# for xpath
ns = {"x": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# Main entry point

def run(options):
    # GPO FDSys organizes its sitemaps by publication year (the date of
    # original print publication) and then by colletion (bills, statutes,
    # etc.). There are additional unconnected sitemaps for each bulk
    # data collection.

    # Update our cache of the complete FDSys sitemap and download package
    # files as requested in the command-line options.
    listing = []
    update_sitemap_cache(options, listing)

    # With --list, just output all of the available data on FDSys
    # (the collection names, and the years each collection is available in, etc.).
    if options.get("list", False):
        listing = map(format_item_for_listing, listing)
        listing.sort()
        for item in listing:
            print item


# Processing the Sitemaps


def update_sitemap_cache(options, listing):
    """Updates the local cache of the complete FDSys sitemap trees,
    only downloading changed sitemap files."""

    # with --bulkdata=False, or not specified
    if options.get("bulkdata", None) in (None, False):
        # Process the main sitemap index for all of the document collections.
        update_sitemap(fdsys_baseurl + "fdsys/sitemap.xml", None, [], options, listing)

    # with --bulkdata=True, or not specified
    if options.get("bulkdata", None) in (None, True):
        # Process the bulk data sitemap index.
        update_sitemap(fdsys_baseurl + "bulkdata/sitemapindex.xml", None, [], options, listing)

def update_sitemap(url, current_lastmod, how_we_got_here, options, listing):
    """Updates the local cache of a sitemap file."""

    # Return a list of files we downloaded.
    results = []

    # What is this sitemap for?
    subject = extract_sitemap_subject_from_url(url, how_we_got_here)

    # For debugging, remember what URLs we are stepping through.
    how_we_got_here = how_we_got_here + [url]

    # Does the user want to process this sitemap?
    if skip_sitemap(subject, options):
        return

    # Where to cache the sitemap and a file where we store its current <lastmod> date
    # (which comes from a parent sitemap)?
    (cache_file, lastmod_cache_file) = get_sitemap_cache_files(subject)
    lastmod_cache_file = os.path.join(utils.cache_dir(), lastmod_cache_file)

    # Download anew if the current_lastmod doesn't match the stored lastmod
    # in our cache, and if --cache is not specified. Or if --force is given.
    # If we're not downloading it, load it from disk because we still have
    # to process each sitemap to ensure we've downloaded all of the package
    # files the user wants.
    download = should_download_sitemap(lastmod_cache_file, current_lastmod, options)

    # Download, or just retreive from cache.
    if download:
        logging.warn("Downloading: %s" % url)
    body = utils.download(
        url,
        cache_file,
        utils.merge(options, {
            'force': download,
            'binary': True
        }))
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
        for node in sitemap.xpath("x:sitemap", namespaces=ns):
            # Get URL and lastmod date of the sitemap.
            url = str(node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(node.xpath("string(x:lastmod)", namespaces=ns))
            sitemap_results = update_sitemap(url, lastmod, how_we_got_here, options, listing)
            if sitemap_results is not None:
                results = results + sitemap_results

    elif sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":

        # This is a regular sitemap with content items listed.

        # For the --list command, remember that this sitemap had some data.
        # And then return --- don't download any package files.
        if options.get("list"):
            listing.append(subject)
            return

        # Process the items.
        for node in sitemap.xpath("x:url", namespaces=ns):
            url = str(node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(node.xpath("string(x:lastmod)", namespaces=ns))

            if not subject.get("bulkdata"):
                # This is a regular collection item.
                #
                # Get the "package" name, i.e. a particular document (which has
                # one or more file formats within it).
                m = re.match("https://www.gpo.gov/fdsys/pkg/(.*)/content-detail.html", url)
                if not m:
                    raise Exception("Unmatched package URL (%s) at %s." % (url, "->".join(how_we_got_here)))
                package_name = m.group(1)
                if options.get("filter") and not re.search(options["filter"], package_name): continue
                results = mirror_package(subject, package_name, lastmod, url, options)

            else:
                # This is a bulk data item. Extract components of the URL.
                m = re.match(re.escape(BULKDATA_BASE_URL) + re.escape(subject["collection"]) + "/(.+)", url)
                if not m:
                    raise Exception("Unmatched bulk data file URL (%s) at %s." % (url, "->".join(how_we_got_here)))
                item_path = m.group(1)
                if options.get("filter") and not re.search(options["filter"], item_path): continue
                results = mirror_bulkdata_file(subject, url, item_path, lastmod, options)

    else:
        raise Exception("Unknown sitemap type (%s) at the root sitemap of %s." % (sitemap.tag, url))

    return results


def extract_sitemap_subject_from_url(url, how_we_got_here):
    # The root of the main documents collections sitemap.
    if url == fdsys_baseurl + "fdsys/sitemap.xml":
        return { }

    # A year sitemap under the main documents root.
    m = re.match(re.escape(fdsys_baseurl) + r"fdsys/sitemap_(\d+)/sitemap_\d+.xml$", url)
    if m:
        return { "year": m.group(1) }

    # A regular collection sitemap.
    m = re.match(re.escape(fdsys_baseurl) + r"fdsys/sitemap_(\d+)/\d+_(.*)_sitemap.xml$", url)
    if m:
        return { "year": m.group(1), "collection": m.group(2) }

    if url == fdsys_baseurl + "bulkdata/sitemapindex.xml":
        return { "bulkdata": True }

    # The root of a bulkdata collection. Bulk data sitemaps
    # aren't grouped by year in the same way the regular
    # collections are.
    m = re.match(re.escape(fdsys_baseurl) + r"bulkdata/(.*)/sitemapindex.xml$", url)
    if m:
        return { "bulkdata": True, "collection": m.group(1) }

    # Bulk data collections have subdivisions, like for BILLS it's
    # subdivided by Congress+bill-type strings (like "113s" for
    # 113th Congress, "S." (senate) bills).
    m = re.match(re.escape(fdsys_baseurl) + r"bulkdata/(.*)/([^/]+)/sitemap.xml$", url)
    if m:
        return_data = { "bulkdata": True, "collection": m.group(1), "grouping": m.group(2) }
        congress_match = re.match(r"^([0-9]+)", m.group(2))
        if return_data["collection"] == "BILLSTATUS" and congress_match:
            return_data['congress'] = congress_match.group(1)

        return return_data

    raise ValueError("Unrecognized sitemap URL: " + url + " (" + "->".join(how_we_got_here) + ")")


def skip_sitemap(subject, options):
    # Which years should we download? All if none is specified.
    if "year" in subject and options.get("years", "").strip() != "":
        only_years = set(options.get("years").split(","))
        if subject["year"] not in only_years:
            return True

    # Which collections should we download? All if none is specified.
    if "collection" in subject and options.get("collections", "").strip() != "":
        only_collections = set(options.get("collections").split(","))
        if subject["collection"] not in only_collections:
            return True

    # Which congresses should we download? All if none is specified.
    if "congress" in subject and options.get("congress", "").strip() != "":
        # If we're looking for congresses after a certain one.
        if options.get("congress")[0] == '>':
            if int(subject["congress"]) <= int(options.get("congress")[1:]):
                return True
        else:
            only_congress = set(options.get("congress").split(","))
            if subject["congress"] not in only_congress:
                return True

    return False


def get_sitemap_cache_files(subject):
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


def should_download_sitemap(lastmod_cache_file, current_lastmod, options):
    # Download a sitemap or just read from our cache?

    if not current_lastmod:
        # No lastmod is known for this file (it's the root of a sitemap
        # tree - this is the first web request).
        return True

    elif options.get("force", False):
        # User requests downloading everything.
        return True

    elif options.get("cached", False):
        # User requests downloading nothing.
        return False

    else:
        # Download if the lastmod from the parent sitemap doesn't agree with
        # the lastmod stored on disk.
        return current_lastmod != utils.read(lastmod_cache_file)


def format_item_for_listing(item):
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


# Downloading Packages


def mirror_package(sitemap, package_name, lastmod, content_detail_url, options):
    """Create a local mirror of a FDSys package."""

    # Return a list of files we downloaded.
    results = []

    if not options.get("granules", False):
        # Most packages are just a package. This is the usual case.
        results = mirror_package_or_granule(sitemap, package_name, None, lastmod, options)

    else:
        # In some collections, like STATUTE, each document has subparts which are not
        # described in the sitemap. Load the main HTML page and scrape for the sub-files.
        # In the STATUTE collection, the MODS information in granules is redundant with
        # information in the top-level package MODS file. But the only way to get granule-
        # level PDFs is to go through the granules.
        content_index = utils.download(content_detail_url,
                                       "fdsys/package/%s/%s/%s.html" % (sitemap["year"], sitemap["collection"], package_name),
                                       utils.merge(options, {
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
                results = mirror_package_or_granule(sitemap, package_name, granule_name, lastmod, options)

    return results


def mirror_package_or_granule(sitemap, package_name, granule_name, lastmod, options):
    # Return a list of files we downloaded.
    results = []

    # Where should we store the file? Each collection has a different
    # file system layout (for BILLS, we put bill text along where the
    # bills scraper puts bills).
    path = get_output_path(sitemap, package_name, granule_name, options)
    if not path:
        return  # should skip

    # Get the lastmod times of the files previously saved for this package.
    file_lastmod_changed = False
    file_lastmod = { }
    lastmod_cache_file = path + "/lastmod.json"
    if os.path.exists(lastmod_cache_file):
        file_lastmod = json.load(open(lastmod_cache_file))

    # Try downloading files for each file type.
    targets = get_package_files(package_name, granule_name)
    for file_type, (file_url, relpath) in targets.items():
        # Does the user want to save this file type? If the user didn't
        # specify --store, save everything. Otherwise only save the
        # file types asked for.
        if options.get("store", "") and file_type not in options["store"].split(","):
            continue

        # Do we already have this file updated? The file_lastmod JSON
        # stores the lastmod from the sitemap at the time we downloaded
        # the individual file.
        if file_lastmod.get(file_type) == lastmod:
            if not options.get("force", False):
                continue

        # With --cached, skip if the file is already downloaded.
        file_path = os.path.join(path, relpath)
        if os.path.exists(file_path) and options.get("cached", False):
            continue

        # Download.
        logging.warn("Downloading: " + file_path)
        data = utils.download(file_url, file_path, utils.merge(options, {
            'binary': True,
            'force': True, # decision to cache was made above
            'to_cache': False,
            'return_status_code_on_error': True,
            'needs_content': (file_type == "text" and file_path.endswith(".html")),
        }))
        results.append(file_path)

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
        file_lastmod_changed = True

        # The "text" format files are put in an HTML container. Unwrap it into a .txt file.
        # TODO: Encoding? The HTTP content-type header says UTF-8, but do we trust it?
        #       html.fromstring does auto-detection.
        if file_type == "text" and file_path.endswith(".html"):
            file_path_text = file_path[0:-4] + "txt"
            logging.info("Unwrapping HTML to: " + file_path_text)
            with open(file_path_text, "w") as f:
                f.write(unwrap_text_in_html(data))

        if sitemap["collection"] == "BILLS" and file_type == "mods":
            # When we download bill files, also create the text-versions/data.json file
            # which extracts commonly used components of the MODS XML, whenever we update
            # that MODS file.
            extract_bill_version_metadata(package_name, path)

    # Write the current last modified date back to disk so we know the next time whether
    # we need to fetch the files for this sitemap item. Assuming we fetched anything.
    # If nothing new was fetched, then there is no reason to update the file.
    if file_lastmod and file_lastmod_changed:
        utils.write(json.dumps(file_lastmod), lastmod_cache_file)

    return results


def get_bill_id_for_package(package_name, with_version=True, restrict_to_congress=None):
    m = re.match(r"BILL(?:S|STATUS)-(\d+)([a-z]+)(\d+)([a-z][a-z0-9]*|)$", package_name)
    if not m:
        raise Exception("Unmatched bill document package name: " + package_name)
    congress, bill_type, bill_number, version_code = m.groups()

    if restrict_to_congress and int(congress) != int(restrict_to_congress):
        return None

    if not with_version:
        return ("%s%s-%s" % (bill_type, bill_number, congress), version_code)
    else:
        return "%s%s-%s-%s" % (bill_type, bill_number, congress, version_code)


def get_output_path(sitemap, package_name, granule_name, options):
    # Where to store the document files?

    # The path will depend a bit on the collection.
    if sitemap["collection"] == "BILLS":
        # Store with the other bill data.
        bill_and_ver = get_bill_id_for_package(package_name, with_version=False, restrict_to_congress=options.get("congress"))
        if not bill_and_ver:
            return None  # congress number does not match options["congress"]
        from bills import output_for_bill
        bill_id, version_code = bill_and_ver
        return output_for_bill(bill_id, "text-versions/" + version_code, is_data_dot=False)
    
    else:
        # Store in fdsys/COLLECTION/YEAR/PKGNAME[/GRANULE_NAME].
        path = "%s/fdsys/%s/%s/%s" % (utils.data_dir(), sitemap["collection"], sitemap["year"], package_name)
        if granule_name:
            path += "/" + granule_name
        return path


def get_package_files(package_name, granule_name):
    # What URL are the package files at? Return a tuple of the remote
    # URL and a relative filename for storing it locally.

    baseurl = "https://www.gpo.gov/fdsys/pkg/%s" % package_name

    if not granule_name:
        # For regular packages, the URL layout is...
        baseurl2 = baseurl
        file_name = package_name
    else:
        # For granules, the URL layout is...
        baseurl2 = "https://www.gpo.gov/fdsys/granule/%s/%s" % (package_name, granule_name)
        file_name = granule_name

    ret = {
       'mods': (baseurl2 + "/mods.xml",                  "mods.xml"),
        'pdf': (baseurl + "/pdf/" + file_name + ".pdf",  "document.pdf"),
        'xml': (baseurl + "/xml/" + file_name + ".xml",  "document.xml"),
       'text': (baseurl + "/html/" + file_name + ".htm", "document.html"), # text wrapped in HTML!
     'premis': (baseurl + "/premis.xml",                 "premis.xml")
    }

    if granule_name:
        # Granules don't have PREMIS files.
        del ret['premis']

    if package_name.startswith("STATUTE-"):
        # Statutes at Large don't have XML.
        del ret['xml']

    return ret


def unwrap_text_in_html(data):
    text_content = unicode(html.fromstring(data).text_content())
    return text_content.encode("utf8")


# Downloading bulk data files


def mirror_bulkdata_file(sitemap, url, item_path, lastmod, options):
    # Return a list of files we downloaded.
    results = []

    # Where should we store the file?
    path = "%s/fdsys/%s/%s" % (utils.data_dir(), sitemap["collection"], item_path)

    # For BILLSTATUS, store this along with where we store the rest of bill
    # status data.
    if sitemap["collection"] == "BILLSTATUS":
        from bills import output_for_bill
        bill_id, version_code = get_bill_id_for_package(os.path.splitext(os.path.basename(item_path))[0], with_version=False)
        path = output_for_bill(bill_id, FDSYS_BILLSTATUS_FILENAME, is_data_dot=False)

    # Where should we store the lastmod found in the sitemap so that
    # we can tell later if the file has changed?
    lastmod_cache_file = os.path.splitext(path)[0] + "-lastmod.txt"

    # Do we already have this file up to date?
    if os.path.exists(lastmod_cache_file) and not options.get("force", False):
        if lastmod == utils.read(lastmod_cache_file):
            return

    # With --cached, skip if the file is already downloaded.
    if os.path.exists(path) and options.get("cached", False):
        return

    # Download.
    logging.warn("Downloading: " + path)
    data = utils.download(url, path, utils.merge(options, {
        'binary': True,
        'force': True, # decision to cache was made above
        'to_cache': False,
    }))
    results.append(path)

    if not data:
        # Something failed.
        return

    # Write the current last modified date back to disk so we know the next time whether
    # we need to fetch the file again.
    utils.write(lastmod, lastmod_cache_file)

    return results


def extract_bill_version_metadata(package_name, text_path):
    bill_version_id = get_bill_id_for_package(package_name)

    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)

    bill_version = {
        'bill_version_id': bill_version_id,
        'version_code': version_code,
        'urls': {},
    }

    mods_ns = {"mods": "http://www.loc.gov/mods/v3"}
    doc = etree.parse(os.path.join(text_path, "mods.xml"))
    locations = doc.xpath("//mods:location/mods:url", namespaces=mods_ns)

    for location in locations:
        label = location.attrib['displayLabel']
        if "HTML" in label:
            format = "html"
        elif "PDF" in label:
            format = "pdf"
        elif "XML" in label:
            format = "xml"
        else:
            format = "unknown"
        bill_version["urls"][format] = location.text

    bill_version["issued_on"] = doc.xpath("string(//mods:dateIssued)", namespaces=mods_ns)

    utils.write(
        json.dumps(bill_version, sort_keys=True, indent=2, default=utils.format_datetime),
        output_for_bill_version(bill_version_id)
    )

def output_for_bill_version(bill_version_id):
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
    return "%s/%s/bills/%s/%s%s/text-versions/%s/data.json" % (utils.data_dir(), congress, bill_type, bill_type, number, version_code)
