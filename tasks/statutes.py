#!/usr/bin/env python

import logging
import time, datetime
from lxml import etree
import json

import utils

# XXX: Copied from bill_info.py!
def output_for_bill(bill_id, format):
	bill_type, number, congress = utils.split_bill_id(bill_id)
	return "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, "data.%s" % format)

def run(options):
	mods_path = options.get( "path", None )

	if mods_path:
		mods = etree.parse( "./data/fdsys/%s/mods.xml" % mods_path )
	else:
		logging.error("Specify a path, like %s" % "STATUTE/1951/STATUTE-65" )
		return False

	bills = []

	for bill in mods.findall( "/{http://www.loc.gov/mods/v3}relatedItem/{http://www.loc.gov/mods/v3}extension" ):
		for bill_info in bill.findall( "{http://www.loc.gov/mods/v3}bill" ):
			congress = bill_info.attrib["congress"]
			bill_type = bill_info.attrib["type"].lower()
			number = bill_info.attrib["number"]
			bill_id = "%s%s-%s" % (bill_type, number, congress)


		bill_data = {
			'bill_id': bill_id,
			'bill_type': bill_type,
			'number': number,
			'congress': congress,

	#		'introduced_at': introduced_at,
	#		'sponsor': sponsor,
	#		'cosponsors': cosponsors,
	#
	#		'actions': actions,
	#		'history': history,
	#		'status': status,
	#		'status_at': status_date,
	#		'enacted_as': slip_law,
	#
	#		'titles': titles,
	#		'official_title': official_title,
	#		'short_title': short_title,
	#		'popular_title': popular_title,
	#
	#		'summary': summary,
	#		'subjects_top_term': subjects[0],
	#		'subjects': subjects[1],
	#
	#		'related_bills': related_bills,
	#		'committees': committees,
	#		'amendments': amendments,

			'updated_at': datetime.datetime.fromtimestamp(time.time()),
		}

		bills.append( bill_data )

		utils.write(
			json.dumps(bill_data, sort_keys=True, indent=2, default=utils.format_datetime),
			output_for_bill(bill_data['bill_id'], "json")
		)

	return bills