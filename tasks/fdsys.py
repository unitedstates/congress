# Cache FDSys sitemaps to get a list of available documents.
#
# ./run fdsys [--year=XXXX]
# Caches the complete FDSys sitemap. Uses lastmod times in
# sitemaps to only download new files. Use --year to only
# update a particular year (for testing, I guess).
#
# ./run fdsys --list-collections
# Dumps a list of the names of GPO's collections.
#
# ./run fdsys --collections=BILLS,STATUTE
# Only fetch sitemaps for these collections.
#
# ./run fdsys --cached|force
# Always/never use the cache.
#
# # ./run fdsys --collections=BILLS --congress=XXX
# Updates the sitemaps for the years of the indicated Congress
# and then outputs text-versions.json next to each bill data.json
# file from the bills scraper.
#
# ./run fdsys ... --store mods,pdf
# When downloading, also locally mirror the MODS and PDF documents
# associated with each package. Update as the sitemap indicates.
# Pass --granules to locally cache only granule files (e.g. the
# individual statute files w/in a volume).

from lxml import etree, html
import glob, json, re, logging, os.path
import utils

# for xpath
ns = { "x": "http://www.sitemaps.org/schemas/sitemap/0.9" }

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
  if options.get("list-collections", False): return
  
  # Locally store MODS, PDF, etc.
  if "store" in options:
    mirror_files(fetch_collections, options)

  # Create a JSON file listing all available bill text documents.
  # Only if --collections is omitted or specifies BILLS, and if
  # --congress is specified.
  if (not fetch_collections or "BILLS" in fetch_collections) and options.get('congress', None):
    update_bill_version_list(int(options.get('congress')))

def update_sitemap_cache(fetch_collections, options):
  """Updates a local cache of the complete FDSys sitemap tree.
  Pass fetch_collections as None, or to restrict the update to
  particular FDSys collections a set of collection names. Only
  downloads changed sitemap files."""
	
  seen_collections = set()
  
  # Load the root sitemap.
  master_sitemap = get_sitemap(None, None, None, options)
  if master_sitemap.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex": raise Exception("Mismatched sitemap type at the root sitemap.")
  
  # Process the year-by-year sitemaps.
  for year_node in master_sitemap.xpath("x:sitemap", namespaces=ns):
    # Get year and lastmod date.
    url = str(year_node.xpath("string(x:loc)", namespaces=ns))
    lastmod = str(year_node.xpath("string(x:lastmod)", namespaces=ns))
    m = re.match(r"http://www.gpo.gov/smap/fdsys/sitemap_(\d+)/sitemap_(\d+).xml", url)
    if not m or m.group(1) != m.group(2): raise ValueError("Unmatched sitemap URL: %s" % url)
    year = m.group(1)
    
    # Should we process this year's sitemaps?
    if options.get("congress", None) and int(year) not in utils.get_congress_years(int(options.get("congress"))): continue
    if options.get("year", None) and int(year) != int(options.get("year")): continue

    # Get the sitemap.
    year_sitemap = get_sitemap(year, None, lastmod, options)
    if year_sitemap.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex": raise Exception("Mismatched sitemap type in %s sitemap." % year)
    
    # Process the collection sitemaps.
    for collection_node in year_sitemap.xpath("x:sitemap", namespaces=ns):
      # Get collection and lastmod date.
      url = str(collection_node.xpath("string(x:loc)", namespaces=ns))
      lastmod = str(collection_node.xpath("string(x:lastmod)", namespaces=ns))
      m = re.match(r"http://www.gpo.gov/smap/fdsys/sitemap_(\d+)/(\d+)_(.*)_sitemap.xml", url)
      if not m or m.group(1) != year or m.group(2) != year: raise ValueError("Unmatched sitemap URL: %s" % url)
      collection = m.group(3)
      
      # To help the user find a collection name, record this collection but don't download it.
      if options.get("list-collections", False):
        seen_collections.add(collection)
        continue

      # Should we download the sitemap?
      if fetch_collections and collection not in fetch_collections:
        continue

      # Get the sitemap.
      collection_sitemap = get_sitemap(year, collection, lastmod, options)
      if collection_sitemap.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset": raise Exception("Mismatched sitemap type in %s_%s sitemap." % (year, collection))
      
  if options.get("list-collections", False):
    print "\n".join(sorted(seen_collections))
    
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
    url = "http://www.gpo.gov/smap/fdsys/sitemap.xml"
    path = "fdsys/sitemap/sitemap.xml"
  elif collection == None:
    url = "http://www.gpo.gov/smap/fdsys/sitemap_%s/sitemap_%s.xml" % (year, year)
    path = "fdsys/sitemap/%s/sitemap.xml" % year
  else:
    url = "http://www.gpo.gov/smap/fdsys/sitemap_%s/%s_%s_sitemap.xml" % (year, year, collection)
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
    'xml': True
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



def mirror_files(fetch_collections, options):
  """Create a local mirror of FDSys document files. Only downloads
  changed files, according to the sitemap. Run update_sitemap_cache first.
  
  Pass fetch_collections as None, or to restrict the update to
  particular FDSys collections a set of collection names.
  
  Set options["store"] to a comma-separated list of file types (pdf,
  mods, text, xml).
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
    if "year" in options and year != options["year"]: continue
    if "congress" in options and int(year) not in utils.get_congress_years(int(options["congress"])): continue 
    if fetch_collections and collection not in fetch_collections: continue
    
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
        # In the STATUTE collection, the MODS information in granules is redudant with
        # information in the top-level package MODS file. But the only way to get granule-
        # level PDFs is to go through the granules.
        content_detail_url = "http://www.gpo.gov/fdsys/pkg/%s/content-detail.html" % package_name
        content_index = utils.download(content_detail_url,
            "fdsys/package/%s/%s/%s.html" % (year, collection, package_name),
            utils.merge(options, {
            'xml': True, # it's not XML but this avoid unescaping HTML which fails if there are unicode characters 
          }))
        if not content_index: raise Exception("Failed to download %s" % content_detail_url)
        for link in html.fromstring(content_index).cssselect("table.page-details-data-table td.rightLinkCell a"):
          if link.text == "More":
            m = re.match("granule/(.*)/(.*)/content-detail.html", link.get("href"))
            if not m or m.group(1) != package_name: raise Exception("Unmatched granule URL %s" % link.get("href"))
            granule_name = m.group(2)
            file_list.append(granule_name)
        
      # Download the files of the desired types.
      for granule_name in file_list:
        mirror_file(year, collection, package_name, lastmod, granule_name, file_types, options)
        
    # If we got this far, we successfully downloaded all of the files in this year/collection.
    # To speed up future updates, save the lastmod time of this sitemap in a file indicating
    # what we downloaded. The store-state file contains a JSON mapping of command line options
    # to the most recent lastmod value for this sitemap.
    sitemap_store_state = { }
    if os.path.exists(sitemap_store_state_file):
      sitemap_store_state = json.load(open(sitemap_store_state_file))
    sitemap_store_state[cache_options_key] = sitemap_last_mod
    json.dump(sitemap_store_state, open(sitemap_store_state_file, "w"))

def get_sitemap_entries(sitemap_filename):
  # Load the XML file.
  dom = etree.parse(sitemap_filename).getroot()
  if dom.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset": raise Exception("Mismatched sitemap type.")
  
  # Loop through entries.
  for file_node in dom.xpath("x:url", namespaces=ns):
    # Get URL and last modified timestamp.
    url = str(file_node.xpath("string(x:loc)", namespaces=ns))
    lastmod = str(file_node.xpath("string(x:lastmod)", namespaces=ns))
    if not url.endswith("/content-detail.html"): raise Exception("Unrecognized file pattern.")
    
    # Get the package name.
    m = re.match("http://www.gpo.gov/fdsys/pkg/(.*)/content-detail.html", url)
    if not m: raise Exception("Unmatched document URL")
    package_name = m.group(1)
    
    yield package_name, lastmod

def mirror_file(year, collection, package_name, lastmod, granule_name, file_types, options):
  # Where should we store the file?
  path = get_output_path(year, collection, package_name, granule_name, options)
  if not path: return # should skip
  
  # Do we need to update this record?
  lastmod_cache_file = path + "/lastmod.txt"
  cache_lastmod = utils.read(lastmod_cache_file)
  force = ((lastmod != cache_lastmod) or options.get("force", False)) and not options.get("cached", False)
  
  # Try downloading files for each file type.
  targets = get_package_files(package_name, granule_name, path)
  for file_type in file_types:
    if file_type not in targets: raise Exception("Invalid file type: %s" % file_type)
    f_url, f_path = targets[file_type]
    
    if (not force) and os.path.exists(f_path): continue # we already have the current file
    logging.warn("Downloading: " + f_path)
    data = utils.download(f_url, f_path, utils.merge(options, {
      'xml': True, 
      'force': force, 
      'to_cache': False,
      'needs_content': file_type == "text" and f_path.endswith(".html"),
    }))
    
    if not data:
      if file_type == "pdf":
        # expected to be present for all packages
        raise Exception("Failed to download %s" % package_name)
      else:
        # not all packages have all file types, but assume this is OK
        logging.error("file not found: " + f_url)
    
    if file_type == "text" and f_path.endswith(".html"):
      # The "text" format files are put in an HTML container. Unwrap it into a .txt file.
      # TODO: Encoding? The HTTP content-type header says UTF-8, but do we trust it?
      #       html.fromstring does auto-detection.
      with open(f_path[0:-4] + "txt", "w") as f:
        text_content = unicode(html.fromstring(data).text_content())
        f.write(text_content.encode("utf8"))

  # Write the current last modified date to disk so we know the next time whether
  # we need to fetch the files for this sitemap item.
  if lastmod and not options.get("cached", False):
    utils.write(lastmod, lastmod_cache_file) 

def get_output_path(year, collection, package_name, granule_name, options):
  # Where to store the document files?
  # The path will depend a bit on the collection.
  if collection == "BILLS":
    # Store with the other bill data.
    m = re.match(r"BILLS-(\d+)([a-z]+)(\d+)(\D.*)", package_name)
    if not m: raise Exception("Unmatched bill document package name: " + package_name)
    congress, bill_type, bill_number, version_code = m.groups()
    congress = int(congress)
    if "congress" in options and congress != int(options["congress"]): return None 
    return output_for_bill(congress, bill_type, bill_number, "text-versions/" + version_code)
  else:
    # Store in fdsys/COLLECTION/YEAR/PKGNAME[/GRANULE_NAME].
    path = "%s/fdsys/%s/%s/%s" % (utils.data_dir(), collection, year, package_name)
    if granule_name: path += "/" + granule_name
    return path

def get_package_files(package_name, granule_name, path):
  baseurl = "http://www.gpo.gov/fdsys/pkg/%s/" % package_name
  baseurl_mods = baseurl
  
  if not granule_name:
    file_name = package_name
  else:
    file_name = granule_name
    baseurl_mods = "http://www.gpo.gov/fdsys/granule/%s/%s/" % (package_name, granule_name)
    
  ret = {
    'mods': (baseurl_mods + "mods.xml", path + "/mods.xml"),
    'pdf': (baseurl + "pdf/" + file_name + ".pdf", path + "/document.pdf"),
    'xml': (baseurl + "xml/" + file_name + ".xml", path + "/document.xml"),
    'text': (baseurl + "html/" + file_name + ".htm", path + "/document.html"), # text wrapped in HTML
  }
  if not granule_name:
    # granules don't have PREMIS files?
    ret['premis'] = (baseurl + "premis.xml", path + "/premis.xml")
    
  return ret

def update_bill_version_list(only_congress):
  bill_versions = { }
  
  # Which sitemap years should we look at?
  if not only_congress:
    sitemap_files = glob.glob(utils.cache_dir() + "/fdsys/sitemap/*/BILLS.xml")
  else:
    # If --congress=X is specified, only look at the relevant years.
    sitemap_files = [utils.cache_dir() + "/fdsys/sitemap/" + str(year) + "/BILLS.xml" for year in utils.get_congress_years(only_congress)]
    sitemap_files = [f for f in sitemap_files if os.path.exists(f)]
  
  # For each year-by-year BILLS sitemap...
  for year_sitemap in sitemap_files:
    dom = etree.parse(year_sitemap).getroot()
    if dom.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset": raise Exception("Mismatched sitemap type.")
    
    # Loop through each bill text version...
    for file_node in dom.xpath("x:url", namespaces=ns):
      # get URL and last modified date
      url = str(file_node.xpath("string(x:loc)", namespaces=ns))
      lastmod = str(file_node.xpath("string(x:lastmod)", namespaces=ns))
      
      # extract bill congress, type, number, and version from the URL
      m = re.match(r"http://www.gpo.gov/fdsys/pkg/BILLS-(\d+)([a-z]+)(\d+)(\D.*)/content-detail.html", url)
      if not m: raise Exception("Unmatched bill document URL: " + url)
      congress, bill_type, bill_number, version_code = m.groups()
      congress = int(congress)
      if bill_type not in utils.thomas_types: raise Exception("Invalid bill type: " + url)
      
      # If --congress=XXX is specified, only look at those bills. 
      if only_congress and congress != only_congress:
        continue
      
      # Track the documents by congress, bill type, etc.
      bill_versions\
        .setdefault(congress, { })\
        .setdefault(bill_type, { })\
        .setdefault(bill_number, { })\
        [version_code] = {
          "url": url,
          "lastmod": lastmod,
        }
        
  # Output the bill version info. We can't do this until the end because we need to get
  # the complete list of versions for a bill before we write the file, and the versions
  # may be split across multiple sitemap files.
  
  for congress in bill_versions:
    for bill_type in bill_versions[congress]:
      for bill_number in bill_versions[congress][bill_type]:
        utils.write(
          json.dumps(bill_versions[congress][bill_type][bill_number],
            sort_keys=True, indent=2, default=utils.format_datetime), 
          output_for_bill(congress, bill_type, bill_number, "text-versions.json")
        )


def output_for_bill(congress, bill_type, number, fn):
  # Similar to bills.output_for_bill
  return "%s/%d/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, fn)

# given a FDsys filename (e.g. BILLS-113hr302ih), fetch the MODS doc, and return:
#   issued_on: the date the referenced document was issued (<dateIssued>)
#   urls: a dict of forms of this doc (<location>)
def document_info_for(filename, cache, options):
  mods_url = mods_for(filename)
  mods_cache = ""
  body = utils.download(mods_url, 
    cache,
    utils.merge(options, {'xml': True})
  )

  doc = etree.fromstring(body)
  mods_ns = {"mods": "http://www.loc.gov/mods/v3"}

  locations = doc.xpath("//mods:location/mods:url", namespaces=mods_ns)

  urls = {}
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
    urls[format] = location.text

  issued_on = doc.xpath("string(//mods:dateIssued)", namespaces=mods_ns)

  return issued_on, urls


def mods_for(filename):
  return "http://www.gpo.gov/fdsys/pkg/%s/mods.xml" % filename
