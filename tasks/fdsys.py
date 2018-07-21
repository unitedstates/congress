# Downloads documents from GPO's GovInfo.gov site, using sitemaps
# to efficiently determine what needs to be updated. See
# https://www.govinfo.gov/sitemaps for a list of collections.
# This service was formerly called "Fdsys."
#
# ./run fdsys --collections=BILLS,STATUTE,...
# Download bill text (from the BILLS collection; there's also a bulk
# data BILLS collection but it has less in it), the Statues at Large,
# and other documents from GovInfo.gov's non-bulk-data collections.
#
# ./run fdsys --bulkdata=BILLSTATUS,FR,...
# Download bill status, the Federal Register, and other documents
# from GovInfo.gov's bulk data collections. (The BILLS collection occurs
# both as a regular collection (bill text in multiple formats) and as
# a bulk data collection (just XML starting recently). Use --bulkdata=BILLS
# to get the bulk data collection.)
#
#   Options:
#
#   --years=2001[,2002,2004]
#   Comma-separated list of years to download from. Applies to collections
#   that are divided by year.
#
#   --congress=113[,114]
#   Comma-separated list of congresses to download from. Applies to bulk
#   data collections like BILLSTATUS that are grouped by Congress + Bill Type.
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

import rtyaml


# globals
GOVINFO_BASE_URL = "https://www.govinfo.gov/"
COLLECTION_BASE_URL = GOVINFO_BASE_URL + "app/details/"
BULKDATA_BASE_URL = GOVINFO_BASE_URL + "bulkdata/"
COLLECTION_SITEMAPINDEX_PATTERN = GOVINFO_BASE_URL + "sitemap/{collection}_sitemap_index.xml"
BULKDATA_SITEMAPINDEX_PATTERN = GOVINFO_BASE_URL + "sitemap/bulkdata/{collection}/sitemapindex.xml"
FDSYS_BILLSTATUS_FILENAME = "fdsys_billstatus.xml"

# for xpath
ns = {"x": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# Main entry point

def run(options):
    # Process sitemaps.
    for collection in sorted(options.get("collections", "").split(",")):
        if collection != "":
            update_sitemap(COLLECTION_SITEMAPINDEX_PATTERN.format(collection=collection), None, [], options)
    for collection in sorted(options.get("bulkdata", "").split(",")):
        if collection != "":
            update_sitemap(BULKDATA_SITEMAPINDEX_PATTERN.format(collection=collection), None, [], options)

def update_sitemap(url, current_lastmod, how_we_got_here, options):
    """Updates the local cache of a sitemap file."""

    # Skip if the year or congress flags are set and this sitemap is
    # not for that year or Congress.
    if should_skip_sitemap(url, options):
        return []

    # Return a list of files we downloaded.
    results = []

    # For debugging, remember what URLs we are stepping through.
    how_we_got_here = how_we_got_here + [url]

    # Get the file paths to cache:
    # * the sitemap XML for future runs
    # * its <lastmod> date (which comes from the parent sitemap) so we know if we need to re-download it now
    # * the <lastmod> dates of the packages listed in this sitemap so we know if we need to re-download any package files
    cache_file = get_sitemap_cache_file(url)
    cache_file = os.path.join("fdsys/sitemap", cache_file, "sitemap.xml")
    lastmod_cache_file = cache_file.replace(".xml", "-lastmod.yaml")
    lastmod_cache_file = os.path.join(utils.cache_dir(), lastmod_cache_file)
    if not os.path.exists(lastmod_cache_file):
        lastmod_cache = { }
    else:
        with open(lastmod_cache_file) as f:
            lastmod_cache = rtyaml.load(f)

    # Download anew if the current_lastmod doesn't match the stored lastmod
    # in our cache, and if --cache is not specified. Or if --force is given.
    # If we're not downloading it, load it from disk because we still have
    # to process each sitemap to ensure we've downloaded all of the package
    # files the user wants.
    download = should_download_sitemap(lastmod_cache.get("lastmod"), current_lastmod, options)

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

    # If we downloaded a new file, update the lastmod for our cache.
    if download and current_lastmod:
        lastmod_cache["lastmod"] = current_lastmod

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
            sitemap_results = update_sitemap(url, lastmod, how_we_got_here, options)
            if sitemap_results is not None:
                results = results + sitemap_results

    elif sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":

        # This is a regular sitemap with content items listed.

        # Process the items.
        for node in sitemap.xpath("x:url", namespaces=ns):
            url = str(node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(node.xpath("string(x:lastmod)", namespaces=ns))

            m = re.match(COLLECTION_BASE_URL + r"([^-]+)-(.*)", url)
            if m:
                collection = m.group(1)
                package_name = m.group(2)
                if options.get("filter") and not re.search(options["filter"], package_name): continue
                mirror_results = mirror_package(collection, package_name, lastmod, lastmod_cache.setdefault("packages", {}), url, options)
                if mirror_results is not None and len(mirror_results) > 0:
                    results = results + mirror_results

            else:
                # This is a bulk data item. Extract components of the URL.
                m = re.match(BULKDATA_BASE_URL + r"([^/]+)/(.*)", url)
                if not m:
                    raise Exception("Unmatched bulk data file URL (%s) at %s." % (url, "->".join(how_we_got_here)))
                collection = m.group(1)
                item_path = m.group(2)
                if options.get("filter") and not re.search(options["filter"], item_path): continue
                mirror_results = mirror_bulkdata_file(collection, url, item_path, lastmod, options)
                if mirror_results is not None and len(mirror_results) > 0:
                    results = results + mirror_results

    else:
        raise Exception("Unknown sitemap type (%s) at the root sitemap of %s." % (sitemap.tag, url))

    # Write the updated last modified dates to disk so we know the next time whether
    # we need to fetch the files. If we didn't download anything, no need to write an
    # empty file.
    if lastmod_cache:
        with open(lastmod_cache_file, "w") as f:
            rtyaml.dump(lastmod_cache, f)

    return results

def should_skip_sitemap(url, options):
    # Don't skip sitemap indexes.
    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/(\w+)_sitemap_index.xml", url)
    if m:
        return False
    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/bulkdata/(\w+)/sitemapindex.xml", url)
    if m:
        return False

    year_filter = options.get("years", "").strip()
    congress_filter = options.get("congress", "").strip()

    # Regular collections are grouped by publication year.
    # Which years should we download? All if none is specified.
    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/(\w+)_(\d+)_sitemap.xml", url)
    if m:
        year = m.group(2)
        if year_filter != "" and year not in year_filter.split(","):
            return True

    # Bulk data collections are grouped into subdirectories that can
    # represent years (as in the FR collection) or other types of groupings
    # like Congress + Bill Type for the BILLSTATUS collection.
    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/bulkdata/(\w+)/(\d+)(.*)/sitemap.xml", url)
    if m:
        numeric_grouping = m.group(2)
        if year_filter != "" and numeric_grouping not in year_filter.split(","):
            return True
        if congress_filter != "" and numeric_grouping not in congress_filter.split(","):
            return True

    return False

def get_sitemap_cache_file(url):
    # Where should we store the local cache of the sitemap XML and a file
    # that stores its <lastmod> date for when we last downloaded it? Returns
    # a path relative to the cache root.

    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/(\w+)_sitemap_index.xml", url)
    if m:
        return m.group(1)

    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/(\w+)_(\d+)_sitemap.xml", url)
    if m:
        return m.group(1) + "/" + m.group(2)

    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/bulkdata/(\w+)/sitemapindex.xml", url)
    if m:
        return m.group(1) + "-bulkdata"

    m = re.match(re.escape(GOVINFO_BASE_URL) + r"sitemap/bulkdata/(\w+)/(.+)/sitemap.xml", url)
    if m:
        return m.group(1) + "-bulkdata/" + m.group(2)

    raise ValueError(url)

def should_download_sitemap(lastmod_cache, current_lastmod, options):
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
        return current_lastmod != lastmod_cache


# Downloading Packages


def mirror_package(collection, package_name, lastmod, lastmod_cache, content_detail_url, options):
    """Create a local mirror of a FDSys package."""

    # Return a list of files we downloaded.
    results = []

    if not options.get("granules", False):
        # Most packages are just a package. This is the usual case.
        results = mirror_package_or_granule(collection, package_name, None, lastmod, lastmod_cache, options)

    else:
        # In some collections, like STATUTE, each document has subparts which are not
        # described in the sitemap.
        #
        # In the STATUTE collection, the MODS information in granules is redundant with
        # information in the top-level package MODS file. But the only way to get granule-
        # level --- i.e. individual law --- PDFs is to go through the granules.
        #
        # On GovInfo.gov, the granules are returned in an AJAX call that fetches the
        # "document in context" table, which fortuitously returns JSON.
        granules = utils.download(GOVINFO_BASE_URL + "wssearch/documentsInContext/%s-%s" % (collection, package_name),
                                       "fdsys/package/%s/%s.json" % (collection, package_name),
                                       utils.merge(options, {  # The Content-Type response header
                                           'binary': True,     # indicates it's UTF-8 encoded, but
                                       }))                     # binary: False means it's HTML and
                                                               # HTML entities are replaced, which
                                                               # would be bad since this is JSON .
        if not granules:
            raise Exception("Failed to download %s" % content_detail_url)
        granules = json.loads(granules.decode("utf8")) # see above

        prefix = collection + "-" + package_name + "-"

        results = []

        def process_granule_node(node):
            if "granuleid" in node["nodeValue"]:
                if not node["nodeValue"]["granuleid"].startswith(prefix):
                    raise ValueError(node["nodeValue"]["granuleid"])
                granule_name = node["nodeValue"]["granuleid"][len(prefix):]
                results.extend(mirror_package_or_granule(collection, package_name, granule_name, lastmod, lastmod_cache, options))

            for child in node["childNodes"]:
                process_granule_node(child)

        process_granule_node(granules)

    return results


def mirror_package_or_granule(collection, package_name, granule_name, lastmod, lastmod_cache, options):
    # Return a list of files we downloaded.
    results = []

    # Where should we store the file? Each collection has a different
    # file system layout (for BILLS, we put bill text along where the
    # bills scraper puts bills).
    path = get_output_path(collection, package_name, granule_name, options)
    if not path:
        return  # should skip

    # Go to the part of the lastmod_cache for this package.
    lastmod_cache = lastmod_cache.setdefault(package_name, {})
    if granule_name: lastmod_cache = lastmod_cache.setdefault(granule_name, {})
    lastmod_cache = lastmod_cache.setdefault("files", {})

    # Migrate old cache storage:
    # Get the lastmod times of the files previously saved for this package.
    lastmod_cache_file = path + "/lastmod.json"
    if not lastmod_cache and os.path.exists(lastmod_cache_file):
        lastmod_cache.update(json.load(open(lastmod_cache_file)))

    # Try downloading files for each file type.
    targets = get_package_files(collection, package_name, granule_name)
    for file_type, (file_url, relpath) in targets.items():
        # Does the user want to save this file type? If the user didn't
        # specify --store, save everything. Otherwise only save the
        # file types asked for.
        if options.get("store", "") and file_type not in options["store"].split(","):
            continue

        # Do we already have this file updated?
        if lastmod_cache.get(file_type) == lastmod:
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
            elif collection == "BILLS" and file_type in ("text", "mods"):
                # expected to be present for bills
                raise Exception("Failed to download %s %s (404)" % (package_name, file_type))
        elif data is True:
            # Download was successful but needs_content was False so we don't have the
            # file content. Instead, True is returned. Strangely isintance(True, int) is
            # True (!!!) so we have to test for True separately from testing if we got a
            # return code integer.
            pass
        elif not data or isinstance(data, int):
            # There was some other error - skip the rest. Don't
            # update lastmod_cache!
            continue

        # Update the lastmod of the downloaded file. If the download failed,
        # because of a 404, we still update this to indicate that the file
        # definitively does not exist. We won't try fetcihng it again.
        lastmod_cache[file_type] = lastmod

        # The "text" format files are put in an HTML container. Unwrap it into a .txt file.
        # TODO: Encoding? The HTTP content-type header says UTF-8, but do we trust it?
        #       html.fromstring does auto-detection.
        if file_type == "text" and file_path.endswith(".html"):
            file_path_text = file_path[0:-4] + "txt"
            logging.info("Unwrapping HTML to: " + file_path_text)
            with open(file_path_text, "w") as f:
                f.write(unwrap_text_in_html(data))

        if collection == "BILLS" and file_type == "mods":
            # When we download bill files, also create the text-versions/data.json file
            # which extracts commonly used components of the MODS XML, whenever we update
            # that MODS file.
            extract_bill_version_metadata(package_name, path)

    return results


def get_bill_id_for_package(package_name, with_version=True, restrict_to_congress=None):
    m = re.match(r"(\d+)([a-z]+)(\d+)([a-z][a-z0-9]*|)$", package_name)
    if not m:
        raise Exception("Unmatched bill document package name: " + package_name)
    congress, bill_type, bill_number, version_code = m.groups()

    if restrict_to_congress and int(congress) != int(restrict_to_congress):
        return None

    if not with_version:
        return ("%s%s-%s" % (bill_type, bill_number, congress), version_code)
    else:
        return "%s%s-%s-%s" % (bill_type, bill_number, congress, version_code)


def get_output_path(collection, package_name, granule_name, options):
    # Where to store the document files?

    # The path will depend a bit on the collection.
    if collection == "BILLS":
        # Store with the other bill data ([congress]/bills/[billtype]/[billtype][billnumber]).
        bill_and_ver = get_bill_id_for_package(package_name, with_version=False, restrict_to_congress=options.get("congress"))
        if not bill_and_ver:
            return None  # congress number does not match options["congress"]
        from bills import output_for_bill
        bill_id, version_code = bill_and_ver
        return output_for_bill(bill_id, "text-versions/" + version_code, is_data_dot=False)

    elif collection == "CRPT":
        # Store committee reports in [congress]/crpt/[reporttype].
        m = re.match(r"(\d+)([hse]rpt)(\d+)$", package_name)
        if not m:
            raise ValueError(package_name)
        congress, report_type, report_number = m.groups()
        if options.get("congress") and congress != options.get("congress"):
            return None  # congress number does not match options["congress"]
        return "%s/%s/%s/%s/%s" % (utils.data_dir(), congress, collection.lower(), report_type, report_type + report_number)
    
    else:
        # Store in fdsys/COLLECTION/PKGNAME[/GRANULE_NAME].
        path = "%s/fdsys/%s/%s" % (utils.data_dir(), collection, package_name)
        if granule_name:
            path += "/" + granule_name
        return path


def get_package_files(collection, package_name, granule_name):
    # What URL are the package files at? Return a tuple of the remote
    # URL and a relative filename for storing it locally.

    ret = {
        'pdf': ("content/pkg/{collection}-{package_name}/pdf/{collection}-{package_name}{dash}{granule_name}.pdf",  "document.pdf"),
       'text': ("content/pkg/{collection}-{package_name}/html/{collection}-{package_name}{dash}{granule_name}.htm", "document.html"), # text wrapped in HTML!
        'xml': ("content/pkg/{collection}-{package_name}/xml/{collection}-{package_name}{dash}{granule_name}.xml",  "document.xml"),
       'mods': ("metadata/pkg/{collection}-{package_name}/mods.xml",                            "mods.xml"),
     'premis': ("metadata/pkg/{collection}-{package_name}/premis.xml",                          "premis.xml")
    }

    if granule_name:
        # Granules don't have PREMIS files.
        del ret['premis']

        # Granule metadata is stored in a different path.
        ret.update({
           'mods': ("metadata/granule/{collection}-{package_name}/{collection}-{package_name}-{granule_name}/mods.xml",                            "mods.xml"),
        })

    if package_name.startswith("STATUTE-"):
        # Statutes at Large don't have XML.
        del ret['xml']

    for key, value in ret.items():
        ret[key] = (
            GOVINFO_BASE_URL + value[0].format(
                collection=collection,
                package_name=package_name,
                dash="-" if granule_name else "",
                granule_name=granule_name if granule_name else ""),
            value[1])

    return ret


def unwrap_text_in_html(data):
    text_content = unicode(html.fromstring(data).text_content())
    return text_content.encode("utf8")


# Downloading bulk data files


def mirror_bulkdata_file(collection, url, item_path, lastmod, options):
    # Return a list of files we downloaded.
    results = []

    # Where should we store the file?
    path = "%s/fdsys/%s/%s" % (utils.data_dir(), collection, item_path)

    # For BILLSTATUS, store this along with where we store the rest of bill
    # status data.
    if collection == "BILLSTATUS":
        from bills import output_for_bill
        bill_id, version_code = get_bill_id_for_package(os.path.splitext(os.path.basename(item_path.replace("BILLSTATUS-", "")))[0], with_version=False)
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
