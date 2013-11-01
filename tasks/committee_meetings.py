import utils
import os.path
import re, datetime
import json, lxml.etree
import uuid
import logging
from email.utils import parsedate
from time import mktime

def run(options):
  # Load the committee metadata from the congress-legislators repository and make a
  # mapping from thomas_id and house_id to the committee dict. For each committee,
  # replace the subcommittees list with a dict from thomas_id to the subcommittee.
  utils.require_congress_legislators_repo()
  committees = { }
  for c in utils.yaml_load("congress-legislators/committees-current.yaml"):
    committees[c["thomas_id"]] = c
    if "house_committee_id" in c: committees[c["house_committee_id"] + "00"] = c
    c["subcommittees"] = dict((s["thomas_id"], s) for s in c.get("subcommittees", []))

  for chamber in ("house", "senate"):
    # Load any existing meetings file so we can recycle GUIDs generated for Senate meetings.
    existing_meetings = []
    output_file = utils.data_dir() + "/committee_meetings_%s.json" % chamber
    if os.path.exists(output_file):
      existing_meetings = json.load(open(output_file))

    # Scrape for meeting info.
    if chamber == "senate":
      meetings = fetch_senate_committee_meetings(existing_meetings, committees, options)
    else:
      meetings = fetch_house_committee_meetings(existing_meetings, committees, options)

    # Write out.
    utils.write(json.dumps(meetings, sort_keys=True, indent=2, default=utils.format_datetime),
      output_file)

def fetch_senate_committee_meetings(existing_meetings, committees, options):
  # Parse the Senate committee meeting XML feed for meetings.
  # To aid users of the data, attempt to assign GUIDs to meetings.

  options = dict(options) # clone
  options["binary"] = True

  meetings = []

  dom = lxml.etree.fromstring(utils.download(
    "http://www.senate.gov/general/committee_schedules/hearings.xml",
    "committee_schedule/senate.xml",
    options))

  for node in dom.xpath("meeting"):
    committee_id = unicode(node.xpath('string(cmte_code)'))
    if committee_id.strip() == "": continue # "No committee hearings scheduled" placeholder
    occurs_at = unicode(node.xpath('string(date)'))
    room = unicode(node.xpath('string(room)'))
    topic = unicode(node.xpath('string(matter)'))

    occurs_at = datetime.datetime.strptime(occurs_at, "%d-%b-%Y %I:%M %p")
    topic = re.sub(r"\s+", " ", topic).strip()

    # Validate committee code.
    try:
      committee_code, subcommittee_code = re.match(r"(\D+)(\d+)$", committee_id).groups()
      if committee_code not in committees: raise ValueError(committee_code)
      if subcommittee_code == "00": subcommittee_code = None
      if subcommittee_code and subcommittee_code not in committees[committee_code]["subcommittees"]: raise ValueError(subcommittee_code)
    except:
      print "Invalid committee code", committee_id
      continue

    # See if this meeting already exists. If so, take its GUID.
    # Assume meetings are the same if they are for the same committee/subcommittee and
    # at the same time.
    for mtg in existing_meetings:
      if mtg["committee"] == committee_code and mtg.get("subcommittee", None) == subcommittee_code and mtg["occurs_at"] == occurs_at.isoformat():
        guid = mtg["guid"]
        break
    else:
      # Not found, so create a new ID.
      guid = unicode(uuid.uuid4())

    # Scrape the topic text for mentions of bill numbers.
    congress = utils.congress_from_legislative_year(utils.current_legislative_year(occurs_at))
    bills = []
    bill_number_re = re.compile(r"(hr|s|hconres|sconres|hjres|sjres|hres|sres)\s?(\d+)", re.I)
    for bill_match in bill_number_re.findall(topic.replace(".", "")):
      bills.append( bill_match[0].lower() + bill_match[1] + "-" + str(congress) )

    # Create the meeting event.
    meetings.append({
      "chamber": "senate",
      "congress": congress,
      "guid": guid,
      "committee": committee_code,
      "subcommittee": subcommittee_code,
      "occurs_at": occurs_at.isoformat(),
      "room": room,
      "topic": topic,
      "bills": bills,
    })

  return meetings

def fetch_house_committee_meetings(existing_meetings, committees, options):
  # Scrape docs.house.gov for meetings.
  # To aid users of the data, assign GUIDs to meetings piggy-backing off of the provided EventID.

  opts = dict(options)
  opts["binary"] = True

  meetings = []
  seen_meetings = set()

  # Scrape the committee listing page for a list of committees with scrapable events.
  committee_html = utils.download("http://docs.house.gov/Committee/Committees.aspx", "committee_schedule/house_overview.html", options)
  for cmte in re.findall(r'<option value="(....)">', committee_html):

    if cmte not in committees:
      logging.error("Invalid committee code: " + cmte)
      continue

    # Download the feed for this committee.
    html = utils.download(
      "http://docs.house.gov/Committee/RSS.ashx?Code=%s" % cmte,
      "committee_schedule/house_%s.xml" % cmte,
      opts)

    # It's not really valid?
    html = html.replace("&nbsp;", " ") # who likes nbsp's? convert to spaces. but otherwise, entity is not recognized.

    # Parse and loop through the meetings listed in the committee feed.
    dom = lxml.etree.fromstring(html)

    for mtg in dom.xpath("channel/item"):
      eventurl = unicode(mtg.xpath("string(link)"))
      event_id = re.search(r"EventID=(\d+)$", eventurl).group(1)
      pubDate = datetime.datetime.fromtimestamp(mktime(parsedate(mtg.xpath("string(pubDate)"))))

      # skip old records of meetings, some of which just give error pages
      if pubDate < (datetime.datetime.now()-datetime.timedelta(days=60)):
        continue

      # Events can appear in multiple committee feeds if it is a joint meeting.
      if event_id in seen_meetings:
        logging.info("Duplicated multi-committee event: " + event_id)
        continue
      seen_meetings.add(event_id)

      # Load the HTML page for the event and use the mechanize library to
      # submit the form that gets the meeting XML. TODO Simplify this when
      # the House makes the XML available at an actual URL.

      logging.info(eventurl)
      import mechanize
      br = mechanize.Browser()
      br.open(eventurl)
      br.select_form(nr=0)

      # mechanize parser failed to find these fields
      br.form.new_control("hidden", "__EVENTTARGET", { })
      br.form.new_control("hidden", "__EVENTARGUMENT", { })
      br.form.set_all_readonly(False)

      # set field values
      br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgXML"
      br["__EVENTARGUMENT"] = ""

      # Submit form and get and load XML response
      dom = lxml.etree.parse(br.submit())

      # Parse the XML.
      try:
        parse_house_committee_meeting(event_id, dom, meetings, existing_meetings, committees)
      except Exception as e:
        logging.error("Error parsing " + eventurl, exc_info=e)
        continue

  return meetings

def parse_house_committee_meeting(event_id, dom, meetings, existing_meetings, committees):
  try:
    congress = int(dom.getroot().get("congress-num"))

    occurs_at = dom.xpath("string(meeting-details/meeting-date/calendar-date)") + " " + dom.xpath("string(meeting-details/meeting-date/start-time)")
    occurs_at = datetime.datetime.strptime(occurs_at, "%Y-%m-%d %H:%M:%S")
  except:
    raise ValueError("Invalid meeting data (probably server error).")

  current_status = str(dom.xpath("string(current-status)"))
  if current_status not in ("S", "R"):
    # If status is "P" (postponed and not yet rescheduled) or "C" (cancelled),
    # don't include in output.
    return

  topic = dom.xpath("string(meeting-details/meeting-title)")

  room = None
  for n in dom.xpath("meeting-details/meeting-location/capitol-complex"):
    room = n.xpath("string(building)") + " " + n.xpath("string(room)")

  bills = [
    c.text.replace(".", "").replace(" ", "").lower() + "-" + str(congress)
    for c in
    dom.xpath("meeting-documents/meeting-document[@type='BR']/legis-num")]

  # Repeat the event for each listed committee or subcommittee, since our
  # data model supports only a single committee/subcommittee ID per event.

  orgs = []
  for c in dom.xpath("meeting-details/committees/committee-name"):
    if c.get("id") not in committees: raise ValueError("Invalid committee ID: " + c.get("id"))
    orgs.append( (committees[c.get("id")]["thomas_id"], None) )
  for sc in dom.xpath("meeting-details/subcommittees/committee-name"):
    if sc.get("id")[0:2] + "00" not in committees: raise ValueError("Invalid committee ID: " + sc.get("id"))
    c = committees[sc.get("id")[0:2] + "00"]
    if sc.get("id")[2:] not in c["subcommittees"]:
      logging.error("Invalid subcommittee code: " + sc.get("id"))
      continue
    orgs.append( (c["thomas_id"], sc.get("id")[2:]) )

  for committee_code, subcommittee_code in orgs:
    # See if this meeting already exists. If so, take its GUID.
    # Assume meetings are the same if they are for the same event ID and committee/subcommittee.
    for mtg in existing_meetings:
      if mtg["house_event_id"] == event_id and mtg.get("committee", None) == committee_code and mtg.get("subcommittee", None) == subcommittee_code:
        guid = mtg["guid"]
        break
    else:
      # Not found, so create a new ID.
      guid = unicode(uuid.uuid4())

    # Create the meeting record.
    meetings.append({
      "chamber": "house",
      "congress": congress,
      "guid": guid,
      "committee": committee_code,
      "subcommittee": subcommittee_code,
      "occurs_at": occurs_at.isoformat(),
      "room": room,
      "topic": topic,
      "bills": bills,
      "house_meeting_type": dom.getroot().get("meeting-type"),
      "house_event_id": event_id,
    })

