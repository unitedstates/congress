from congress.tasks import utils
import os.path
import os
import re
import datetime
import json
import lxml.etree
import uuid
import logging
import mechanize
import zipfile
import io
import requests
import subprocess

from email.utils import parsedate
from time import mktime

# to get text files their is a new dependency; you need to have pdftotext. 
# On Ubuntu, apt-get install poppler-utils. On OS X, install it via MacPorts 
# with port install poppler, or via Homebrew with brew install poppler.

# options:
#
#    --chamber: "house" or "senate" to limit the parse to a single chamber
#    --load_by: Takes a range of House Event IDs. Give it the beginning and end IDs with a dash between, otherwise, it goes by the committee feeds.
#    --docs=False: Don't download (& convert to text) House committee documents

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
        print("Fetching Senate meetings...")
        meetings = fetch_senate_committee_meetings(committees, options)
        print("Writing Senate meeting data to disk.")
        utils.write_json(meetings, output_for("senate"))

    if "house" in chambers:
        if load_by == None:
            print("Fetching House meetings...")
            meetings = fetch_house_committee_meetings(committees, options)
        else:
            print("Fetching House meetings by event_id...")
            meetings = fetch_meeting_from_event_id(committees, options, load_by)

        print("Writing House meeting data to disk.")
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
    options["force"] = True

    meetings = []

    dom = lxml.etree.fromstring(utils.download(
        "https://www.senate.gov/general/committee_schedules/hearings.xml",
        "committee_schedule/senate.xml",
        options))

    for node in dom.xpath("meeting"):
        committee_id = str(node.xpath('string(cmte_code)'))
        if committee_id.strip() == "":
            continue  # "No committee hearings scheduled" placeholder
        occurs_at = str(node.xpath('string(date)'))
        room = str(node.xpath('string(room)'))
        topic = str(node.xpath('string(matter)'))

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
            print("Invalid committee code", committee_id)
            continue

        # See if this meeting already exists. If so, take its GUID.
        # Assume meetings are the same if they are for the same committee/subcommittee and
        # at the same time.
        for mtg in existing_meetings:
            if mtg["committee"] == committee_code and mtg.get("subcommittee", None) == subcommittee_code and mtg["occurs_at"] == occurs_at.isoformat():
                if options.get("debug", False):
                    print("[%s] Reusing gUID." % mtg["guid"])
                guid = mtg["guid"]
                break
        else:
            # Not found, so create a new ID.
            # TODO: Can we make this a human-readable ID?
            guid = str(uuid.uuid4())

        # Scrape the topic text for mentions of bill numbers.
        congress = utils.congress_from_legislative_year(utils.current_legislative_year(occurs_at))
        bills = []
        bill_number_re = re.compile(r"(hr|s|hconres|sconres|hjres|sjres|hres|sres)\s?(\d+)", re.I)
        for bill_match in bill_number_re.findall(topic.replace(".", "")):
            bills.append(bill_match[0].lower() + bill_match[1] + "-" + str(congress))

        # Create the meeting event.
        if options.get("debug", False):
            print("[senate][%s][%s] Found meeting in room %s at %s." % (committee_code, subcommittee_code, room, occurs_at.isoformat()))

        meetings.append({
            "chamber": "senate",
            "congress": congress,
            "guid": guid,
            "committee": committee_code,
            "subcommittee": subcommittee_code,
            "occurs_at": occurs_at.isoformat(),
            "room": room,
            "topic": topic,
            "bill_ids": bills,
        })

    print("[senate] Found %i meetings." % len(meetings))
    return meetings

# House

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
    opts["force"] = True

    meetings = []
    seen_meetings = set()

    # Scrape the committee listing page for a list of committees with scrapable events.
    committee_html = utils.download("http://docs.house.gov/Committee/Committees.aspx", "committee_schedule/house_overview.html", opts)
    for cmte in re.findall(r'<option value="(....)">', committee_html.decode('utf-8')):
        if cmte not in committees:
            logging.error("Invalid committee code: " + cmte)
            continue

        # Download the feed for this committee.
        logging.info("Fetching events for committee " + cmte)
        html = utils.download(
            "http://docs.house.gov/Committee/RSS.ashx?Code=%s" % cmte,
            "committee_schedule/house_%s.xml" % cmte,
            opts)

        # It's not really valid?
        html = html.replace(b"&nbsp;", b" ")  # who likes nbsp's? convert to spaces. but otherwise, entity is not recognized.
        #print(html)
        # Parse and loop through the meetings listed in the committee feed.
        dom = lxml.etree.fromstring(html)
        
        # original start to loop
        for mtg in dom.xpath("channel/item"):

            eventurl = str(mtg.xpath("string(link)"))
            event_id = re.search(r"EventID=(\d+)$", eventurl)
            if not event_id: continue # weird empty event showed up
            event_id = event_id.group(1)
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
            # if bad zipfile
            if load_xml_from_page == False: continue

    print("[house] Found %i meetings." % len(meetings))
    return meetings


## load House meeting sequentially from event_id
def fetch_meeting_from_event_id(committees, options, load_id):
    existing_meetings = []
    output_file = output_for("house")
    if os.path.exists(output_file):
        existing_meetings = json.load(open(output_file))

    opts = dict(options)
    opts["binary"] = True
    opts["force"] = True

    meetings = []
    ids = load_id.split('-')
    current_id = int(ids[0])
    end_id = int(ids[1])

    while current_id <= end_id:
        event_id = str(current_id)
        event_url = "http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + event_id
        load_xml_from_page(event_url, options, existing_meetings, committees, event_id, meetings)
        # bad zipfile
        if load_xml_from_page == False: continue
        current_id += 1
    
    print("[house] Found %i meetings." % len(meetings))
    return meetings


def load_xml_from_page(eventurl, options, existing_meetings, committees, event_id, meetings):  
    # Load the HTML page for the event and use the mechanize library to
    # submit the form that gets the meeting XML. TODO Simplify this when
    # the House makes the XML available at an actual URL.

    logging.info(eventurl)
    package_info = extract_meeting_package(eventurl, event_id, options)
    if package_info == False: return False
    witnesses = package_info["witnesses"]
    uploaded_documents = package_info["uploaded_documents"]
    dom = package_info["dom"]

    # Parse the XML.
    try:
        meeting = parse_house_committee_meeting(event_id, dom, existing_meetings, committees, options, witnesses, uploaded_documents)
        if meeting != None: # an active meeting record
            meetings.append(meeting)
   
    except Exception as e:
        logging.error("Error parsing " + eventurl, exc_info=e)


#look for witnesses and documents in the house meeting package    
def extract_meeting_package(eventurl, event_id, options):
    br = mechanize.Browser()
    # open committee event page
    br.open(eventurl)

    br.select_form(nr=0)

    # mechanize parser failed to find these fields
    br.form.new_control("hidden", "__EVENTTARGET", {})
    br.form.new_control("hidden", "__EVENTARGUMENT", {})
    br.form.set_all_readonly(False)

    # set field values
    if options.get("docs", True):
        # When we want documents, download the whole ZIP package.
        br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgPackage"
    else:
        # Otherwise, just download the metadata XML.
        br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgXML"
    br["__EVENTARGUMENT"] = ""
    
    # get the info
    request = br.submit()

    # when just downloading the metadata XML, return the DOM and no other info
    if not options.get("docs", True):
        try:
            dom = lxml.etree.fromstring(request.read())
        except lxml.etree.XMLSyntaxError as e:
            print(event_id, e)
            return False
        return {"witnesses": None, "uploaded_documents": [], "dom": dom}

    ## read zipfile
    try:
        request_bytes = io.BytesIO(request.read())
        package = zipfile.ZipFile(request_bytes)
    except:
        message = "Problem downloading zipfile: %s" % (event_id)
        print(message)
        return False

    # save documents in meeting package
    uploaded_documents = save_documents(package, event_id)
    witnesses = None
    # find meeting and witness xml
    for name in package.namelist():
        if ".xml" in name:
            if "WList" in name:
                bytes = package.read(name)
                witness_tree = lxml.etree.fromstring(bytes)
                witness_info = parse_witness_list(witness_tree, uploaded_documents, event_id)
                witnesses = witness_info["hearing_witness_info"]
            else:
                bytes = package.read(name)
                dom = lxml.etree.fromstring(bytes)

    # it will return none if there is no witness list in the file
    return {"witnesses": witnesses, "uploaded_documents": uploaded_documents, "dom": dom}


# parse xml for urls to testimony and witness information
def parse_witness_list(witness_tree, uploaded_documents, event_id):
    hearing_id = witness_tree.xpath("//@meeting-id")[0]
    hearing_witness_info = []
    #basic witness information
    for witness in witness_tree.xpath("panel/witness"):
        record = {"house_event_id": hearing_id}
        record["first_name"] =  witness.xpath("string(firstname)")
        if record["first_name"] == '':
            record["first_name"] = None
        record["middle_name"] = witness.xpath("string(middlename)")
        if record["middle_name"] == '':
            record["middle_name"] = None
        record["last_name"] = witness.xpath("string(lastname)")
        if record["last_name"] == '':
            record["last_name"] = None
        record["honorific"] = witness.xpath("string(honorific)")
        if record["honorific"] == '':
            record["honorific"] = None
        record["position"] = witness.xpath("string(position)")
        if record["position"] == '':
            record["position"] = None
        record["organization"] = witness.xpath("string(organization)")
        if record["organization"] == '':
            record["organization"] = None
        record["witness_type"] = witness.xpath("string(witness-type)")
        if record["witness_type"] == '':
            record["witness_type"] = None
        record["documents"] = []
        # documents related to that witness
        for doc in witness.xpath("witness-documents/witness-document"):
            document = {}
            published_on = doc.xpath("string(@publish-date)")
            try:
                document["published_on"] = datetime.datetime.strptime(published_on, "%Y-%m-%dT%H:%M:%S.%f")
            except:
                document["published_on"] = datetime.datetime.strptime(published_on, "%Y-%m-%dT%H:%M:%S")

            document["description"] = doc.xpath("string(description)")
            if document["description"] == '':
                document["description"] = None
            
            doc_type = doc.xpath("string(type)")
            if doc_type == '':
                document["type"] = None
                document["type_name"] = None
            else:
                document["type"] = doc_type
                types = {"CV": "Committee vote", "WS": "Witness statement", 
                    "WT": "Witness truth statement", "WB": "Witness biography",
                    "CR": "Committee report", "BR": "Bill", "FA": "Floor amendment",
                    "CA": "Committee amendment", "HT": "Transcript", "WD": "Witness document"}
                        # "SD": "" I don't know this one, the SD category covers a lot
                if doc_type in types:
                  document["type_name"] = types[doc_type]
                else:
                  document["type_name"] = None
            
            urls = []
            for files in doc.xpath("files/file"):
                url = files.xpath("string(@doc-url)")
                splinter = url.split('/')
                doc_name = splinter[-1]
                if doc_name not in uploaded_documents:
                    file_found = save_file(url, event_id)
                else:
                    file_found = True
                urls.append({"url":url, "file_found": file_found})
            
            document["urls"] = urls
            record["documents"].append(document)
        hearing_witness_info.append(record)
    return {"hearing_witness_info": hearing_witness_info}


# Grab a House meeting out of the DOM for the XML feed.
def parse_house_committee_meeting(event_id, dom, existing_meetings, committees, options, witnesses, uploaded_documents):
    try:
        congress = int(dom.xpath("//@congress-num")[0])
        occurs_at = dom.xpath("string(meeting-details/meeting-date/calendar-date)") + " " + dom.xpath("string(meeting-details/meeting-date/start-time)")
        occurs_at = datetime.datetime.strptime(occurs_at, "%Y-%m-%d %H:%M:%S")
    except:
        raise ValueError("Invalid meeting data (probably server error) in %s." % event_id)

    current_status = str(dom.xpath("string(current-status)"))
    if current_status not in ("S", "R"):
        # If status is "P" (postponed and not yet rescheduled) or "C" (cancelled),
        # don't include in output.
        return

    topic = dom.xpath("string(meeting-details/meeting-title)")

    committee_names = []
    for com in dom.xpath("meeting-details/committees"):
        comte = com.xpath("string(committee-name)")
        if comte != None:
            committee_names.append(com.xpath("string(committee-name)"))
    for scom in dom.xpath("meeting-details/subcommittees"):
        scomte = scom.xpath("string(committee-name)")
        if scomte != None:
            committee_names.append(scom.xpath("string(committee-name)"))

    room = None
    for n in dom.xpath("meeting-details/meeting-location/capitol-complex"):
        room = n.xpath("string(building)") + " " + n.xpath("string(room)")

    bills = []
    for bill_id in dom.xpath("meeting-documents/meeting-document[@type='BR']/legis-num"):
        # validating bill ids
        bill_id = house_bill_id_formatter(bill_id.text, congress)
        if bill_id != None:
            bills.append(bill_id)

    meeting_type = dom.xpath("//@meeting-type")[0]

    # Meeting documents include legislation, reports, etc.
    meeting_documents = []
    for doc in dom.xpath("//meeting-document"):
        document = {}
        published_on = doc.xpath("string(@publish-date)")
        try:
            document["published_on"] = datetime.datetime.strptime(published_on, "%Y-%m-%dT%H:%M:%S.%f")
        except:
            document["published_on"] = datetime.datetime.strptime(published_on, "%Y-%m-%dT%H:%M:%S")
        document["description"] = doc.xpath("string(description)")
        if document["description"] == '':
            document["description"] = None
        
        doc_type = doc.xpath("string(filename-metadata/doc-type)")
        if doc_type == '':
            document["type"] = None
            document["type_name"] = None
        else:
            document["type"] = doc_type
            types = { "CV": "Committee vote", "WS": "Witness statement", 
                    "WT": "Witness truth statement", "WB": "Witness biography",
                    "CR": "Committee report", "BR": "Bill", "FA": "Floor amendment",
                    "CA": "Committee amendment", "HT": "Transcript", "WD": "Witness document"}
                    # "SD": "" I don't know this one, the SD category covers a lot
            if doc_type in types:
              document["type_name"] = types[doc_type]
            else:
              document["type_name"] = None

        document["bioguide_id"] = doc.xpath("string(filename-metadata/bioguideID)")
        if document["bioguide_id"] == '':
            document["bioguide_id"] = None

        document["amendmendment_number"]= doc.xpath("string(filename-metadata/amdt-num)")

        bill_id = doc.xpath("string(filename-metadata/legis-num)")
        document["bill_id"] = house_bill_id_formatter(bill_id, congress)

        document["version_code"] = doc.xpath("string(filename-metadata/legis-stage)")
        if document["version_code"] == '':
            document["version_code"] = None
        
        urls = []
        for u in doc.xpath("files/file"):
            url = u.xpath("string(@doc-url)")
            splinter = url.split('/')
            doc_name = splinter[-1]
            file_found = False
            if doc_name in uploaded_documents:
                file_found = True
            elif options.get("docs", True):
                file_found = save_file(url, event_id)
            urls.append({"url":url, "file_found": file_found})

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
            if mtg["house_event_id"] == int(event_id) and mtg.get("committee", None) == committee_code and mtg.get("subcommittee", None) == subcommittee_code:
                guid = mtg["guid"]
                break
        else:
            # Not found, so create a new ID.
            # TODO: when does this happen?
            guid = str(uuid.uuid4())

        url = "http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + event_id

        # return the parsed meeting
        if options.get("debug", False):
            print("[house][%s][%s] Found meeting in room %s at %s" % (committee_code, subcommittee_code, room, occurs_at.isoformat()))

        results = {
            "chamber": "house",
            "congress": congress,
            "guid": guid,
            "committee": committee_code,
            "committee_names": committee_names,
            "subcommittee": subcommittee_code,
            "occurs_at": occurs_at.isoformat(),
            "room": room,
            "topic": topic,
            "bill_ids": bills,
            "house_meeting_type": meeting_type,
            "house_event_id": int(event_id),
            "url": url,
        }

        # witness information and documents are only added if there was a result
        if witnesses != None:
            results["witnesses"] = witnesses
        if len(meeting_documents) > 0:
            results["meeting_documents"] = meeting_documents 

        return results


# saves documents to disk, called in extract_meeting_package
def save_documents(package, event_id):
    uploaded_documents = []

    # find/create directory
    folder = str(int(event_id)/100)
    output_dir = utils.data_dir() + "/committee/meetings/house/%s/%s" % (folder, event_id)
    if not os.path.exists(output_dir): os.makedirs(output_dir)

    # loop through package and save documents    
    for name in package.namelist():
        # for documents that are not xml
        if ".xml" not in name:
            try:
                bytes = package.read(name)
            except:
                print("Did not save to disk: file %s" % (name))
                continue
            file_name = "%s/%s" % (output_dir, name)
            
            # save document
            logging.info("saved " + file_name)
            with open(file_name, 'wb') as document_file:
                document_file.write(bytes)
            # try to make a text version
            text_doc = text_from_pdf(file_name)
            if text_doc != None:
                uploaded_documents.append(text_doc)
            uploaded_documents.append(name)

    return uploaded_documents

# Code from IG scraper project
# uses pdftotext to get text out of PDFs,
# then writes it and returns the /data-relative path.
def text_from_pdf(pdf_path):
  try:
    subprocess.Popen(["pdftotext", "-v"], shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).communicate()
  except:
    logging.warn("Not processing PDF. Have you installed pdftotext?")
    return None

  real_pdf_path = pdf_path
  real_text_path = pdf_path.replace(".pdf", ".txt")

  try:
    subprocess.check_call("pdftotext -layout \"%s\" \"%s\"" % (real_pdf_path, real_text_path), shell=True)
  except subprocess.CalledProcessError as exc:
    logging.warn("Error extracting text for %s\n" % (real_text_path))
    return None

  if os.path.exists(real_text_path):
    file_name = os.path.basename(real_text_path)
    return file_name
  else:
    logging.warn("Text not extracted to %s" % real_text_path)
    return None     


# this is for files mentioned in the xml that do not appear in the meeting packet
def save_file(url, event_id):
    # not saving xml but I cold be convinced otherwise
    if ".xml" in url: return False

    r = requests.get(url, stream=True)

    if r.status_code == requests.codes.ok: 
        # find or create directory
        folder = str(int(event_id)/100)
        output_dir = utils.data_dir() + "/committee/meetings/house/%s/%s" % (folder, event_id)
        if not os.path.exists(output_dir): os.makedirs(output_dir)
        # get file name
        splinter = url.split('/')
        name = splinter[-1]
        file_name = "%s/%s" % (output_dir, name)
        # try to save

        try:
            logging.info("saved " + url + " to " + file_name)
            with open(file_name, 'wb') as document_file:
                document_file.write(r.content)
            if ".pdf" in file_name:
                text_doc = text_from_pdf(file_name)
            return True
        except:
            print("Failed to save- %s" % (url))
            return False
    else:
        logging.info("failed to fetch: " + url)
        return False
            

def house_bill_id_formatter(bill_id, congress):
    # make sure there is a number
    if bill_id == None or bill_id == '':
        return None
    else:
        bill_id = bill_id.strip()
        digit = False
        alpha = False
        for char in bill_id:
            if char.isdigit():
                digit = True
            if char.isalpha():
                alpha = True
        
        if digit == False:
            return None
        # look for missing hr, though this risks mislabeling continuing and joint resolutions
        if alpha == False:
            bill_id = "hr" + bill_id
        else:
            bill_id = bill_id.replace(".", "").replace(" ", "").lower()
        
        bill_id = bill_id + "-" + str(congress)
        return bill_id






