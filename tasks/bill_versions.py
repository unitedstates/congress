import utils
import os
import os.path
import re
import json
import datetime
import logging
from lxml import etree

import fdsys


def run(options):
    bill_id = options.get('bill_id', None)
    bill_version_id = options.get('bill_version_id', None)

    # using a specific bill or version overrides the congress flag/default
    if bill_id:
        bill_type, number, congress = utils.split_bill_id(bill_id)
    elif bill_version_id:
        bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
    else:
        congress = options.get('congress', utils.current_congress())

    if bill_version_id:
        to_fetch = [bill_version_id]
    else:
        to_fetch = bill_version_ids_for(congress, options)
        if not to_fetch:
            logging.error("Error figuring out which bills to download, aborting.")
            return None

    limit = options.get('limit', None)
    if limit:
        to_fetch = to_fetch[:int(limit)]

    logging.warn("Going to fetch %i bill versions for congress #%s" % (len(to_fetch), congress))

    saved_versions = utils.process_set(to_fetch, fetch_version, options)


# uses downloaded/cached FDSys sitemap to find all available bill version IDs for this Congress
# a version ID is a "[bill_id]-[version_code]"
def bill_version_ids_for(only_congress, options):
    years = utils.get_congress_years(only_congress)
    only_bill_id = options.get('bill_id', None)

    version_ids = []

    for year in years:

        # don't bother fetching future years
        if year > datetime.datetime.now().year:
            continue

        # ensure BILLS sitemap for this year is present
        entries = fdsys.entries_from_collection(year, "BILLS", None, options)

        # some future years may not be ready yet
        if not entries:
            continue

        for entry in entries:
            url, lastmod = entry
            congress, bill_id, bill_version_id = split_url(url)

            # a year may have other congresses in it
            if int(congress) != int(only_congress):
                continue

            # we may be focused on a single bill OD
            if only_bill_id and (bill_id != only_bill_id):
                continue

            version_ids.append(bill_version_id)

    return version_ids


# returns congress, bill_id, and bill_version_id
def split_url(url):
    congress, bill_type, bill_number, version_code = re.match(r"http://www.gpo.gov/fdsys/pkg/BILLS-(\d+)([a-z]+)(\d+)(\D.*)/content-detail.html", url).groups()
    bill_id = "%s%s-%s" % (bill_type, bill_number, congress)
    bill_version_id = "%s-%s" % (bill_id, version_code)

    return congress, bill_id, bill_version_id


# an output text-versions/[versioncode]/data.json for every bill
def output_for_bill_version(bill_version_id):
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
    return "%s/%s/bills/%s/%s%s/text-versions/%s/data.json" % (utils.data_dir(), congress, bill_type, bill_type, number, version_code)


# the path to where we store MODSs files on disk
def document_filename_for(bill_version_id, filename):
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
    return "%s/%s/bills/%s/%s%s/text-versions/%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, version_code, filename)

# e.g. http://www.gpo.gov/fdsys/pkg/BILLS-113hr302ih/mods.xml


def mods_url_for(bill_version_id):
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
    return "http://www.gpo.gov/fdsys/pkg/BILLS-%s%s%s%s/mods.xml" % (congress, bill_type, number, version_code)

# given an individual bill version ID, download at least the MODs file
# and produce text-versions/[versionid]/data.json with version codes, version names,
# the date of publication, and URLs to the MODs, PREMIS, and original docs


def fetch_version(bill_version_id, options):
    # Download MODS etc.

    logging.info("\n[%s] Fetching..." % bill_version_id)

    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
    # bill_id = "%s%s-%s" % (bill_type, number, congress)

    utils.download(
        mods_url_for(bill_version_id),
        document_filename_for(bill_version_id, "mods.xml"),
        utils.merge(options, {'binary': True, 'to_cache': False})
    )

    return write_bill_version_metadata(bill_version_id)


def write_bill_version_metadata(bill_version_id):
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)

    bill_version = {
        'bill_version_id': bill_version_id,
        'version_code': version_code,
        'urls': {},
    }

    mods_ns = {"mods": "http://www.loc.gov/mods/v3"}
    doc = etree.parse(document_filename_for(bill_version_id, "mods.xml"))
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

    return {'ok': True, 'saved': True}
