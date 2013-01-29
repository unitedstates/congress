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
# ./run fdsys --collections=STATUTE --store=mods
#
# Then run this script:
#
# ./run statutes
# Processes all downloaded statutes files and saves
# bill files (e.g. data/82/bills/hr/hr1/data.json).
#
# ./run statutes --volume=65
# ./run statutes --volumes=65-86
# ./run statutes --year=1951
# ./run statutes --years=1951-1972
# Processes just the indicated volume or range of volumes.
# Starting with the 93rd Congress (1973-1974, corresponding
# to volume 78 of the Statutes of Large), we have bill
# data from THOMAS. Be careful not to overwrite those files.


import logging
import time, datetime
from lxml import etree
import glob

import utils
import bill_info

def run(options):
  root_dir = utils.data_dir() + '/fdsys/STATUTE'

  if "volume" in options:
    to_fetch = glob.glob(root_dir + "/*/STATUTE-" + str(int(options["volume"])))
  elif "volumes" in options:
    start, end = options["volumes"].split("-")
    to_fetch = []
    for v in xrange(int(start), int(end)+1):
      to_fetch.extend(glob.glob(root_dir + "/*/STATUTE-" + str(v)))
  elif "year" in options:
    to_fetch = glob.glob(root_dir + "/" + str(int(options["year"])) + "/STATUTE-*")
  elif "years" in options:
    start, end = options["years"].split("-")
    to_fetch = []
    for y in xrange(int(start), int(end)+1):
      to_fetch.extend(glob.glob(root_dir + "/" + str(y) + "/STATUTE-*"))
  else:
    to_fetch = sorted(glob.glob(root_dir + "/*/STATUTE-*"))

  logging.warn("Going to process %i volumes" % len(to_fetch))

  utils.process_set(to_fetch, proc_statute, options)

def proc_statute(path, options):
  mods = etree.parse(path + "/mods.xml")
  mods_ns = { "mods": "http://www.loc.gov/mods/v3" }

  # Load the THOMAS committee names for this Congress, which is our best
  # bet for normalizing committee names in the GPO data.
  congress = mods.find( "/mods:extension[2]/mods:congress", mods_ns ).text
  utils.fetch_committee_names(congress, options)

  logging.warn("Processing %s (Congress %s)" % (path, congress))

  for bill in mods.findall( "/mods:relatedItem", mods_ns ):
    titles = []

    titles.append( {
      "title": bill.find( "mods:titleInfo/mods:title", mods_ns ).text,
      "as": "enacted",
      "type": "official",
    } )

    descriptor = bill.find( "mods:extension/mods:descriptor", mods_ns )

    if descriptor is not None:
      subject = descriptor.text
    else:
      subject = None

    # MODS files also contain information about:
    # ['BACKMATTER', 'FRONTMATTER', 'CONSTAMEND', 'PROCLAMATION', 'REORGPLAN']
    if bill.find( "mods:extension/mods:granuleClass", mods_ns ).text not in [ "PUBLICLAW", "PRIVATELAW", "HCONRES", "SCONRES" ]:
      continue

    committees = []

    cong_committee = bill.find( "mods:extension/mods:congCommittee", mods_ns )

    if cong_committee is not None:
      chambers = { "H": "House", "S": "Senate", "J": "Joint" }

      committee = chambers[cong_committee.attrib["chamber"]] + " " + cong_committee.find( "mods:name", mods_ns ).text

      committee_info = {
        "committee": committee,
        "activity": [], # XXX
        "committee_id": utils.committee_names[committee] if committee in utils.committee_names else None,
      }

      committees.append( committee_info )

    bill_elements = bill.findall( "mods:extension/mods:bill", mods_ns )

    if ( bill_elements is None ) or ( len( bill_elements ) != 1 ):
      logging.error("Could not get bill data for %s" % repr(titles) )
      continue
    else:
      bill_congress = bill_elements[0].attrib["congress"]
      bill_type = bill_elements[0].attrib["type"].lower()
      bill_number = bill_elements[0].attrib["number"]
      bill_id = "%s%s-%s" % (bill_type, bill_number, bill_congress)

    actions = []

    law_elements = bill.findall( "mods:extension/mods:law", mods_ns )

    # XXX: If <law> is missing, this assumes it is a concurrent resolution.
    #      This may be a problem if the code is updated to accept joint resolutions for constitutional amendments.
    if ( law_elements is None ) or ( len( law_elements ) != 1 ):
      other_chamber = { "HOUSE": "s", "SENATE": "h" }

      action = {
        "type": "vote",
        "vote_type": "vote2",
        "where": other_chamber[bill.find( "mods:extension/mods:originChamber", mods_ns ).text],
        "result": "pass", # XXX
        "how": "unknown", # XXX
#        "text": "",
        "acted_at": bill.find( "mods:extension/mods:granuleDate", mods_ns ).text, # XXX
        "status": "PASSED:CONCURRENTRES",
        "references": [], # XXX
      }
    else:
      law_congress = law_elements[0].attrib["congress"]
      law_number = law_elements[0].attrib["number"]
      law_type = ( "private" if ( law_elements[0].attrib["isPrivate"] == "true" ) else "public" )

      action = {
        "congress": law_congress,
        "number": law_number,
        "type": "enacted",
        "law": law_type,
        "text": "Became %s Law No: %s-%s." % ( law_type.capitalize(), law_congress, law_number ),
        "acted_at": bill.find( "mods:extension/mods:granuleDate", mods_ns ).text, # XXX
        "status": "ENACTED:SIGNED", # XXX: Check for overridden vetoes!
        "references": [], # XXX
      }

    actions.append( action )

    # Check for typos in the metadata.
    if law_congress != bill_congress:
      logging.error("Congress mismatch for %s%s: %s or %s?" % ( bill_type, bill_number, bill_congress, law_congress ) )
      continue

    status, status_date = bill_info.latest_status( actions )

    bill_data = {
      'bill_id': bill_id,
      'bill_type': bill_type,
      'number': bill_number,
      'congress': bill_congress,

      'introduced_at': None, # XXX
      'sponsor': None, # XXX
      'cosponsors': [], # XXX

      'actions': actions, # XXX
      'history': bill_info.history_from_actions( actions ),
      'status': status,
      'status_at': status_date,
      'enacted_as': bill_info.slip_law_from( actions ),

      'titles': titles,
      'official_title': bill_info.current_title_for( titles, "official" ),
      'short_title': bill_info.current_title_for( titles, "short" ), # XXX
      'popular_title': bill_info.current_title_for( titles, "popular" ), # XXX

#      'summary': summary,
      'subjects_top_term': subject,
      'subjects': [],

      'related_bills': [], # XXX: <associatedBills> usually only lists the current bill.
      'committees': committees,
      'amendments': [], # XXX

      'updated_at': datetime.datetime.fromtimestamp(time.time()),
    }

    bill_info.output_bill( bill_data, options )

  return {'ok': True, 'saved': True}
