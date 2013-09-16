import re
import logging

import utils

def run(options):
	congress = options.get("congress", None)
	congress = int(congress) if congress else utils.current_congress()

	chamber = options.get('chamber', None)

	if chamber and chamber in [ "h", "s" ]:
		votes = get_votes(chamber, congress, options)
	else:
		votes = get_votes("h", congress, options) + get_votes("s", congress, options)

	utils.process_set(votes, put_vote, options)

def vote_path_for(congress, chamber, vote_number):
	return "%s/%s/votes/voteview/%s%d/data.json" % (utils.data_dir(), congress, chamber, vote_number)

def vote_list_source_url_for(congress, chamber):
	chamber_map = { "h": "HOU", "s": "SEN" }

	# XXX: This filename format is not always the latest available.
	return "ftp://voteview.com/dtaord/%s%02dKH.ORD" % ( chamber_map[chamber], int(congress) )

def rollcall_list_type_for(congress, chamber):
	if congress <= 106:
		rollcall_list_type = "dtl"
	elif congress in [ 107, 108 ]:
		rollcall_list_type = "dict"
	else:
		rollcall_list_type = "csv"

	return rollcall_list_type

def rollcall_list_source_url_for(rollcall_list_type, congress, chamber):
	if rollcall_list_type == "dtl":
		chamber_map = { "h": "", "s": "S" }

		# XXX: This filename format is not always the latest available.
		rollcall_list_source_url = "ftp://voteview.com/dtl/%d%s.DTL" % ( int(congress), chamber_map[chamber] )
	elif rollcall_list_type == "dict":
		chamber_map = { "h": "house", "s": "senate" }

		# XXX: This filename format is not always the latest available.
		rollcall_list_source_url = "ftp://voteview.com/%s%d_dictionary.txt" % ( chamber_map[chamber], int(congress) )
	else:
		chamber_map = { "h": "H", "s": "S" }

		# XXX: This filename format is not always the latest available.
		rollcall_list_source_url = "ftp://voteview.com/dtaord/%s%ddesc.csv" % ( chamber_map[chamber], int(congress) )

	return rollcall_list_source_url

def vote_list_target_path_for(congress, chamber):
	return "%s/votes/voteview/vote_list_%s.txt" % (congress, chamber)

def rollcall_list_target_path_for(congress, chamber):
	return "%s/votes/voteview/rollcall_list_%s.txt" % (congress, chamber)

def get_state_from_icpsr_state_code(icpsr_state_code):
	icpsr_state_code_map = {
		 1: "CT",
		 2: "ME",
		 3: "MA",
		 4: "NH",
		 5: "RI",
		 6: "VT",
		11: "DE",
		12: "NJ",
		13: "NY",
		14: "PA",
		21: "IL",
		22: "IN",
		23: "MI",
		24: "OH",
		25: "WI",
		31: "IA",
		32: "KS",
		33: "MN",
		34: "MO",
		35: "NE",
		36: "ND",
		37: "SD",
		40: "VA",
		41: "AL",
		42: "AR",
		43: "FL",
		44: "GA",
		45: "LA",
		46: "MS",
		47: "NC",
		48: "SC",
		49: "TX",
		51: "KY",
		52: "MD",
		53: "OK",
		54: "TN",
		55: "DC",
		56: "WV",
		61: "AZ",
		62: "CO",
		63: "ID",
		64: "MT",
		65: "NV",
		66: "NM",
		67: "UT",
		68: "WY",
		71: "CA",
		72: "OR",
		73: "WA",
		81: "AK",
		82: "HI",
		99: None, # Used by presidents
	}

	return icpsr_state_code_map[icpsr_state_code] if icpsr_state_code in icpsr_state_code_map else None

def get_party_from_icpsr_party_code(icpsr_party_code):
	icpsr_party_code_map = {
		   1: "Federalist",
		   9: "Jefferson Republican",
		  10: "Anti-Federalist",
		  11: "Jefferson Democrat",
		  13: "Democrat-Republican",
		  22: "Adams",
		  25: "National Republican",
		  26: "Anti Masonic",
		  29: "Whig",
		  34: "Whig and Democrat",
		  37: "Constitutional Unionist",
		  40: "Anti-Democrat and States Rights",
		  41: "Anti-Jackson Democrat",
		  43: "Calhoun Nullifier",
		  44: "Nullifier",
		  46: "States Rights",
		  48: "States Rights Whig",
		 100: "Democrat",
		 101: "Jackson Democrat",
		 103: "Democrat and Anti-Mason",
		 104: "Van Buren Democrat",
		 105: "Conservative Democrat",
		 108: "Anti-Lecompton Democrat",
		 110: "Popular Sovereignty Democrat",
		 112: "Conservative",
		 114: "Readjuster",
		 117: "Readjuster Democrat",
		 118: "Tariff for Revenue Democrat",
		 119: "United Democrat",
		 200: "Republican",
		 202: "Union Conservative",
		 203: "Unconditional Unionist",
		 206: "Unionist",
		 208: "Liberal Republican",
		 212: "United Republican",
		 213: "Progressive Republican",
		 214: "Non-Partisan and Republican",
		 215: "War Democrat",
		 300: "Free Soil",
		 301: "Free Soil Democrat",
		 302: "Free Soil Whig",
		 304: "Anti-Slavery",
		 308: "Free Soil American and Democrat",
		 310: "American",
		 326: "National Greenbacker",
		 328: "Independent",
		 329: "Ind. Democrat",
		 331: "Ind. Republican",
		 333: "Ind. Republican-Democrat",
		 336: "Anti-Monopolist",
		 337: "Anti-Monopoly Democrat",
		 340: "Populist",
		 341: "People's",
		 347: "Prohibitionist",
		 353: "Ind. Silver Republican",
		 354: "Silver Republican",
		 355: "Union",
		 356: "Union Labor",
		 370: "Progressive",
		 380: "Socialist",
		 401: "Fusionist",
		 402: "Liberal",
		 403: "Law and Order",
		 522: "American Labor",
		 537: "Farmer-Labor",
		 555: "Jackson",
		 603: "Ind. Whig",
		1060: "Silver",
		1061: "Emancipationist",
		1111: "Liberty",
		1116: "Conservative Republican",
		1275: "Anti-Jackson",
		1346: "Jackson Republican",
		3333: "Opposition",
		4000: "Anti-Administration",
		4444: "Union",
		5000: "Pro-Administration",
		6000: "Crawford Federalist",
		6666: "Crawford Republican",
		7000: "Jackson Federalist",
		7777: "Crawford Republican",
		8000: "Adams-Clay Federalist",
		8888: "Adams-Clay Republican",
		9000: "Unknown",
		9999: "Unknown",
	}

	return icpsr_party_code_map[icpsr_party_code] if icpsr_party_code in icpsr_party_code_map else None

def party_abbreviation_for(party_name):
	party_abbreviation_map = {
		"Conservative": "C",
		"Democrat-Republican": "DR",
		"Democrat": "D",
		"Federalist": "F",
		"Ind. Democrat": "ID",
		"Ind. Republican": "IR",
		"Ind. Whig": "IW",
		"Independent": "I",
		"Liberal": "L",
		"Republican": "R",
		"Whig": "W",
	}

	return party_abbreviation_map[party_name] if party_name in party_abbreviation_map else party_name

def get_vote_type_from_icpsr_vote_code(icpsr_vote_code):
	icpsr_vote_code_map = {
		0: None, # Not a member
		1: "Yea",
		2: "Yea", # Paired yea
		3: "Yea", # Announced yea
		4: "Nay", # Announced nay
		5: "Nay", # Paired nay
		6: "Nay",
		7: "Present", # (type 1)
		8: "Present", # (type 2)
		9: "Not Voting",
	}

	return icpsr_vote_code_map[icpsr_vote_code] if icpsr_vote_code in icpsr_vote_code_map else None

def parse_icpsr_vote_string(icpsr_vote_string):
	votes = []

	for icpsr_vote_code in icpsr_vote_string:
		votes.append(get_vote_type_from_icpsr_vote_code(int(icpsr_vote_code)))

	return votes

def parse_vote_list_line(vote_list_line):
	return re.match(r"^([\s\d]{2}\d)([\s\d]{4}\d)([\s\d]\d)([\s\d]{2})([^\d]+?)([\s\d]{3}\d)([\s\d])([\s\d])([^\s\d][^\d]+?)(\d+)$", vote_list_line).groups()

def parse_rollcall_dtl_list_line(rollcall_list_line):
	return re.match(r"^([\s\d]{3}\d)([\s\d]{4}\d)?([\s\d]\d)\s(.*?)\s*$", rollcall_list_line).groups()

def parse_rollcall_dtl_list_first_line(rollcall_dtl_first_line):
	return re.match(r"^(.{14})(.{15})(.{10})?(.+)$", rollcall_dtl_first_line).groups()

def parse_rollcall_dtl_date(rollcall_dtl_date):
	from datetime import datetime

	try:
		parsed_date = datetime.strptime(rollcall_dtl_date, "%B %d, %Y")
	except ValueError:
		try:
			parsed_date = datetime.strptime(rollcall_dtl_date, "%b. %d, %Y")
		except ValueError:
			parsed_date = None

	formatted_date = utils.format_datetime(parsed_date)

	return formatted_date[:10] if formatted_date is not None else formatted_date

def extract_vote_info_from_parsed_vote_list_line(parsed_vote_list_line):
	vote_info = {
		"congress": int(parsed_vote_list_line[0]) if parsed_vote_list_line[0].strip() else None,
		"icpsr_id": int(parsed_vote_list_line[1]) if parsed_vote_list_line[1].strip() else None,
		"icpsr_state": int(parsed_vote_list_line[2]) if parsed_vote_list_line[2].strip() else None,
		"district": int(parsed_vote_list_line[3]) if parsed_vote_list_line[3].strip() else None,
		# parsed_vote_list_line[4] is partial state name
		"state_name": parsed_vote_list_line[4].strip(),
		"icpsr_party": int(parsed_vote_list_line[5]) if parsed_vote_list_line[5].strip() else None,
		"occupancy": int(parsed_vote_list_line[6]) if parsed_vote_list_line[6].strip() else None,
		"means": int(parsed_vote_list_line[7]) if parsed_vote_list_line[7].strip() else None,
		# parsed_vote_list_line[8] is partial member name
		"member_name": parsed_vote_list_line[8].strip(),
		"votes": parse_icpsr_vote_string(parsed_vote_list_line[9]),
	}

	return vote_info

def extract_rollcall_info_from_parsed_rollcall_dtl_list_line(parsed_rollcall_dtl_list_line):
	rollcall_info = {
		"vote": int(parsed_rollcall_dtl_list_line[0]),
		"line": int(parsed_rollcall_dtl_list_line[2]),
		"text": parsed_rollcall_dtl_list_line[3],
	}

	return rollcall_info

def parse_vote_list_file(vote_list_file):
	logging.warn("Parsing vote list file...")

	vote_list_info = []

	for vote_list_line in vote_list_file.split("\r\n"):
		if not vote_list_line.strip():
			continue

		vote_info = extract_vote_info_from_parsed_vote_list_line(parse_vote_list_line(vote_list_line))

		vote_info["state"] = get_state_from_icpsr_state_code(vote_info["icpsr_state"]) if vote_info["icpsr_state"] is not None else None
		vote_info["party"] = get_party_from_icpsr_party_code(vote_info["icpsr_party"]) if vote_info["icpsr_party"] is not None else None

		icpsr_id = vote_info["icpsr_id"]

		try:
			bioguide_id = utils.get_person_id("icpsr", icpsr_id, "bioguide")
		except KeyError as e:
			logging.error("Problem with member %s ([%d] %s) of %s %s: %s" % ( vote_info["member_name"], vote_info["icpsr_party"], vote_info["party"], vote_info["state_name"], vote_info["district"], e.message ))
			continue

		vote_info["bioguide_id"] = bioguide_id

		vote_list_info.append(vote_info)

	return vote_list_info

def parse_rollcall_dtl_list_file(rollcall_dtl_list_file):
	rollcall_dtl_list_info = {}

	for rollcall_dtl_list_line in rollcall_dtl_list_file.split("\r\n"):
		if not rollcall_dtl_list_line.strip():
			continue

		rollcall_dtl_list_line_info = extract_rollcall_info_from_parsed_rollcall_dtl_list_line(parse_rollcall_dtl_list_line(rollcall_dtl_list_line))

		if rollcall_dtl_list_line_info["line"] == 1:
			rollcall_info = {}

			rollcall_dtl_list_first_line_parts = parse_rollcall_dtl_list_first_line(rollcall_dtl_list_line_info["text"])

			rollcall_info["record_id"] = rollcall_dtl_list_first_line_parts[0].strip()
			rollcall_info["journal_id"] = rollcall_dtl_list_first_line_parts[1].strip()
			rollcall_info["bill"] = rollcall_dtl_list_first_line_parts[2].strip()
			rollcall_info["date"] = parse_rollcall_dtl_date(rollcall_dtl_list_first_line_parts[3].strip())
		elif rollcall_dtl_list_line_info["line"] == 2:
			pass
		elif rollcall_dtl_list_line_info["line"] == 3:
			rollcall_info["description"] = rollcall_dtl_list_line_info["text"]
		else:
			rollcall_info["description"] += " " + rollcall_dtl_list_line_info["text"]

		rollcall_dtl_list_info[rollcall_dtl_list_line_info["vote"]] = rollcall_info

	return rollcall_dtl_list_info

def parse_rollcall_list_file(rollcall_list_type, rollcall_list_file):
	logging.warn("Parsing rollcall list file...")
	logging.info("Rollcall list type: %s" % ( rollcall_list_type ))

	if rollcall_list_type == "dtl":
		rollcall_list_info = parse_rollcall_dtl_list_file(rollcall_list_file)
	else:
		raise ValueError("Rollcall list type not supported: %s" % ( rollcall_list_type ))

	return rollcall_list_info

def build_votes(vote_list):
	logging.warn("Building votes...")

	votes = {}

	for vote_info in vote_list:
		for i in range(len(vote_info["votes"])):
			vote_type = vote_info["votes"][i]

			if vote_type is None:
				continue

			if i not in votes:
				votes[i] = {}

			if vote_type not in votes[i]:
				votes[i][vote_type] = []

			vote = {
				"id": vote_info["bioguide_id"],
				"display_name": vote_info["member_name"],
				"party": party_abbreviation_for(vote_info["party"]),
				"state": vote_info["state"],
			}

			votes[i][vote_type].append(vote)

	# Sort votes by member name.
	for vote_number in votes:
		for vote_type in votes[vote_number]:
			votes[vote_number][vote_type].sort(key = lambda vote : vote["display_name"])

	return votes

def fetch_vote_list_file(chamber, congress, options):
	logging.warn("Fetching vote list file...")

	vote_list_file = utils.download(vote_list_source_url_for(congress, chamber), vote_list_target_path_for(congress, chamber), options).encode("utf-8")

	if not vote_list_file:
		logging.error("Couldn't download vote list file.")
		return None

	return vote_list_file

def fetch_rollcall_list_file(rollcall_list_type, chamber, congress, options):
	logging.warn("Fetching rollcall list file...")

	rollcall_list_file = utils.download(rollcall_list_source_url_for(rollcall_list_type, congress, chamber), rollcall_list_target_path_for(congress, chamber), options).encode("utf-8")

	if not rollcall_list_file:
		logging.error("Couldn't download rollcall list file.")
		return None

	return rollcall_list_file

def get_votes(chamber, congress, options):
	logging.warn("Getting votes for %d-%s..." % ( congress, chamber ))

	vote_list_file = fetch_vote_list_file(chamber, congress, options)

	vote_list = parse_vote_list_file(vote_list_file)
	votes = build_votes(vote_list)

	rollcall_list_type = rollcall_list_type_for(congress, chamber)
	rollcall_list_file = fetch_rollcall_list_file(rollcall_list_type, chamber, congress, options)

	rollcall_list = parse_rollcall_list_file(rollcall_list_type, rollcall_list_file)

	vote_output_list = []

	for rollcall_number in rollcall_list:
		vote_results = votes[rollcall_number - 1]
		rollcall = rollcall_list[rollcall_number]

		vote_output = {
			"congress": congress,
			"chamber": chamber,
			"number": rollcall_number, # XXX: This is not the right number.
			"question": rollcall["description"],
			"date": rollcall["date"],
			"votes": vote_results,
		}

		vote_output_list.append(vote_output)

	return vote_output_list

def put_vote(vote, options):
	import json

	logging.warn("Writing vote %d-%s%d..." % ( vote["congress"], vote["chamber"], vote["number"] ))

	vote_path = vote_path_for(vote["congress"], vote["chamber"], vote["number"])

	utils.write(json.dumps(vote, sort_keys=True, indent=2), vote_path)

	return { "ok": True, "saved": True }
