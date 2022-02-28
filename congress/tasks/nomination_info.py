from congress.tasks import utils
import logging
import re
import json
from datetime import datetime
from lxml import etree
import time
from lxml.html import fromstring

# can be run on its own, just require a nomination_id (e.g. PN2094-112)


def run(options):
	nomination_id = options.get('nomination_id', None)

	if nomination_id:
		result = fetch_nomination(nomination_id, options)
		logging.warn("\n%s" % result)
	else:
		logging.error("To run this task directly, supply a bill_id.")

# download and cache page for nomination


def fetch_nomination(nomination_id, options={}):
	logging.info("\n[%s] Fetching..." % nomination_id)

	# fetch committee name map, if it doesn't already exist
	nomination_type, number, congress = utils.split_nomination_id(nomination_id)
	if not number:
		return {'saved': False, 'ok': False, 'reason': "Couldn't parse %s" % nomination_id}

	if not utils.committee_names:
		utils.fetch_committee_names(congress, options)

	# fetch bill details body
	body = utils.download(
		nomination_url_for(nomination_id),
		nomination_cache_for(nomination_id, "information.html"), options)

	if not body:
		return {'saved': False, 'ok': False, 'reason': "failed to download"}

	if options.get("download_only", False):
		return {'saved': False, 'ok': True, 'reason': "requested download only"}

	# TODO:
	#   detect group nominations, particularly for military promotions
	#   detect when a group nomination is split into subnominations
	#
	# Also, the splitting process is nonsense:
	# http://thomas.loc.gov/home/PN/split.htm

	if "split into two or more parts" in body:
		return {'saved': False, 'ok': True, 'reason': 'was split'}

	nomination = parse_nomination(nomination_id, body, options)
	output_nomination(nomination, options)
	return {'ok': True, 'saved': True}


def parse_nomination(nomination_id, body, options):
	nomination_type, number, congress = utils.split_nomination_id(nomination_id)

	# remove (and store) comments, which contain some info for the nomination
	# but also mess up the parser
	facts = re.findall("<!--(.+?)-->", body)
	body = re.sub("<!--.+?-->", "", body)

	doc = fromstring(body)

	# get rid of centered bold labels, they screw stuff up,
	# e.g. agency names on PN1375-113
	body = re.sub(re.compile("<div align=\"center\">.+?</div>", re.M), "", body)
	for elem in doc.xpath('//div[@align="center"]'):
		elem.getparent().remove(elem)

	committee_names = []
	committees = []

	info = {
		'nomination_id': nomination_id, 'actions': []
	}

	# the markup on these pages is a disaster, so we're going to use a heuristic based on boldface, inline tags followed by text
	for pair in doc.xpath('//span[@class="elabel"]|//strong'):
		if pair.tail:
			text = pair.text or pair.text_content()
			label, data = text.replace(':', '').strip(), pair.tail.strip()

			# handle actions separately
			if label.split(" ")[-1] == "Action":
				pieces = re.split("\s+\-\s+", data)

				location = label.split(" ")[0].lower()

				# use 'acted_at', even though it's always a date, to be consistent
				# with acted_at field on bills and amendments
				acted_at = datetime.strptime(pieces[0], "%B %d, %Y").strftime("%Y-%m-%d")

				# join rest back together (in case action itself has a hyphen)
				text = str.join(" - ", pieces[1:len(pieces)])

				info['actions'].append({
					"type": "action",
					"location": location,
					"acted_at": acted_at,
					"text": text
				})

			else:
				# let's handle these cases one by one
				if label == "Organization":
					info["organization"] = data

				elif label == "Control Number":
					# this doesn't seem useful
					pass

				elif label.lower() == "referred to":
					committee_names.append(data)

				elif label == "Reported by":
					info["reported_by"] = data

				elif label == "Nomination":
					# sanity check - verify nomination_id matches
					if nomination_id != data:
						raise Exception("Whoa! Mismatched nomination ID.")

				elif label == "Date Received":
					# Note: Will break with the 1000th congress in year 3789
					match = re.search("(\d{2,3})[stndhr]{2}", data)
					if match:
						info["congress"] = int(match.group(1))
					else:
						raise Exception("Choked, couldn't find Congress in \"%s\"" % data)

					# Doc format is: "January 04, 1995 (104th Congress)"
					info["received_on"] = datetime.strptime(data.split(" (")[0], "%B %d, %Y").strftime("%Y-%m-%d")

				elif label == "Nominee":

					# ignore any vice suffix
					name = data.split(", vice")[0]

					try:
						name = re.search("(.+?),", name).groups()[0]
					except Exception as e:
						raise Exception("Couldn't parse nominee entry: %s" % name)

					# Some begin "One nomination,...", so 'List of Nominees' will get it
					if "nomination" in name:
						pass

					# and grab the state and position out of the comment facts
					if facts[-5]:
						position = facts[-5]
					else:
						raise Exception("Couldn't find the position in the comments.")

					info["nominees"] = [{
						"name": name,
						"position": position,
						"state": facts[-6][2:]
					}]

				elif label.lower() == "nominees":
					pass

				elif label.lower() == "authority date":
					pass

				elif label.lower() == "list of nominees":
					# step through each sibling, collecting each br's stripped tail for names as we go
					# stop when we get to a strong or span (next label)
					nominees = []

					current_position = None
					for sibling in pair.itersiblings():
						if sibling.tag == "br":
							if sibling.tail:
								name = sibling.tail.strip()
								if (name[0:5].lower() == "to be"):
									current_position = name[6:].strip()
								elif name:
									nominees.append({
										"name": sibling.tail.strip(),
										"position": current_position
									})
						elif (sibling.tag == "strong") or (sibling.tag == "span"):
							break

					info["nominees"] = nominees

				else:
					# choke, I think we handle all of them now
					raise Exception("Unrecognized label: %s" % label)

	if not info.get("received_on", None):
		raise Exception("Choked, couldn't find received date.")

	if not info.get("nominees", None):
		raise Exception("Choked, couldn't find nominee info.")

	# try to normalize committee name to an ID
	# choke if it doesn't work - the names should match up.
	for committee_name in committee_names:
		committee_id = utils.committee_names[committee_name]
		committees.append(committee_id)
	info["referred_to"] = committees
	info["referred_to_names"] = committee_names

	return info

# directory helpers


def output_for_nomination(nomination_id, format):
	nomination_type, number, congress = utils.split_nomination_id(nomination_id)
	return "%s/%s/nominations/%s/%s" % (utils.data_dir(), congress, number, "data.%s" % format)


def nomination_url_for(nomination_id):
	nomination_type, number, congress = utils.split_nomination_id(nomination_id)

	# numbers can be either of the form "63" or "64-01"
	number_pieces = number.split("-")
	if len(number_pieces) == 1:
		number_pieces.append("00")
	url_number = "%05d%s" % (int(number_pieces[0]), number_pieces[1])

	return "http://thomas.loc.gov/cgi-bin/ntquery/z?nomis:%03d%s%s:/" % (int(congress), nomination_type.upper(), url_number)


def nomination_cache_for(nomination_id, file):
	nomination_type, number, congress = utils.split_nomination_id(nomination_id)
	return "%s/nominations/%s/%s" % (congress, number, file)


def output_nomination(nomination, options):
	logging.info("[%s] Writing to disk..." % nomination['nomination_id'])

	# output JSON - so easy!
	utils.write(
		json.dumps(nomination, sort_keys=True, indent=2, default=utils.format_datetime),
		output_for_nomination(nomination['nomination_id'], "json")
	)
