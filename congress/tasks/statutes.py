# Convert GPO Fdsys STATUTE metadata into bill files.
#
# GPO has the Statutes at Large from 1951 (the 65th
# volume, 82nd Congress) to the present, with metadata
# at the level of the law.
#
# The bill files have sort of made up action entries
# since we don't know the legislative history of the bill.
# We also assume all bills are enacted by being signed
# by the President for the sake of outputting status
# information.
#
# First download the Statutes at Large from GPO:
#
# usc-run fdsys --collections=STATUTE --store=mods
#
# To process statute text, get the text PDFs:
#
# usc-run fdsys --collections=STATUTE --store=pdfs --granules
#
# Then run this script:
#
# usc-run statutes
#
# Processes all downloaded statutes files and saves bill files:
#   data/82/bills/hr/hr1/data.json and
#   data/82/bills/hr/hr1/text-versions/enr/data.json
#
# Specify --textversions to only write the text-versions file.
#
# If the individual statute PDF files are available, then
# additional options are possible:
#
# If --linkpdf is given, then *hard links* are created from
# where the PDF should be for bill text to where the PDF has
# been downloaded in the fdsys directory.
#
# If --extracttext is given, then the pdf is converted to text
# using "pdftotext -layout" and they are stored in files like
# data/82/bills/hr/hr1/text-versions/enr/document.txt. They are
# UTF-8 encoded and have form-feed characters marking page breaks.
#
# Examples:
# usc-run statutes --volume=65
# usc-run statutes --volumes=65-86
# usc-run statutes --year=1951
# usc-run statutes --years=1951-1972
# Processes just the indicated volume or range of volumes.
# Starting with the 93rd Congress (1973-1974, corresponding
# to volume 78 of the Statutes of Large), we have bill
# data from THOMAS. Be careful not to overwrite those files.
#
# With bill text missing from THOMAS/GPO from the 93rd to
# 102nd Congresses, fill in the text-versions files like so:
# usc-run statutes --volumes=87-106 --textversions

import logging
import time
import datetime
from lxml import etree
import glob
import json
import os.path
import subprocess

from congress.tasks import utils, bill_info, bill_versions
import fdsys


def run(options):
    root_dir = utils.data_dir() + '/fdsys/STATUTE'

    if "volume" in options:
        to_fetch = glob.glob(root_dir + "/*/STATUTE-" + str(int(options["volume"])))
    elif "volumes" in options:
        start, end = options["volumes"].split("-")
        to_fetch = []
        for v in range(int(start), int(end) + 1):
            to_fetch.extend(glob.glob(root_dir + "/*/STATUTE-" + str(v)))
    elif "year" in options:
        to_fetch = glob.glob(root_dir + "/" + str(int(options["year"])) + "/STATUTE-*")
    elif "years" in options:
        start, end = options["years"].split("-")
        to_fetch = []
        for y in range(int(start), int(end) + 1):
            to_fetch.extend(glob.glob(root_dir + "/" + str(y) + "/STATUTE-*"))
    else:
        to_fetch = sorted(glob.glob(root_dir + "/*/STATUTE-*"))

    logging.warn("Going to process %i volumes" % len(to_fetch))

    utils.process_set(to_fetch, proc_statute_volume, options)


def proc_statute_volume(path, options):
    mods = etree.parse(path + "/mods.xml")
    mods_ns = {"mods": "http://www.loc.gov/mods/v3"}

    # Load the THOMAS committee names for this Congress, which is our best
    # bet for normalizing committee names in the GPO data.
    congress = mods.find("/mods:extension[2]/mods:congress", mods_ns).text
    utils.fetch_committee_names(congress, options)

    logging.warn("Processing %s (Congress %s)" % (path, congress))

    package_id = mods.find("/mods:extension[2]/mods:accessId", mods_ns).text

    for bill in mods.findall("/mods:relatedItem", mods_ns):
        # MODS files also contain information about:
        # ['BACKMATTER', 'FRONTMATTER', 'CONSTAMEND', 'PROCLAMATION', 'REORGPLAN']
        if bill.find("mods:extension/mods:granuleClass", mods_ns).text not in ["PUBLICLAW", "PRIVATELAW", "HCONRES", "SCONRES"]:
            continue

        # Get the title and source URL (used in error messages).
        title_text = bill.find("mods:titleInfo/mods:title", mods_ns).text.replace('""', '"')
        source_url = bill.find("mods:location/mods:url[@displayLabel='Content Detail']", mods_ns).text

        # Bill number
        bill_elements = bill.findall("mods:extension/mods:bill[@priority='primary']", mods_ns)
        if len(bill_elements) == 0:
            logging.error("No bill number identified for '%s' (%s)" % (title_text, source_url))
            continue
        elif len(bill_elements) > 1:
            logging.error("Multiple bill numbers identified for '%s'" % title_text)
            for be in bill_elements:
                logging.error("  -- " + etree.tostring(be).strip())
            logging.error("  @ " + source_url)
            continue
        else:
            bill_congress = bill_elements[0].attrib["congress"]
            bill_type = bill_elements[0].attrib["type"].lower()
            bill_number = bill_elements[0].attrib["number"]
            bill_id = "%s%s-%s" % (bill_type, bill_number, bill_congress)

        # Title
        titles = []
        titles.append({
            "title": title_text,
            "as": "enacted",
            "type": "official",
            "is_for_portion": False,
        })

        # Subject
        descriptor = bill.find("mods:extension/mods:descriptor", mods_ns)
        if descriptor is not None:
            subject = descriptor.text
        else:
            subject = None

        # Committees
        committees = []
        cong_committee = bill.find("mods:extension/mods:congCommittee", mods_ns)
        if cong_committee is not None:
            chambers = {"H": "House", "S": "Senate", "J": "Joint"}
            committee = chambers[cong_committee.attrib["chamber"]] + " " + cong_committee.find("mods:name", mods_ns).text
            committee_info = {
                "committee": committee,
                "activity": [],  # XXX
                "committee_id": utils.committee_names[committee] if committee in utils.committee_names else None,
            }
            committees.append(committee_info)

        # The 'granuleDate' is the enactment date?
        granule_date = bill.find("mods:extension/mods:granuleDate", mods_ns).text

        sources = [{
            "source": "statutes",
            "package_id": package_id,
            "access_id": bill.find("mods:extension/mods:accessId", mods_ns).text,
            "source_url": source_url,
            "volume": bill.find("mods:extension/mods:volume", mods_ns).text,
            "page": bill.find("mods:part[@type='article']/mods:extent[@unit='pages']/mods:start", mods_ns).text,
            "position": bill.find("mods:extension/mods:pagePosition", mods_ns).text,
        }]

        law_elements = bill.findall("mods:extension/mods:law", mods_ns)

        # XXX: If <law> is missing, this assumes it is a concurrent resolution.
        #      This may be a problem if the code is updated to accept joint resolutions for constitutional amendments.
        if (law_elements is None) or (len(law_elements) != 1):
            other_chamber = {"HOUSE": "s", "SENATE": "h"}

            actions = [{
                "type": "vote",
                "vote_type": "vote2",
                "where": other_chamber[bill.find("mods:extension/mods:originChamber", mods_ns).text],
                "result": "pass",  # XXX
                "how": "unknown",  # XXX
                #        "text": "",
                "acted_at": granule_date,  # XXX
                "status": "PASSED:CONCURRENTRES",
                "references": [],  # XXX
            }]
        else:
            law_congress = law_elements[0].attrib["congress"]
            law_number = law_elements[0].attrib["number"]
            law_type = ("private" if (law_elements[0].attrib["isPrivate"] == "true") else "public")

            # Check for typos in the metadata.
            if law_congress != bill_congress:
                logging.error("Congress mismatch for %s%s: %s or %s? (%s)" % (bill_type, bill_number, bill_congress, law_congress, source_url))
                continue

            actions = [{
                "congress": law_congress,
                "number": law_number,
                "type": "enacted",
                "law": law_type,
                "text": "Became %s Law No: %s-%s." % (law_type.capitalize(), law_congress, law_number),
                "acted_at": granule_date,  # XXX
                "status": "ENACTED:SIGNED",  # XXX: Check for overridden vetoes!
                "references": [],  # XXX
            }]

        status, status_date = bill_info.latest_status(actions)

        bill_data = {
            'bill_id': bill_id,
            'bill_type': bill_type,
            'number': bill_number,
            'congress': bill_congress,

            'introduced_at': None,  # XXX
            'sponsor': None,  # XXX
            'cosponsors': [],  # XXX

            'actions': actions,  # XXX
            'history': bill_info.history_from_actions(actions),
            'status': status,
            'status_at': status_date,
            'enacted_as': bill_info.slip_law_from(actions),

            'titles': titles,
            'official_title': bill_info.current_title_for(titles, "official"),
            'short_title': bill_info.current_title_for(titles, "short"),  # XXX
            'popular_title': bill_info.current_title_for(titles, "popular"),  # XXX

            'subjects_top_term': subject,
            'subjects': [],

            'related_bills': [],  # XXX: <associatedBills> usually only lists the current bill.
            'committees': committees,
            'amendments': [],  # XXX

            'sources': sources,
            'updated_at': datetime.datetime.fromtimestamp(time.time()),
        }

        if not options.get('textversions', False):
            bill_info.output_bill(bill_data, options)

        # XXX: Can't use bill_versions.fetch_version() because it depends on fdsys.
        version_code = "enr"
        bill_version_id = "%s%s-%s-%s" % (bill_type, bill_number, bill_congress, version_code)
        bill_version = {
            'bill_version_id': bill_version_id,
            'version_code': version_code,
            'issued_on': status_date,
            'urls': {"pdf": bill.find("mods:location/mods:url[@displayLabel='PDF rendition']", mods_ns).text},
            'sources': sources,
        }
        utils.write(
            json.dumps(bill_version, sort_keys=True, indent=2, default=utils.format_datetime),
            bill_versions.output_for_bill_version(bill_version_id)
        )

        # Process the granule PDF.
        # - Hard-link it into the right place to be seen as bill text.
        # - Run "pdftotext -layout" to convert it to plain text and save it in the bill text location.
        pdf_file = path + "/" + sources[0]["access_id"] + "/document.pdf"
        if os.path.exists(pdf_file):
            dst_path = fdsys.output_for_bill(bill_data["bill_id"], "text-versions/" + version_code, is_data_dot=False)
            if options.get("linkpdf", False):
                os.link(pdf_file, dst_path + "/document.pdf")  # a good idea
            if options.get("extracttext", False):
                logging.error("Running pdftotext on %s..." % pdf_file)
                if subprocess.call(["pdftotext", "-layout", pdf_file, dst_path + "/document.txt"]) != 0:
                    raise Exception("pdftotext failed on %s" % pdf_file)

    return {'ok': True, 'saved': True}
