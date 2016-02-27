# Cache FDSys sitemaps to get a list of available documents.
#
# ./run fdsys [--year=XXXX] [--congress=XXX]
# Caches the complete FDSys sitemap. Uses lastmod times in
# sitemaps to only download new files. Use --year to only
# update a particular year, and --congress to only update
# a particular Congress (with the BILLS collection).
#
# ./run fdsys --list-collections
# Dumps a list of the names of GPO's collections.
#
# ./run fdsys --collections=BILLS,STATUTE
# Only fetch sitemaps for these collections.
#
# ./run fdsys --cached|--force
# Always/never use the cache.
#
# ./run fdsys ... --store mods,pdf,text,xml,premis,zip [--granules]
# When downloading, also locally mirror the MODS, PDF, text, XML,
# PREMIS, or the whole package ZIP file associated with each package.
# Update only changed files as the sitemap indicates.
# Pass --granules in addition to locally cache only granule files
# (e.g. the individual statute files w/in a volume).

from lxml import etree, html
import glob
import json
import re
import logging
import os.path
import zipfile
import utils
from bill_info import output_for_bill

# for xpath
ns = {"x": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def run(options):
    # GPO FDSys organizes its sitemaps by publication year (the date of
    # original print publication) and then by colletion (bills, statutes,
    # etc.).

    # Which collections should we download? All if none is specified.
    fetch_collections = None
    if options.get("collections", "").strip() != "":
        fetch_collections = set(options.get("collections").split(","))

    # Update our cache of the complete FDSys sitemap.
    update_sitemap_cache(fetch_collections, options)
    if options.get("list-collections", False):
        return

    # Locally store MODS, PDF, etc.
    if "store" in options:
        mirror_packages(fetch_collections, options)


def update_sitemap_cache(fetch_collections, options):
    """Updates a local cache of the complete FDSys sitemap tree.
    Pass fetch_collections as None, or to restrict the update to
    particular FDSys collections a set of collection names. Only
    downloads changed sitemap files."""

    seen_collections = dict()  # maps collection name to a set() of sitemap years in which the collection is present

    # Load the root sitemap.
    master_sitemap = get_sitemap(None, None, None, options)
    if master_sitemap.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex":
        raise Exception("Mismatched sitemap type at the root sitemap.")

    # Process the year-by-year sitemaps.
    for year_node in master_sitemap.xpath("x:sitemap", namespaces=ns):
        # Get year and lastmod date.
        url = str(year_node.xpath("string(x:loc)", namespaces=ns))
        lastmod = str(year_node.xpath("string(x:lastmod)", namespaces=ns))
        m = re.match(r"https://www.gpo.gov/smap/fdsys/sitemap_(\d+)/sitemap_(\d+).xml", url)
        if not m or m.group(1) != m.group(2):
            raise ValueError("Unmatched sitemap URL: %s" % url)
        year = m.group(1)

        # Should we process this year's sitemaps?
        if options.get("congress", None) and int(year) not in utils.get_congress_years(int(options.get("congress"))):
            continue
        if options.get("year", None) and int(year) != int(options.get("year")):
            continue

        # Get the sitemap.
        year_sitemap = get_sitemap(year, None, lastmod, options)
        if year_sitemap.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex":
            raise Exception("Mismatched sitemap type in %s sitemap." % year)

        # Process the collection sitemaps.
        for collection_node in year_sitemap.xpath("x:sitemap", namespaces=ns):
            # Get collection and lastmod date.
            url = str(collection_node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(collection_node.xpath("string(x:lastmod)", namespaces=ns))
            m = re.match(r"https://www.gpo.gov/smap/fdsys/sitemap_(\d+)/(\d+)_(.*)_sitemap.xml", url)
            if not m or m.group(1) != year or m.group(2) != year:
                raise ValueError("Unmatched sitemap URL: %s" % url)
            collection = m.group(3)

            # To help the user find a collection name, record this collection but don't download it.
            if options.get("list-collections", False):
                seen_collections.setdefault(collection, set()).add(int(year))
                continue

            # Should we download the sitemap?
            if fetch_collections and collection not in fetch_collections:
                continue

            # Get the sitemap.
            collection_sitemap = get_sitemap(year, collection, lastmod, options)
            if collection_sitemap.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
                raise Exception("Mismatched sitemap type in %s_%s sitemap." % (year, collection))

    if options.get("list-collections", False):
        max_collection_name_len = max(len(n) for n in seen_collections)

        def make_nice_year_range(years):
            ranges = []
            for y in sorted(years):
                if len(ranges) > 0 and ranges[-1][1] == y - 1:
                    # extend the previous range
                    ranges[-1][1] = y
                else:
                    # append a new range
                    ranges.append([y, y])
            ranges = [(("%d" % r[0]) if r[0] == r[1] else "%d-%d" % tuple(r)) for r in ranges]
            return ", ".join(ranges)

        for collection in sorted(seen_collections):
            print collection.ljust(max_collection_name_len), " ", make_nice_year_range(seen_collections[collection])


def get_sitemap(year, collection, lastmod, options):
    """Gets a single sitemap, downloading it if the sitemap has changed.

    Downloads the root sitemap (year==None, collection==None), or
    the sitemap for a year (collection==None), or the sitemap for
    a particular year and collection. Pass lastmod which is the current
    modification time of the file according to its parent sitemap, which
    is how it knows to return a cached copy.

    Returns the sitemap parsed into a DOM.
    """

    # Construct the URL and the path to where to cache the file on disk.
    if year == None:
        url = "https://www.gpo.gov/smap/fdsys/sitemap.xml"
        path = "fdsys/sitemap/sitemap.xml"
    elif collection == None:
        url = "https://www.gpo.gov/smap/fdsys/sitemap_%s/sitemap_%s.xml" % (year, year)
        path = "fdsys/sitemap/%s/sitemap.xml" % year
    else:
        url = "https://www.gpo.gov/smap/fdsys/sitemap_%s/%s_%s_sitemap.xml" % (year, year, collection)
        path = "fdsys/sitemap/%s/%s.xml" % (year, collection)

    # Should we re-download the file?
    lastmod_cache_file = utils.cache_dir() + "/" + path.replace(".xml", "-lastmod.txt")
    if options.get("cached", False):
        # If --cached is used, don't hit the network.
        force = False
    elif not lastmod:
        # No *current* lastmod date is known for this file (because it is the master
        # sitemap file, probably), so always download.
        force = True
    else:
        # If the file is out of date or --force is used, download the file.
        cache_lastmod = utils.read(lastmod_cache_file)
        force = (lastmod != cache_lastmod) or options.get("force", False)

    if force:
        logging.warn("Downloading: %s" % url)

    body = utils.download(url, path, utils.merge(options, {
        'force': force,
        'binary': True
    }))

    if not body:
        raise Exception("Failed to download %s" % url)

    # Write the current last modified date to disk so we know the next time whether
    # we need to fetch the file.
    if lastmod and not options.get("cached", False):
        utils.write(lastmod, lastmod_cache_file)

    try:
        return etree.fromstring(body)
    except etree.XMLSyntaxError as e:
        raise Exception("XML syntax error in %s: %s" % (url, str(e)))


# uses get_sitemap, but returns a list of tuples of date and url
def entries_from_collection(year, collection, lastmod, options):
    if (not collection) or (not year):
        raise Exception("This method requires a specific year and collection.")

    sitemap = get_sitemap(year, collection, lastmod, options)

    entries = []

    for entry_node in sitemap.xpath("x:url", namespaces=ns):
        url = str(entry_node.xpath("string(x:loc)", namespaces=ns))
        lastmod = str(entry_node.xpath("string(x:lastmod)", namespaces=ns))
        entries.append((url, lastmod))

    return entries


def mirror_packages(fetch_collections, options):
    """Create a local mirror of FDSys document files. Only downloads
    changed files, according to the sitemap. Run update_sitemap_cache first.

    Pass fetch_collections as None, or to restrict the update to
    particular FDSys collections a set of collection names.

    Set options["store"] to a comma-separated list of file types (pdf,
    mods, text, xml, zip).
    """

    # For determining whether we need to process a sitemap file again on a later
    # run, we need to make a key out of the command line arguments that affect
    # which files we are downloading.
    cache_options_key = repr(tuple(sorted(kv for kv in options.items() if kv[0] in ("store", "year", "congress", "granules", "cached"))))

    file_types = options["store"].split(",")

    # Process each FDSys sitemap...
    for sitemap in sorted(glob.glob(utils.cache_dir() + "/fdsys/sitemap/*/*.xml")):
        # Should we process this file?
        year, collection = re.search(r"/(\d+)/([^/]+).xml$", sitemap).groups()
        if "year" in options and year != options["year"]:
            continue
        if "congress" in options and int(year) not in utils.get_congress_years(int(options["congress"])):
            continue
        if fetch_collections and collection not in fetch_collections:
            continue

        # Has this sitemap changed since the last successful mirror?
        #
        # The sitemap's last modification time is stored in ...-lastmod.txt,
        # which comes from the sitemap's parent sitemap's lastmod listing for
        # the file.
        #
        # Compare that to the lastmod value of when we last did a successful mirror.
        # This function can be run to fetch different sets of files, so get the
        # lastmod value corresponding to the current run arguments.
        sitemap_store_state_file = re.sub(r"\.xml$", "-store-state.json", sitemap)
        sitemap_last_mod = open(re.sub(r"\.xml$", "-lastmod.txt", sitemap)).read()
        if os.path.exists(sitemap_store_state_file):
            sitemap_store_state = json.load(open(sitemap_store_state_file))
            if sitemap_store_state.get(cache_options_key) == sitemap_last_mod:
                # sitemap hasn't changed since the last time
                continue

        logging.info("scanning " + sitemap + "...")

        # Load the sitemap for this year & collection, and loop through each document.
        for package_name, lastmod in get_sitemap_entries(sitemap):
            # Add this package to the download list.
            file_list = []

            if not options.get("granules", False):
                # Doing top-level package files (granule==None).
                file_list.append(None)

            else:
                # In some collections, like STATUTE, each document has subparts which are not
                # described in the sitemap. Load the main HTML page and scrape for the sub-files.
                # In the STATUTE collection, the MODS information in granules is redundant with
                # information in the top-level package MODS file. But the only way to get granule-
                # level PDFs is to go through the granules.
                content_detail_url = "https://www.gpo.gov/fdsys/pkg/%s/content-detail.html" % package_name
                content_index = utils.download(content_detail_url,
                                               "fdsys/package/%s/%s/%s.html" % (year, collection, package_name),
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
                        file_list.append(granule_name)

            # Download the files of the desired types.
            for granule_name in file_list:
                mirror_package(year, collection, package_name, lastmod, granule_name, file_types, options)

        # If we got this far, we successfully downloaded all of the files in this year/collection.
        # To speed up future updates, save the lastmod time of this sitemap in a file indicating
        # what we downloaded. The store-state file contains a JSON mapping of command line options
        # to the most recent lastmod value for this sitemap.
        sitemap_store_state = {}
        if os.path.exists(sitemap_store_state_file):
            sitemap_store_state = json.load(open(sitemap_store_state_file))
        sitemap_store_state[cache_options_key] = sitemap_last_mod
        json.dump(sitemap_store_state, open(sitemap_store_state_file, "w"))


def get_sitemap_entries(sitemap_filename):
    # Load the XML file.
    dom = etree.parse(sitemap_filename).getroot()
    if dom.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
        raise Exception("Mismatched sitemap type.")

    # Loop through entries.
    for file_node in dom.xpath("x:url", namespaces=ns):
        # Get URL and last modified timestamp.
        url = str(file_node.xpath("string(x:loc)", namespaces=ns))
        lastmod = str(file_node.xpath("string(x:lastmod)", namespaces=ns))
        if not url.endswith("/content-detail.html"):
            raise Exception("Unrecognized file pattern.")

        # Get the package name.
        m = re.match("https://www.gpo.gov/fdsys/pkg/(.*)/content-detail.html", url)
        if not m:
            raise Exception("Unmatched document URL")
        package_name = m.group(1)

        yield package_name, lastmod


def mirror_package(year, collection, package_name, lastmod, granule_name, file_types, options):
    # Where should we store the file?
    path = get_output_path(year, collection, package_name, granule_name, options)
    if not path:
        return  # should skip

    # Delete legacy cache file.
    lastmod_cache_file = path + "/lastmod.txt"
    if os.path.exists(lastmod_cache_file): os.unlink(lastmod_cache_file)

    # Get the lastmod times of the files previously saved for this package.
    stored_lastmod_by_type = { }
    lastmod_cache_file = path + "/lastmod.json"
    if os.path.exists(lastmod_cache_file):
        stored_lastmod_by_type = json.load(open(lastmod_cache_file))

    # Try downloading files for each file type.
    targets = get_package_files(package_name, granule_name, path)
    updated_file_types = set()
    for file_type in file_types:
        if file_type not in targets:
            raise Exception("Invalid file type: %s" % file_type)

        # For BILLS, XML was not available until the 108th Congress, though even after that
        # it was spotty until the 111th or so Congress.
        if file_type == "xml" and collection == "BILLS" and int(package_name[6:9]) < 108:
            continue

        f_url, f_path = targets[file_type]

        if os.path.exists(f_path):
            # We already have the current file. Should we skip?
            # Skip if --cache is used.
            if options.get("cached", False):
                continue

            # Skip if the lastmod in the (remote) sitemap matches the lastmod
            # stored for this file on disk, and --force is not used.
            if lastmod == stored_lastmod_by_type.get(file_type) and not options.get("force", False):
                continue

        # Download.
        logging.warn("Downloading: " + f_path)
        data = utils.download(f_url, f_path, utils.merge(options, {
            'binary': True,
            'force': True, # decision to cache was made above
            'to_cache': False,
            'needs_content': file_type == "text" and f_path.endswith(".html"),
        }))

        # Download failed?
        if not data:
            if file_type in ("pdf", "zip"):
                # expected to be present for all packages
                raise Exception("Failed to download %s %s" % (package_name, file_type))
            elif collection == "BILLS" and file_type in ("text", "mods"):
                # expected to be present for bills
                raise Exception("Failed to download %s %s" % (package_name, file_type))
            else:
                # not all packages have all file types, but assume this is OK
                logging.error("file not found: " + f_url)
                continue

        # Update the lastmod of the downloaded file.
        stored_lastmod_by_type[file_type] = lastmod

        # Note that we got the file.
        updated_file_types.add(file_type)

        if file_type == "text" and f_path.endswith(".html"):
            # The "text" format files are put in an HTML container. Unwrap it into a .txt file.
            # TODO: Encoding? The HTTP content-type header says UTF-8, but do we trust it?
            #       html.fromstring does auto-detection.
            with open(f_path[0:-4] + "txt", "w") as f:
                f.write(unwrap_text_in_html(data))

        if file_type == "zip":
            # This is the entire package in a ZIP file. Extract the contents of this file
            # to the appropriate paths.
            with zipfile.ZipFile(f_path) as zf:
                for z2 in zf.namelist():
                    if not z2.startswith(package_name + "/"):
                        raise ValueError("Unmatched file name in package ZIP: " + z2)
                    z2 = z2[len(package_name) + 1:]  # strip off leading package name

                    if z2 in ("mods.xml", "premis.xml", "dip.xml"):
                        # Extract this file to a file of the same name.
                        z3 = path + "/" + z2
                    elif z2 == "pdf/" + package_name + ".pdf":
                        # Extract this file to "document.pdf".
                        z3 = path + "/document.pdf"
                    elif z2 == "html/" + package_name + ".htm":
                        # Extract this file and unwrap text to "document.txt".
                        z3 = path + "/document.txt"
                    else:
                        raise ValueError("Unmatched file name in package ZIP: " + z2)

                    with zf.open(package_name + "/" + z2) as zff:
                        with open(z3, "w") as output_file:
                            data = zff.read()
                            if z3 == path + "/document.txt":
                                data = unwrap_text_in_html(data)
                            output_file.write(data)

    if collection == "BILLS" and "mods" in updated_file_types:
        # When we download bill files, also create the text-versions/data.json file
        # which extracts commonly used components of the MODS XML.
        from bill_versions import write_bill_version_metadata
        write_bill_version_metadata(get_bill_id_for_package(package_name, with_version=True))

    # Write the current last modified date to disk so we know the next time whether
    # we need to fetch the files for this sitemap item.
    if not options.get("cached", False):
        utils.write(json.dumps(stored_lastmod_by_type), lastmod_cache_file)


def get_bill_id_for_package(package_name, with_version=True, restrict_to_congress=None):
    m = re.match(r"BILLS-(\d+)([a-z]+)(\d+)(\D.*)", package_name)
    if not m:
        raise Exception("Unmatched bill document package name: " + package_name)
    congress, bill_type, bill_number, version_code = m.groups()

    if restrict_to_congress and int(congress) != int(restrict_to_congress):
        return None

    if not with_version:
        return ("%s%s-%s" % (bill_type, bill_number, congress), version_code)
    else:
        return "%s%s-%s-%s" % (bill_type, bill_number, congress, version_code)


def get_output_path(year, collection, package_name, granule_name, options):
    # Where to store the document files?
    # The path will depend a bit on the collection.
    if collection == "BILLS":
        # Store with the other bill data.
        bill_and_ver = get_bill_id_for_package(package_name, with_version=False, restrict_to_congress=options.get("congress"))
        if not bill_and_ver:
            return None  # congress number does not match options["congress"]
        bill_id, version_code = bill_and_ver
        return output_for_bill(bill_id, "text-versions/" + version_code, is_data_dot=False)
    else:
        # Store in fdsys/COLLECTION/YEAR/PKGNAME[/GRANULE_NAME].
        path = "%s/fdsys/%s/%s/%s" % (utils.data_dir(), collection, year, package_name)
        if granule_name:
            path += "/" + granule_name
        return path


def get_package_files(package_name, granule_name, path):
    baseurl = "https://www.gpo.gov/fdsys/pkg/%s" % package_name
    baseurl2 = baseurl

    if not granule_name:
        file_name = package_name
    else:
        file_name = granule_name
        baseurl2 = "https://www.gpo.gov/fdsys/granule/%s/%s" % (package_name, granule_name)

    ret = {
        # map file type names used on the command line to a tuple of the URL path on FDSys and the relative path on disk
        'zip': (baseurl2 + ".zip", path + "/document.zip"),
        'mods': (baseurl2 + "/mods.xml", path + "/mods.xml"),
        'pdf': (baseurl + "/pdf/" + file_name + ".pdf", path + "/document.pdf"),
        'xml': (baseurl + "/xml/" + file_name + ".xml", path + "/document.xml"),
        'text': (baseurl + "/html/" + file_name + ".htm", path + "/document.html"),  # text wrapped in HTML
    }
    if not granule_name:
        # granules don't have PREMIS files?
        ret['premis'] = (baseurl + "/premis.xml", path + "/premis.xml")

    return ret


def unwrap_text_in_html(data):
    text_content = unicode(html.fromstring(data).text_content())
    return text_content.encode("utf8")
