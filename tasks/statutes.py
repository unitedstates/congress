#!/usr/bin/env python

import logging
import time, datetime
from lxml import etree
import json

import utils
import bill_info

def run( options ):
	mods_path = options.get( "path", None )

	if mods_path:
		mods = etree.parse( "./data/fdsys/%s/mods.xml" % mods_path )
	else:
		logging.error("Specify a path, like %s" % "STATUTE/1951/STATUTE-65" )
		return False

	bills = []

	if not utils.committee_names: utils.fetch_committee_names( mods.find( "/{http://www.loc.gov/mods/v3}extension[2]/{http://www.loc.gov/mods/v3}congress" ).text, options)

	for bill in mods.findall( "/{http://www.loc.gov/mods/v3}relatedItem" ):
		titles = []

		titles.append( {
			"title": bill.find( "{http://www.loc.gov/mods/v3}titleInfo/{http://www.loc.gov/mods/v3}title" ).text,
			"as": "enacted",
			"type": "official",
		} )

		descriptor = bill.find( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}descriptor" )

		if descriptor is not None:
			subject = descriptor.text
		else:
			subject = None

		# MODS files also contain information about:
		# ['BACKMATTER', 'FRONTMATTER', 'CONSTAMEND', 'PROCLAMATION', 'REORGPLAN']
		if bill.find( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}granuleClass" ).text not in [ "PUBLICLAW", "PRIVATELAW", "HCONRES", "SCONRES" ]:
			continue

		committees = []

		cong_committee = bill.find( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}congCommittee" )

		if cong_committee is not None:
			chambers = { "H": "House", "S": "Senate", "J": "Joint" }

			committee = chambers[cong_committee.attrib["chamber"]] + " " + cong_committee.find( "{http://www.loc.gov/mods/v3}name" ).text

			committee_info = {
				"committee": committee,
				"activity": [], # XXX
				"committee_id": utils.committee_names[committee] if committee in utils.committee_names else None,
			}

			committees.append( committee_info )

		bill_elements = bill.findall( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}bill" )

		if ( bill_elements is None ) or ( len( bill_elements ) != 1 ):
			logging.error("Could not get bill data for %s" % ( official_title ) )
			continue
		else:
			congress = bill_elements[0].attrib["congress"]
			bill_type = bill_elements[0].attrib["type"].lower()
			number = bill_elements[0].attrib["number"]
			bill_id = "%s%s-%s" % (bill_type, number, congress)

		actions = []

		law_elements = bill.findall( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}law" )

		# XXX: If <law> is missing, this assumes it is a concurrent resolution.
		#      This may be a problem if the code is updated to accept joint resolutions for constitutional amendments.
		if ( law_elements is None ) or ( len( law_elements ) != 1 ):
			other_chamber = { "HOUSE": "s", "SENATE": "h" }

			action = {
				"type": "vote",
				"vote_type": "vote2",
				"where": other_chamber[bill.find( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}originChamber" ).text],
				"result": "pass", # XXX
				"how": "unknown", # XXX
#				"text": "",
				"acted_at": bill.find( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}granuleDate" ).text, # XXX
				"status": "PASSED:CONCURRENTRES",
				"references": [], # XXX
			}
		else:
			congress = law_elements[0].attrib["congress"]
			number = law_elements[0].attrib["number"]
			law_type = ( "private" if ( law_elements[0].attrib["isPrivate"] == "true" ) else "public" )

			action = {
				"congress": congress,
				"number": number,
				"type": "enacted",
				"law": law_type,
				"text": "Became %s Law No: %s-%s." % ( law_type.capitalize(), congress, number ),
				"acted_at": bill.find( "{http://www.loc.gov/mods/v3}extension/{http://www.loc.gov/mods/v3}granuleDate" ).text, # XXX
				"status": "ENACTED:SIGNED", # XXX: Check for overridden vetoes!
				"references": [], # XXX
			}

		actions.append( action )

		status, status_date = bill_info.latest_status( actions )

		bill_data = {
			'bill_id': bill_id,
			'bill_type': bill_type,
			'number': number,
			'congress': congress,

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

#			'summary': summary,
			'subjects_top_term': subject,
			'subjects': [],

			'related_bills': [], # XXX: <associatedBills> usually only lists the current bill.
			'committees': committees,
			'amendments': [], # XXX

			'updated_at': datetime.datetime.fromtimestamp(time.time()),
		}

		bills.append( bill_data )

		bill_info.output_bill( bill_data, options )

	return bills
