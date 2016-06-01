import os
import re
import datetime
import json
import lxml.etree
import uuid
import logging
import mechanize
import zipfile
import StringIO
import requests
import subprocess

from email.utils import parsedate
from time import mktime

from tasks import Task, current_legislative_year, congress_from_legislative_year

# to get text files their is a new dependency; you need to have pdftotext. 
# On Ubuntu, apt-get install poppler-utils. On OS X, install it via MacPorts 
# with port install poppler, or via Homebrew with brew install poppler.


class CommitteeMeetings(Task):

    def __init__(self, options=None, config=None):
        super(CommitteeMeetings, self).__init__(options, config)

    def run(self):
        """
        options:
            --chamber: "house" or "senate" to limit the parse to a single chamber
            --load_by: Takes a range of House Event IDs. Give it the beginning and end IDs with a dash between, otherwise,
                       it goes by the committee feeds.
            --docs=False: Don't download (& convert to text) House committee documents

        @return:
        @rtype:
        """

        # can limit it to one chamber
        chamber = self.options.get("chamber", None)
        if chamber and (chamber in ("house", "senate")):
            chambers = chamber
        else:
            chambers = ("house", "senate")

        load_by = self.options.get("load_by", None)

        # Load the committee metadata from the congress-legislators repository and make a
        # mapping from thomas_id and house_id to the committee dict. For each committee,
        # replace the subcommittees list with a dict from thomas_id to the subcommittee.
        self.require_congress_legislators_repo()
        committees = {}
        for c in self.storage.yaml_load("congress-legislators/committees-current.yaml"):
            committees[c["thomas_id"]] = c
            if "house_committee_id" in c:
                committees[c["house_committee_id"] + "00"] = c
            c["subcommittees"] = dict((s["thomas_id"], s) for s in c.get("subcommittees", []))

        if "senate" in chambers:
            print "Fetching Senate meetings..."
            meetings = self.fetch_senate_committee_meetings(committees)
            print "Writing Senate meeting data to disk."
            self.storage.write_json(meetings, self.output_for("senate"))

        if "house" in chambers:
            if load_by is None:
                print "Fetching House meetings..."
                meetings = self.fetch_house_committee_meetings(committees)
            else:
                print "Fetching House meetings by event_id..."
                meetings = self.fetch_meeting_from_event_id(committees, load_by)

            print "Writing House meeting data to disk."
            self.storage.write_json(meetings, self.output_for("house"))
            # Write all meetings to a single file on disk.

    def output_for(self, chamber):
        """

        @param chamber:
        @type chamber:
        @return:
        @rtype:
        """
        # TODO: if these have unique IDs, maybe worth storing a file per-meeting.
        return self.storage.data_dir + "/committee_meetings_%s.json" % chamber

    def fetch_senate_committee_meetings(self, committees):
        """
        Parse the Senate committee meeting XML feed for meetings.
        To aid users of the data, attempt to assign GUIDs to meetings.

        @param committees:
        @type committees:
        @return:
        @rtype:
        """
        # Load any existing meetings file so we can recycle any GUIDs.
        existing_meetings = []
        output_file = self.output_for("senate")
        if self.storage.exists(output_file):
            existing_meetings = json.load(self.storage.fs.open(output_file))

        options = dict(self.options)  # clone
        options["binary"] = True #
        options["force"] = True

        meetings = []

        dom = lxml.etree.fromstring(self.download(
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
            congress = congress_from_legislative_year(current_legislative_year(occurs_at))
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
                "bill_ids": bills,
            })

        print "[senate] Found %i meetings." % len(meetings)
        return meetings

    def fetch_house_committee_meetings(self, committees):
        """
        Scrape docs.house.gov for meetings.
        To aid users of the data, assign GUIDs to meetings piggy-backing off of the provided EventID.


        @param committees:
        @type committees:
        @return:
        @rtype:
        """
        # Load any existing meetings file so we can recycle any GUIDs.
        existing_meetings = []
        output_file = self.output_for("house")
        if self.storage.exists(output_file):
            existing_meetings = json.load(self.storage.fs.open(output_file))

        opts = dict(self.options)
        opts["binary"] = True
        opts["force"] = True

        meetings = []
        seen_meetings = set()

        # Scrape the committee listing page for a list of committees with scrapable events.
        committee_html = self.download("http://docs.house.gov/Committee/Committees.aspx", "committee_schedule/house_overview.html", self.options)
        for cmte in re.findall(r'<option value="(....)">', committee_html):
            if cmte not in committees:
                logging.error("Invalid committee code: " + cmte)
                continue

            # Download the feed for this committee.
            html = self.download(
                "http://docs.house.gov/Committee/RSS.ashx?Code=%s" % cmte,
                "committee_schedule/house_%s.xml" % cmte,
                opts)

            # It's not really valid?
            html = html.replace("&nbsp;", " ")  # who likes nbsp's? convert to spaces. but otherwise, entity is not recognized.
            #print html
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
                result = self.load_xml_from_page(eventurl, existing_meetings, committees, event_id, meetings)
                # if bad zipfile
                if result is False:
                    continue

        print "[house] Found %i meetings." % len(meetings)
        return meetings

    def fetch_meeting_from_event_id(self, committees, load_id):
        """
        Load House meeting sequentially from event_id

        @param committees:
        @type committees:
        @param load_id:
        @type load_id:
        @return:
        @rtype:
        """
        existing_meetings = []
        output_file = self.output_for("house")
        if self.storage.exists(output_file):
            existing_meetings = json.load(self.storage.fs.open(output_file))

        opts = dict(self.options)
        opts["binary"] = True
        opts["force"] = True

        meetings = []
        ids = load_id.split('-')
        current_id = int(ids[0])
        end_id = int(ids[1])

        while current_id <= end_id:
            event_id = str(current_id)
            event_url = "http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + event_id
            self.load_xml_from_page(event_url, existing_meetings, committees, event_id, meetings)
            # bad zipfile
            if self.load_xml_from_page is False:
                continue
            current_id += 1

        print "[house] Found %i meetings." % len(meetings)
        return meetings

    def load_xml_from_page(self, eventurl, existing_meetings, committees, event_id, meetings):
        """
        Load the HTML page for the event and use the mechanize library
        to submit the form that gets the meeting XML.
        TODO: Simplify this when the House makes the XML available at an actual URL.

        @param eventurl:
        @type eventurl:
        @param existing_meetings:
        @type existing_meetings:
        @param committees:
        @type committees:
        @param event_id:
        @type event_id:
        @param meetings:
        @type meetings:
        @return:
        @rtype:
        """

        logging.info(eventurl)
        package_info = self.extract_meeting_package(eventurl, event_id)
        if package_info is False:
            return False
        witnesses = package_info["witnesses"]
        uploaded_documents = package_info["uploaded_documents"]
        dom = package_info["dom"]

        # Parse the XML.
        try:
            meeting = self.parse_house_committee_meeting(event_id, dom, existing_meetings, committees, witnesses, uploaded_documents)
            if meeting is not None:
                meetings.append(meeting)
            else:
                print(event_id, "postponed")

        except Exception as e:
            logging.error("Error parsing " + eventurl, exc_info=e)
            print(event_id, "error")

    def extract_meeting_package(self, eventurl, event_id):
        """
        Look for witnesses and documents in the house meeting package

        @param eventurl:
        @type eventurl:
        @param event_id:
        @type event_id:
        @return:
        @rtype:
        """
        br = mechanize.Browser()
        # open committee event page
        br.open(eventurl)

        br.select_form(nr=0)

        # mechanize parser failed to find these fields
        br.form.new_control("hidden", "__EVENTTARGET", {})
        br.form.new_control("hidden", "__EVENTARGUMENT", {})
        br.form.set_all_readonly(False)

        # set field values
        if self.options.get("docs", True):
            # When we want documents, download the whole ZIP package.
            br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgPackage"
        else:
            # Otherwise, just download the metadata XML.
            br["__EVENTTARGET"] = "ctl00$MainContent$LinkButtonDownloadMtgXML"
        br["__EVENTARGUMENT"] = ""

        # get the info
        request = br.submit()

        # when just downloading the metadata XML, return the DOM and no other info
        if not self.options.get("docs", True):
            dom = lxml.etree.fromstring(request.read())
            return {"witnesses": None, "uploaded_documents": [], "dom": dom}

        # read zipfile
        try:
            request_bytes = StringIO.StringIO(request.read())
            package = zipfile.ZipFile(request_bytes)
        except:
            message = "Problem downloading zipfile: %s" % (event_id)
            print message
            return False

        # save documents in meeting package
        uploaded_documents = self.save_documents(package, event_id)
        witnesses = None
        # find meeting and witness xml
        for name in package.namelist():
            if ".xml" in name:
                if "WList" in name:
                    bytes = package.read(name)
                    witness_tree = lxml.etree.fromstring(bytes)
                    witness_info = self.parse_witness_list(witness_tree, uploaded_documents, event_id)
                    witnesses = witness_info["hearing_witness_info"]
                else:
                    bytes = package.read(name)
                    dom = lxml.etree.fromstring(bytes)

        # it will return none if there is no witness list in the file
        return {"witnesses": witnesses, "uploaded_documents": uploaded_documents, "dom": dom}

    # parse xml for urls to testimony and witness information
    def parse_witness_list(self, witness_tree, uploaded_documents, event_id):
        hearing_id = witness_tree.xpath("//@meeting-id")[0]
        hearing_witness_info = []
        #basic witness information
        for witness in witness_tree.xpath("panel/witness"):
            record = {"house_event_id": hearing_id}
            field_map = {
                'first_name': 'firstname',
                'middle_name': 'middlename',
                'last_name': 'lastname',
                'hornific': 'honorific',
                'position': 'position',
                'organization': 'organization',
                'witness_type': 'witness-type'
            }
            for ourfield, theirfield in field_map.items():
                record[ourfield] = witness.xpath('string({0})'.format(theirfield)) or None

            record["documents"] = []
            # documents related to that witness
            for doc in witness.xpath("witness-documents/witness-document"):
                document = {}
                published_on = doc.xpath("string(@publish-date)")
                try:
                    document["published_on"] = datetime.datetime.strptime(published_on, "%Y-%m-%dT%H:%M:%S.%f")
                except:
                    document["published_on"] = datetime.datetime.strptime(published_on, "%Y-%m-%dT%H:%M:%S")

                document["description"] = doc.xpath("string(description)") or None

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
                    document['type_name'] = types.get(doc_type, None)

                urls = []
                for files in doc.xpath("files/file"):
                    url = files.xpath("string(@doc-url)")
                    splinter = url.split('/')
                    doc_name = splinter[-1]
                    if doc_name not in uploaded_documents:
                        file_found = self.save_file(url, event_id)
                    else:
                        file_found = True
                    urls.append({"url":url, "file_found": file_found})

                document["urls"] = urls
                record["documents"].append(document)
            hearing_witness_info.append(record)
        return {"hearing_witness_info": hearing_witness_info}

    def parse_house_committee_meeting(self, event_id, dom, existing_meetings, committees, witnesses, uploaded_documents):
        """
        Grab a House meeting out of the DOM for the XML feed.


        @param event_id:
        @type event_id:
        @param dom:
        @type dom:
        @param existing_meetings:
        @type existing_meetings:
        @param committees:
        @type committees:
        @param witnesses:
        @type witnesses:
        @param uploaded_documents:
        @type uploaded_documents:
        @return:
        @rtype:
        """
        try:
            congress = int(dom.xpath("//@congress-num")[0])
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

        committee_names = []
        for com_xpath in ['meeting-details/committees', 'meeting-details/subcommittees']:
            for com in dom.xpath(com_xpath):
                comte = com.xpath('committee-name//text()')
                if comte is not None:
                    committee_names.append(comte)

        room = None
        for n in dom.xpath("meeting-details/meeting-location/capitol-complex"):
            room = n.xpath("string(building)") + " " + n.xpath("string(room)")

        bills = []
        for bill_id in dom.xpath("meeting-documents/meeting-document[@type='BR']/legis-num"):
            # validating bill ids
            bill_id = self.house_bill_id_formatter(bill_id.text, congress)
            if bill_id is not None:
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
                if types.has_key(doc_type):
                    document["type_name"] = types[doc_type]
                else:
                    document["type_name"] = None

            document["bioguide_id"] = doc.xpath("string(filename-metadata/bioguideID)")
            if document["bioguide_id"] == '':
                document["bioguide_id"] = None

            document["amendmendment_number"]= doc.xpath("string(filename-metadata/amdt-num)")

            bill_id = doc.xpath("string(filename-metadata/legis-num)")
            document["bill_id"] = self.house_bill_id_formatter(bill_id, congress)

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
                elif self.options.get("docs", True):
                    file_found = self.save_file(url, event_id)
                urls.append({"url": url, "file_found": file_found})

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
                guid = unicode(uuid.uuid4())

            url = "http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=" + event_id

            # return the parsed meeting
            if self.options.get("debug", False):
                print "[house][%s][%s] Found meeting in room %s at %s" % (committee_code, subcommittee_code, room, occurs_at.isoformat())

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
            if witnesses is not None:
                results["witnesses"] = witnesses
            if len(meeting_documents) > 0:
                results["meeting_documents"] = meeting_documents

            return results

    def save_documents(self, package, event_id):
        """
        Saves documents to disk, called in extract_meeting_package.

        @param package:
        @type package:
        @param event_id:
        @type event_id:
        @return:
        @rtype:
        """
        uploaded_documents = []

        # find/create directory
        folder = str(int(event_id)/100)
        output_dir = self.storage.data_dir + "/committee/meetings/house/%s/%s" % (folder, event_id)
        if not self.storage.exists(output_dir):
            self.storage.mkdir_p(output_dir)

        # loop through package and save documents
        for name in package.namelist():
            # for documents that are not xml
            if ".xml" not in name:
                try:
                    bytes = package.read(name)
                except:
                    print "Did not save to disk: file %s" % (name)
                    continue
                file_name = "%s/%s" % (output_dir, name)

                # save document
                logging.info("saved " + file_name)
                with open(file_name, 'wb') as document_file:
                    document_file.write(bytes)
                # try to make a text version
                text_doc = self.text_from_pdf(file_name)
                if text_doc is not None:
                    uploaded_documents.append(text_doc)
                uploaded_documents.append(name)

        return uploaded_documents

    def text_from_pdf(self, pdf_path):
        """
        Code from IG scraper project uses pdftotext to get text out of PDFs,
        then writes it and returns the /data-relative path.

        @param pdf_path: path to pdf to convert
        @type pdf_path: str
        @return: file name or None
        @rtype: (str|None)
        """
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

        if self.storage.exists(real_text_path):
            file_name = os.path.basename(real_text_path)
            return file_name
        else:
            logging.warn("Text not extracted to %s" % real_text_path)
            return None

    def save_file(self, url, event_id):
        """
        This is for files mentioned in the xml that do not appear in the meeting packet

        @param url:
        @type url:
        @param event_id:
        @type event_id:
        @return:
        @rtype:
        """

        # not saving xml but I cold be convinced otherwise
        if ".xml" in url: return False

        r = requests.get(url, stream=True)

        if r.status_code == requests.codes.ok:
            # find or create directory
            folder = str(int(event_id)/100)
            output_dir = self.storage.data_dir + "/committee/meetings/house/%s/%s" % (folder, event_id)
            if not self.storage.exists(output_dir):
                self.storage.mkdir_p(output_dir)
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
                    text_doc = self.text_from_pdf(file_name)
                return True
            except:
                print "Failed to save- %s" % (url)
                return False
        else:
            logging.info("failed to fetch: " + url)
            return False

    @staticmethod
    def house_bill_id_formatter(bill_id, congress):
        """
        Make sure there is a number

        @param bill_id:
        @type bill_id:
        @param congress:
        @type congress:
        @return:
        @rtype:
        """

        if bill_id is None or bill_id == '':
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

            if digit is False:
                return None
            # look for missing hr, though this risks mislabeling continuing and joint resolutions
            if alpha is False:
                bill_id = "hr" + bill_id
            else:
                bill_id = bill_id.replace(".", "").replace(" ", "").lower()

            bill_id = bill_id + "-" + str(congress)
            return bill_id
