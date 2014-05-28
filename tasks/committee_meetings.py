import utils
import os.path
import re
import datetime
import json
import lxml.etree
import uuid
import logging
import mechanize
import zipfile
import StringIO
from email.utils import parsedate
from time import mktime

# options:
#
#    --chamber: "house" or "senate" to limit the parse to a single chamber
#    --load_by: Takes a range of House Event IDs. Give it the beginning and end IDs with a dash between, otherwise, it goes by the committee feeds.

def run(options):
    # can limit it to one chamber
    chamber = options.get("chamber", None)
    if chamber and (chamber in ("house", "senate")):
        chambers = (chamber)
    else:
        chambers = ("house", "senate")

    load_by = options.get("load_by", None)

    # Load the committee metadata from the congress-legislators repository and make a
    # mapping from thomas_id and house_id to the committee dict. For each committee,
    # replace the subcommittees list with a dict from thomas_id to the subcommittee.
    utils.require_congress_legislators_repo()
    committees = {}
    for c in utils.yaml_load("congress-legislators/committees-current.yaml"):
        committees[c["thomas_id"]] = c
        if "house_committee_id" in c:
            committees[c["house_committee_id"] + "00"] = c
        c["subcommittees"] = dict((s["thomas_id"], s) for s in c.get("subcommittees", []))

    if "senate" in chambers:
        print "Fetching Senate meetings..."
        meetings = fetch_senate_committee_meetings(committees, options)
        print "Writing Senate meeting data to disk."
        utils.write_json(meetings, output_for("senate"))

    if "house" in chambers:
        if load_by == None:
            print "Fetching House meetings..."
            meetings = fetch_house_committee_meetings(committees, options)
        else:
            print "Fetching House meetings by event_id..."
            meetings = fetch_meeting_from_event_id(committees, options, load_by)

        print "Writing House meeting data to disk."
        utils.write_json(meetings, output_for("house"))

    # Write all meetings to a single file on disk.


# TODO: if these have unique IDs, maybe worth storing a file per-meeting.
def output_for(chamber):
    return utils.data_dir() + "/committee_meetings_%s.json" % chamber

# Parse the Senate committee meeting XML feed for meetings.
# To aid users of the data, attempt to assign GUIDs to meetings.
def fetch_senate_committee_meetings(committees, options):
    # Load any existing meetings file so we can recycle any GUIDs.
    existing_meetings = []
    output_file = output_for("senate")
    if os.path.exists(output_file):
        existing_meetings = json.load(open(output_file))

    options = dict(options)  # clone
    options["binary"] = True #

    meetings = []

    dom = lxml.etree.fromstring(utils.download(
        "http://www.senate.gov/general/committee_schedules/hearings.xml",
        "committee_schedule/senate.xml",
        options))

    for node in dom.xpath("meeting"):
        committee_id = unicode(node.xpath('string(cmte_code)'))
        if committee_id.strip() == "":
            continue  # "No committee hearings scheduled" placeholder
        occurs_at = unicode(node.xpath('string(date)'))
        room = unicode(node.xpath('string(room)'))
        topic = unicode(node.xpath('string(matter)'))

        occurs_at = datetime.datetime.strptime(occurs_at, "%d-%b-%Y %I:%M %p")
        topic = re.sub(r"\s+", " ", topic).strip()

        # Validate committee code.
        try:
            committee_code, subcommittee_code = re.match(r"(\D+)(\d+)$", committee_id).groups()
            if committee_code not in committees:
                raise ValueError(committee_code)
            if subcommittee_code == "00":
                subcommittee_code = None
            if subcommittee_code and subcommittee_code not in committees[committee_code]["subcommittees"]:
                raise ValueError(subcommittee_code)
        except:
            print "Invalid committee code", committee_id
            continue

        # See if this meeting already exists. If so, take its GUID.
        # Assume meetings are the same if they are for the same committee/subcommittee and
        # at the same time.
        for mtg in existing_meetings:
            if mtg["committee"] == committee_code and mtg.get("subcommittee", None) == subcommittee_code and mtg["occurs_at"] == occurs_at.isoformat():
                if options.get("debug", False):
                    print "[%s] Reusing gUID." % mtg["guid"]
                guid = mtg["guid"]
                break
        else:
            # Not found, so create a new ID.
            # TODO: Can we make this a human-readable ID?
            guid = unicode(uuid.uuid4())

        # Scrape the topic text for mentions of bill numbers.
        congress = utils.congress_from_legislative_year(utils.current_legislative_year(occurs_at))
        bills = []
        bill_number_re = re.compile(r"(hr|s|hconres|sconres|hjres|sjres|hres|sres)\s?(\d+)", re.I)
        for bill_match in bill_number_re.findall(topic.replace(".", "")):
            bills.append(bill_match[0].lower() + bill_match[1] + "-" + str(congress))

        # Create the meeting event.
        if options.get("debug", False):
            print "[senate][%s][%s] Found meeting in room %s at %s." % (committee_code, subcommittee_code, room, occurs_at.isoformat())

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

    print "[senate] Found %i meetings." % len(meetings)
    return meetings


# Scrape docs.house.gov for meetings.
# To aid users of the data, assign GUIDs to meetings piggy-backing off of the provided EventID.
def fetch_house_committee_meetings(committees, options):
    # Load any existing meetings file so we can recycle any GUIDs.
    existing_meetings = []
    output_file = output_for("house")
    if os.path.exists(output_file):
        existing_meetings = json.load(open(output_file))

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
        html = html.replace("&nbsp;", " ")  # who likes nbsp's? convert to spaces. but otherwise, entity is not recognized.

        # Parse and loop through the meetings listed in the committee feed.
        dom = lxml.etree.fromstring(html)

        # original start to loop
        for mtg in dom.xpath("channel/item"):
            eventurl = unicode(mtg.xpath("string(link)"))
  
            event_id = re.search(r"EventID=(\d+)$", eventurl).group(1)
            pubDate = datetime.datetime.fromtimestamp(mktime(parsedate(mtg.xpath("string(pubDate)"))))

            # skip old records of meetings, some of which just give error pages
            if pubDate < (datetime.datetime.now() - datetime.timedelta(days=60)):
                continue

            # Events can appear in multiple committee feeds if it is a joint meeting.
            if event_id in seen_meetings:
                logging.info("Duplicated multi-committee event: " + event_id)
                continue
            seen_meetings.add(event_id)

            # this loads the xml from the page and sends the xml to parse_house_committee_meeting
            load_xml_from_page(eventurl, options, existing_meetings, committees, event_id, meetings)

    print "[house] Found %i meetings." % len(meetings)
    return meetings


## load House meeting sequentially from event_id
def fetch_meeting_from_event_id(committees, options, load_id):
    existing_meetings = []
    output_file = output_for("house")
    if os.path.exists(output_file):
        existing_meetings = json.load(open(output_file))

    opts = dict(options)
    opts["binary"] = True

    meetings = []
    ids = load_id.split('-')
    current_id = int(ids[0])
    end_id = int(ids[1])

    while current_id <= end_id:
        event_id = str(current_id)
        event_url = "http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + event_id
        load_xml_from_page(event_url, options, existing_meetings, committees, event_id, meetings)
        current_id += 1
    
    print "[house] Found %i meetings." % len(meetings)
    return meetings

def load_xml_from_page(eventurl, options, existing_meetings, committees, event_id, meetings):  
    # Load the HTML page for the event and use the mechanize library to
    # submit the form that gets the meeting XML. TODO Simplify this when
    # the House makes the XML available at an actual URL.

    logging.info(eventurl)
    # I am moving this to the top
    # import mechanize
    br = mechanize.Browser()
    # open committee event page
    br.open(eventurl)
    br.select_form(nr=0)

    # mechanize parser failed to find these fields
    br.form.new_control("hidden", "__EVENTTARGET", {})
    br.form.new_control("hidden", "__EVENTARGUMENT", {})
    br.form.set_all_readonly(False)

    # set field values
    br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgXML"
    br["__EVENTARGUMENT"] = ""

    # Submit form and get and load XML response
    dom = lxml.etree.parse(br.submit())

    witness_info = look_for_witnesses(eventurl)

    # Parse the XML.
    try:
        meeting = parse_house_committee_meeting(event_id, dom, existing_meetings, committees, options, witness_info)
        if meeting != None:
            meetings.append(meeting)
        else:
            print(event_id, "postponed")
   
    except Exception as e:
        logging.error("Error parsing " + eventurl, exc_info=e)
        print(event_id, "error")

    look_for_witnesses(eventurl)


#look for witnesses in the house package xml    
def look_for_witnesses(eventurl):
    br = mechanize.Browser()
    # open committee event page
    br.open(eventurl)

    br.select_form(nr=0)

    # mechanize parser failed to find these fields
    br.form.new_control("hidden", "__EVENTTARGET", {})
    br.form.new_control("hidden", "__EVENTARGUMENT", {})
    br.form.set_all_readonly(False)

    # set field values
    br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgPackage"
    br["__EVENTARGUMENT"] = ""
    
    # get the info
    request = br.submit()

    ## read zipfile
    try:
        request_bytes = StringIO.StringIO(request.read())
        package = zipfile.ZipFile(request_bytes)
    except:
        message = "Error uploading zipfile uploaded for  %s "%(eventurl)
        print message
        return None
        #raise ValueError(message)


    for name in package.namelist():
        if "WList" in name:
            bytes = package.read(name)
            witness_tree = lxml.etree.fromstring(bytes)
            witness_info = parse_witness_list(witness_tree)
            return witness_info
    # it will return none if there is no witness list in the file
    return None

# parse xml for urls to testimony and witness information
def parse_witness_list(witness_tree):
    hearing_id = witness_tree.xpath("//@meeting-id")[0]
    hearing_witness_info = []
    for witness in witness_tree.xpath("panel/witness"):
        record = {"house_event_id": hearing_id}
        record["firstname"] =  witness.xpath("string(firstname)")
        record["middlename"] = witness.xpath("string(middlename)")
        record["lastname"] = witness.xpath("string(lastname)")
        record["position"] = witness.xpath("string(position)")
        record["organization"] = witness.xpath("string(organization)")
        record["witness_type"] = witness.xpath("string(witness-type)")
        record["documents"] = []
        for doc in witness.xpath("witness-documents/witness-document"):
            document = {}
            document["description"] = doc.xpath("string(description)")
            document["type"] = doc.xpath("string(type)")
            urls = []
            # I need to test this on a case with multiple documents per witness
            for files in doc.xpath("files/file"):
                urls.append(files.xpath("string(@doc-url)"))
            document["urls"] = urls
            record["documents"].append(document)
        hearing_witness_info.append(record)
    return hearing_witness_info


# Grab a House meeting out of the DOM for the XML feed.
def parse_house_committee_meeting(event_id, dom, existing_meetings, committees, options, witness_info):
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

    # Meeting documents include legislation, reports, etc.
    meeting_documents = []
    for doc in dom.xpath("//meeting-document"):
        document = {}
        document["description"] = doc.xpath("string(description)")
        document["type"] = doc.xpath("string(filename-metadata/doc-type)")
        document["legislation_number"] = doc.xpath("string(filename-metadata/legis-num)")
        document["legislation_stage"] = doc.xpath("string(filename-metadata/legis-stage)")
        document["version_number"] = doc.xpath("string(version-num)") 
        urls = []
        for url in doc.xpath("files/file"):
            urls.append(url.xpath("string(@doc-url)"))
        if len(urls) > 0:
            document["urls"] = urls
        meeting_documents.append(document)

    # Repeat the event for each listed committee or subcommittee, since our
    # data model supports only a single committee/subcommittee ID per event.

    orgs = []
    for c in dom.xpath("meeting-details/committees/committee-name"):
        if c.get("id") not in committees:
            raise ValueError("Invalid committee ID: " + c.get("id"))
        orgs.append((committees[c.get("id")]["thomas_id"], None))
    for sc in dom.xpath("meeting-details/subcommittees/committee-name"):
        if sc.get("id")[0:2] + "00" not in committees:
            raise ValueError("Invalid committee ID: " + sc.get("id"))
        c = committees[sc.get("id")[0:2] + "00"]
        if sc.get("id")[2:] not in c["subcommittees"]:
            logging.error("Invalid subcommittee code: " + sc.get("id"))
            continue
        orgs.append((c["thomas_id"], sc.get("id")[2:]))

    for committee_code, subcommittee_code in orgs:
        # See if this meeting already exists. If so, take its GUID.
        # Assume meetings are the same if they are for the same event ID and committee/subcommittee.
        for mtg in existing_meetings:

            if mtg["house_event_id"] == event_id and mtg.get("committee", None) == committee_code and mtg.get("subcommittee", None) == subcommittee_code:
                guid = mtg["guid"]
                break
        else:
            # Not found, so create a new ID.
            # TODO: when does this happen?
            guid = unicode(uuid.uuid4())

        url = "http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + event_id

        # return the parsed meeting
        if options.get("debug", False):
            print "[house][%s][%s] Found meeting in room %s at %s" % (committee_code, subcommittee_code, room, occurs_at.isoformat())

        results = {
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
            "url": url,
        }

        # witness information and documents are only added if there was a result
        if witness_info != None:
            results["witness_info"] = witness_info
        if len(meeting_documents) > 0:
            results["meeting_documents"] = meeting_documents 

        return results

