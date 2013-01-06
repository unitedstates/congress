import re, logging, datetime, time, json

import utils

from bill_info import sponsor_for, actions_for

# TODO:
# "TEXT OF AMENDMENT AS SUBMITTED"
# "COSPONSORS"

def fetch_amendment(amdt_id, options):
  logging.info("\n[%s] Fetching..." % amdt_id)
  
  # fetch bill details body
  body = utils.download(
    amdt_url_for(amdt_id), 
    amdt_cache_for(amdt_id, "information.html"),
    options.get('force', False))

  if not body:
    return {'saved': False, 'ok': False, 'reason': "failed to download"}

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}
    
  amdt_type, number, congress = utils.split_bill_id(amdt_id)

  amdt = {
    'amendment_id': amdt_id,
    'amendment_type': amdt_type,
    'chamber': amdt_type[0],
    'number': number,
    'congress': congress,
    'house_number': house_number_for(body),
    
    'amends': amends_for(body),

    'offered_at': offered_at_for(body, 'offered'),
    'submitted_at': offered_at_for(body, 'submitted'),
    'proposed_at': offered_at_for(body, 'proposed'),
    'sponsor': sponsor_for(body),

    'title': amendment_simple_text_for(body, "title"),
    'description': amendment_simple_text_for(body, "description"),
    'purpose': amendment_simple_text_for(body, "purpose"),
    
    'actions': actions_for(body, amdt_id, is_amendment=True),

    'updated_at': datetime.datetime.fromtimestamp(time.time()),
  }
  
  output_amendment(amdt, options)

  return {'ok': True, 'saved': True}

def output_amendment(amdt, options):
  logging.info("[%s] Writing to disk..." % amdt['amendment_id'])

  # output JSON - so easy!
  utils.write(
    json.dumps(amdt, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_amdt(amdt['amendment_id'], "json")
  )

def house_number_for(body):
  match = re.search(r"H.AMDT.\d+</b>\n \((A\d+)\)", body, re.I)
  if match:
    return match.group(1)
  else:
    return None
    
def amends_for(body):
  # When an amendment amends an amendment, the bill is listed first, followed by a comma
  # and newline. Skip the bill when it exists and just parse the amendment.
  match = re.search(r"Amends: (?:.*\n, )?<a href=\"/cgi-bin/bdquery/z\?d(\d+):([A-Z]+)(\d+):", body)
  if match:
    congress = int(match.group(1))
    bill_type = utils.thomas_types_2[match.group(2)]
    bill_number = int(match.group(3))
    is_bill = bill_type not in ("samdt", "hamdt")
    return {
      "document_type": "bill" if is_bill else "amendment",
      "congress": congress,
      "bill_type" if is_bill else "amendment_type": bill_type,
      "number": bill_number,
    }
  else:
    raise Exception("Choked finding what the amendment amends.")

def offered_at_for(body, offer_type):
  match = re.search(r"Sponsor:.*\n.*\(" + offer_type + " (\d+/\d+/\d+)", body, re.I)
  if match:
    date = match.group(1)
    date = datetime.datetime.strptime(date, "%m/%d/%Y")
    date = datetime.datetime.strftime(date, "%Y-%m-%d")
    return date
  else:
    return None # not all of offered/submitted/proposed will be present

def amendment_simple_text_for(body, heading):
  match = re.search(r"AMENDMENT " + heading.upper() + ":(<br />| )(.+)", body, re.I)
  if match:
    title = match.group(2).strip()
    if title == "*** TITLE NOT FOUND ***":
      return None
    return title
  else:
    return None

def amdt_url_for(amdt_id):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  thomas_type = utils.thomas_types[amdt_type][0]
  congress = int(congress)
  number = int(number)
  return "http://thomas.loc.gov/cgi-bin/bdquery/D?d%03d:%d:./list/bss/d%03d%s.lst::" % (congress, number, congress, thomas_type)

def amdt_cache_for(amdt_id, file):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/amendments/%s/%s%s/%s" % (congress, amdt_type, amdt_type, number, file)

def output_for_amdt(amdt_id, format):
  amdt_type, number, congress = utils.split_bill_id(amdt_id)
  return "%s/%s/amendments/%s/%s%s/%s" % (utils.data_dir(), congress, amdt_type, amdt_type, number, "data.%s" % format)

