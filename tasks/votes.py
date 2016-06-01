import json
import iso8601
import os
import os.path
import re
import urlparse
import time
import datetime
from lxml import html, etree
import logging

from tasks import Task, current_congress, uniq, get_congress_first_year, merge, format_datetime, make_node


class Votes(Task):

    def __init__(self, options, config):
        super(Votes, self).__init__(options, config)

    def run(self):
        vote_id = self.options.get('vote_id', None)

        if vote_id:
            vote_chamber, vote_number, congress, session_year = self.split_vote_id(vote_id)
            to_fetch = [vote_id]
        else:
            congress = self.options.get('congress', None)
            if congress:
                session_year = self.options.get('session', None)
                if not session_year:
                    logging.error("If you provide a --congress, provide a --session year.")
                    return None
            else:
                congress = current_congress()
                session_year = self.options.get('session', str(datetime.datetime.now().year))

            chamber = self.options.get('chamber', None)

            if chamber == "house":
                to_fetch = self.vote_ids_for_house(congress, session_year)
            elif chamber == "senate":
                to_fetch = self.vote_ids_for_senate(congress, session_year)
            else:
                to_fetch = (self.vote_ids_for_house(congress, session_year) or []) + (self.vote_ids_for_senate(congress, session_year) or [])

            if not to_fetch:
                if not self.options.get("fast", False):
                    logging.error("Error figuring out which votes to download, aborting.")
                else:
                    logging.warn("No new or recent votes.")
                return None

            limit = self.options.get('limit', None)
            if limit:
                to_fetch = to_fetch[:int(limit)]

        if self.options.get('pages_only', False):
            return None

        logging.warn("Going to fetch %i votes from congress #%s session %s" % (len(to_fetch), congress, session_year))

        self.process_set(to_fetch, self.fetch_vote)

    def vote_ids_for_house(self, congress, session_year):
        """
        Page through listing of House votes of a particular congress and session

        @param congress:
        @type congress:
        @param session_year:
        @type session_year:
        @return:
        @rtype:
        """
        vote_ids = []

        index_page = "http://clerk.house.gov/evs/%s/index.asp" % session_year
        group_page = r"ROLL_(\d+)\.asp"
        link_pattern = r"http://clerk.house.gov/cgi-bin/vote.asp\?year=%s&rollnumber=(\d+)" % session_year

        # download index page, find the matching links to the paged listing of votes
        page = self.download(
            index_page,
            "%s/votes/%s/pages/house.html" % (congress, session_year),
            self.options)

        if not page:
            logging.error("Couldn't download House vote index page, aborting")
            return None

        # extract matching links
        doc = html.document_fromstring(page)
        links = doc.xpath(
            "//a[re:match(@href, '%s')]" % group_page,
            namespaces={"re": "http://exslt.org/regular-expressions"})

        for link in links:
            # get some identifier for this inside page for caching
            grp = re.match(group_page, link.get("href")).group(1)

            # download inside page, find the matching links
            page = self.download(
                urlparse.urljoin(index_page, link.get("href")),
                "%s/votes/%s/pages/house_%s.html" % (congress, session_year, grp),
                self.options)

            if not page:
                logging.error("Couldn't download House vote group page (%s), aborting" % grp)
                continue

            doc = html.document_fromstring(page)
            votelinks = doc.xpath(
                "//a[re:match(@href, '%s')]" % link_pattern,
                namespaces={"re": "http://exslt.org/regular-expressions"})

            for votelink in votelinks:
                num = re.match(link_pattern, votelink.get("href")).group(1)
                vote_id = "h" + num + "-" + str(congress) + "." + session_year
                if not self.should_process(vote_id):
                    continue
                vote_ids.append(vote_id)

        return uniq(vote_ids)

    def vote_ids_for_senate(self, congress, session_year):
        session_num = int(session_year) - get_congress_first_year(int(congress)) + 1

        vote_ids = []

        page = self.download(
            "http://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_%s_%d.xml" % (congress, session_num),
            "%s/votes/%s/pages/senate.xml" % (congress, session_year),
            merge(self.options, {'binary': True})
        )

        if not page:
            logging.error("Couldn't download Senate vote XML index, aborting")
            return None

        dom = etree.fromstring(page)

        # Sanity checks.
        if int(congress) != int(dom.xpath("congress")[0].text):
            logging.error("Senate vote XML returns the wrong Congress: %s" % dom.xpath("congress")[0].text)
            return None
        if int(session_year) != int(dom.xpath("congress_year")[0].text):
            logging.error("Senate vote XML returns the wrong session: %s" % dom.xpath("congress_year")[0].text)
            return None

        # Get vote list.
        for vote in dom.xpath("//vote"):
            num = int(vote.xpath("vote_number")[0].text)
            vote_id = "s" + str(num) + "-" + str(congress) + "." + session_year
            if not self.should_process(vote_id):
                continue
            vote_ids.append(vote_id)
        return vote_ids

    def output_for_vote(self, vote_id, format):
        """

        @param vote_id:
        @type vote_id:
        @param format:
        @type format:
        @return:
        @rtype:
        """
        vote_chamber, vote_number, vote_congress, vote_session_year = self.split_vote_id(vote_id)
        return "%s/%s/votes/%s/%s%s/%s" % (self.storage.data_dir, vote_congress, vote_session_year, vote_chamber, vote_number, "data.%s" % format)

    def should_process(self, vote_id):
        if not self.options.get("fast", False):
            return True

        # If --fast is used, only download new votes or votes taken in the last
        # three days (when most vote changes and corrections should occur).
        f = self.output_for_vote(vote_id, "json")
        if not os.path.exists(f):
            return True

        v = json.load(open(f))
        now = self.EASTERN_TIME_ZONE.localize(datetime.datetime.now())
        return (now - iso8601.parse_date(v["date"])) < datetime.timedelta(days=3)

    def fetch_vote(self, vote_id):
        logging.info("\n[%s] Fetching..." % vote_id)

        vote_chamber, vote_number, vote_congress, vote_session_year = self.split_vote_id(vote_id)

        if vote_chamber == "h":
            url = "http://clerk.house.gov/evs/%s/roll%03d.xml" % (vote_session_year, int(vote_number))
        else:
            session_num = int(vote_session_year) - get_congress_first_year(int(vote_congress)) + 1
            url = "http://www.senate.gov/legislative/LIS/roll_call_votes/vote%d%d/vote_%d_%d_%05d.xml" % (int(vote_congress), session_num, int(vote_congress), session_num, int(vote_number))

        # fetch vote XML page
        body = self.download(
            url,
            "%s/votes/%s/%s%s/%s%s.xml" % (vote_congress, vote_session_year, vote_chamber, vote_number, vote_chamber, vote_number),
            merge(self.options, {'binary': True}),
        )

        if not body:
            return {'saved': False, 'ok': False, 'reason': "failed to download"}

        if self.options.get("download_only", False):
            return {'saved': False, 'ok': True, 'reason': "requested download only"}

        if "This vote was vacated" in body:
            # Vacated votes: 2011-484, 2012-327, ...
            # Remove file, since it may previously have existed with data.
            for f in (self.output_for_vote(vote_id, "json"), self.output_for_vote(vote_id, "xml")):
                if self.storage.exists(f):
                    self.storage.remove(f)
            return {'saved': False, 'ok': True, 'reason': "vote was vacated"}

        dom = etree.fromstring(body)

        vote = {
            'vote_id': vote_id,
            'chamber': vote_chamber,
            'congress': int(vote_congress),
            'session': vote_session_year,
            'number': int(vote_number),
            'updated_at': datetime.datetime.fromtimestamp(time.time()),
            'source_url': url,
        }

        # do the heavy lifting

        if vote_chamber == "h":
            self.parse_house_vote(dom, vote)
        elif vote_chamber == "s":
            self.parse_senate_vote(dom, vote)

        # output and return

        self.output_vote(vote)

        return {'ok': True, 'saved': True}

    def parse_house_vote(self, dom, vote):
        def parse_date(d):
            d = d.strip()
            if " " in d:
                return datetime.datetime.strptime(d, "%d-%b-%Y %I:%M %p")
            else:  # some votes have no times?
                print vote
                return datetime.datetime.strptime(d, "%d-%b-%Y")

        vote["date"] = parse_date(str(dom.xpath("string(vote-metadata/action-date)")) + " " + str(dom.xpath("string(vote-metadata/action-time)")))
        vote["question"] = unicode(dom.xpath("string(vote-metadata/vote-question)"))
        vote["type"] = unicode(dom.xpath("string(vote-metadata/vote-question)"))
        vote["type"] = self.normalize_vote_type(vote["type"])
        if unicode(dom.xpath("string(vote-metadata/vote-desc)")).startswith("Impeaching "):
            vote["category"] = "impeachment"
        else:
            vote["category"] = self.get_vote_category(vote["question"])
        vote["subject"] = unicode(dom.xpath("string(vote-metadata/vote-desc)"))
        if not vote["subject"]:
            del vote["subject"]

        vote_types = {"YEA-AND-NAY": "1/2", "2/3 YEA-AND-NAY": "2/3", "3/5 YEA-AND-NAY": "3/5", "1/2": "1/2", "2/3": "2/3", "QUORUM": "QUORUM", "RECORDED VOTE": "1/2", "2/3 RECORDED VOTE": "2/3", "3/5 RECORDED VOTE": "3/5"}
        vote["requires"] = vote_types.get(str(dom.xpath("string(vote-metadata/vote-type)")), "unknown")

        vote["result_text"] = unicode(dom.xpath("string(vote-metadata/vote-result)"))
        vote["result"] = unicode(dom.xpath("string(vote-metadata/vote-result)"))

        bill_num = unicode(dom.xpath("string(vote-metadata/legis-num)"))
        if bill_num not in ("", "QUORUM", "JOURNAL", "MOTION", "ADJOURN") and not re.match(r"QUORUM \d+$", bill_num):
            bill_types = {"S": "s", "S CON RES": "sconres", "S J RES": "sjres", "S RES": "sres", "H R": "hr", "H CON RES": "hconres", "H J RES": "hjres", "H RES": "hres"}
            try:
                bill_type, bill_number = bill_num.rsplit(" ", 1)
                vote["bill"] = {
                    "congress": vote["congress"],
                    "type": bill_types[bill_type],
                    "number": int(bill_number)
                }
            except ValueError:  # rsplit failed, i.e. there is no space in the legis-num field
                raise Exception("Unhandled bill number in the legis-num field")

        if str(dom.xpath("string(vote-metadata/amendment-num)")):
            vote["amendment"] = {
                "type": "h-bill",
                "number": int(str(dom.xpath("string(vote-metadata/amendment-num)"))),
                "author": unicode(dom.xpath("string(vote-metadata/amendment-author)")),
            }

        # Assemble a complete question from the vote type, amendment, and bill number.
        if "amendment" in vote and "bill" in vote:
            vote["question"] += ": Amendment %s to %s" % (vote["amendment"]["number"], unicode(dom.xpath("string(vote-metadata/legis-num)")))
        elif "amendment" in vote:
            vote["question"] += ": Amendment %s to [unknown bill]" % vote["amendment"]["number"]
        elif "bill" in vote:
            vote["question"] += ": " + unicode(dom.xpath("string(vote-metadata/legis-num)"))
            if "subject" in vote:
                vote["question"] += " " + vote["subject"]
        elif "subject" in vote:
            vote["question"] += ": " + vote["subject"]

        # Count up the votes.
        vote["votes"] = {}  # by vote type

        def add_vote(vote_option, voter):
            vote["votes"].setdefault(vote_option, []).append(voter)

        # Ensure the options are noted, even if no one votes that way.
        if unicode(dom.xpath("string(vote-metadata/vote-question)")) == "Election of the Speaker":
            for n in dom.xpath('vote-metadata/vote-totals/totals-by-candidate/candidate'):
                vote["votes"][n.text] = []
        elif unicode(dom.xpath("string(vote-metadata/vote-question)")) == "Call of the House":
            for n in dom.xpath('vote-metadata/vote-totals/totals-by-candidate/candidate'):
                vote["votes"][n.text] = []
        elif "YEA-AND-NAY" in dom.xpath('string(vote-metadata/vote-type)'):
            vote["votes"]['Yea'] = []
            vote["votes"]['Nay'] = []
            vote["votes"]['Present'] = []
            vote["votes"]['Not Voting'] = []
        else:
            vote["votes"]['Aye'] = []
            vote["votes"]['No'] = []
            vote["votes"]['Present'] = []
            vote["votes"]['Not Voting'] = []

        for member in dom.xpath("vote-data/recorded-vote"):
            display_name = unicode(member.xpath("string(legislator)"))
            state = str(member.xpath("string(legislator/@state)"))
            party = str(member.xpath("string(legislator/@party)"))
            vote_cast = str(member.xpath("string(vote)"))
            bioguideid = str(member.xpath("string(legislator/@name-id)"))
            add_vote(vote_cast, {
                "id": bioguideid,
                "state": state,
                "party": party,
                "display_name": display_name,
            })

        # Through the 107th Congress and sporadically in more recent data, the bioguide field
        # is not present. Look up the Members' bioguide IDs by name/state/party/date. This works
        # reasonably well, but there are many gaps. When there's a gap, it raises an exception
        # and the file is not saved.
        #
        # Take into account that the vote may list both a "Smith" and a "Smith, John". Resolve
        # "Smith" by process of elimination, i.e. he must not be whoever "Smith, John" resolved
        # to. To do that, process the voters from longest specified display name to shortest.
        #
        # One example of a sporadic case is 108th Congress, 2nd session (2004), votes 405 through
        # 544, where G.K. Butterfield's bioguide ID is 000000. It should have been B001251.
        # See https://github.com/unitedstates/congress/issues/46.

        seen_ids = set()
        all_voters = sum(vote["votes"].values(), [])
        all_voters.sort(key=lambda v: len(v["display_name"]), reverse=True)  # process longer names first
        for v in all_voters:
            if v["id"] not in ("", "0000000"):
                continue

            # here are wierd cases from h610-103.1993 that confound our name lookup since it has the wrong state abbr
            if v["state"] == "XX":
                for st in ("PR", "AS", "GU", "VI", "DC"):
                    if v["display_name"].endswith(" (%s)" % st):
                        v["state"] = st

            # get the last name without the state abbreviation in parenthesis, if it is present
            display_name = v["display_name"].strip()
            ss = " (%s)" % v["state"]
            if display_name.endswith(ss):
                display_name = display_name[:-len(ss)].strip()

            # wrong party in upstream data
            if vote["vote_id"] == "h2-106.1999" and display_name == "Hastert":
                v["id"] = "H000323"
                continue

            # dead man recorded as Not Voting (he died the day before, so none of our roles match the vote date)
            if vote["vote_id"] == "h306-106.1999" and display_name == "Brown" and v["state"] == "CA":
                v["id"] = "B000918"
                continue

            # look up ID
            v["id"] = self.lookup_legislator(vote["congress"], "rep", display_name, v["state"], v["party"], vote["date"], "bioguide", exclude=seen_ids)

            if v["id"] is None:
                logging.error("[%s] Missing bioguide ID and name lookup failed for %s (%s-%s on %s)" % (vote["vote_id"], display_name, v["state"], v["party"], vote["date"]))
                raise Exception("No bioguide ID for %s (%s-%s)" % (display_name, v["state"], v["party"]))
            else:
                if vote["congress"] > 107:
                    logging.warn("[%s] Used name lookup for %s because bioguide ID was missing." % (vote["vote_id"], v["display_name"]))
                seen_ids.add(v["id"])

    def parse_senate_vote(self, dom, vote):
        def parse_date(d):
            return datetime.datetime.strptime(d, "%B %d, %Y, %I:%M %p")

        vote["date"] = parse_date(dom.xpath("string(vote_date)"))
        if len(dom.xpath("modify_date")) > 0:
            vote["record_modified"] = parse_date(dom.xpath("string(modify_date)"))  # some votes like s1-110.2008 don't have a modify_date
        vote["question"] = unicode(dom.xpath("string(vote_question_text)"))
        if vote["question"] == "":
            vote["question"] = unicode(dom.xpath("string(question)"))  # historical votes?
        vote["type"] = unicode(dom.xpath("string(vote_question)"))
        if vote["type"] == "":
            vote["type"] = vote["question"]
        vote["type"] = self.normalize_vote_type(vote["type"])
        vote["category"] = self.get_vote_category(vote["type"])
        vote["subject"] = unicode(dom.xpath("string(vote_title)"))
        vote["requires"] = unicode(dom.xpath("string(majority_requirement)"))
        vote["result_text"] = unicode(dom.xpath("string(vote_result_text)"))
        vote["result"] = unicode(dom.xpath("string(vote_result)"))

        bill_types = {"S.": "s", "S.Con.Res.": "sconres", "S.J.Res.": "sjres", "S.Res.": "sres", "H.R.": "hr", "H.Con.Res.": "hconres", "H.J.Res.": "hjres", "H.Res.": "hres"}

        if unicode(dom.xpath("string(document/document_type)")):
            if dom.xpath("string(document/document_type)") == "PN":
                vote["nomination"] = {
                    "number": unicode(dom.xpath("string(document/document_number)")),
                    "title": unicode(dom.xpath("string(document/document_title)")),
                }
                vote["question"] += ": " + vote["nomination"]["title"]
            elif dom.xpath("string(document/document_type)") == "Treaty Doc.":
                vote["treaty"] = {
                    "title": unicode(dom.xpath("string(document/document_title)")),
                }
            else:
                vote["bill"] = {
                    "congress": int(dom.xpath("number(document/document_congress|congress)")),  # some historical files don't have document/document_congress so take the first of document/document_congress or the top-level congress element as a fall-back
                    "type": bill_types[unicode(dom.xpath("string(document/document_type)"))],
                    "number": int(dom.xpath("number(document/document_number)")),
                    "title": unicode(dom.xpath("string(document/document_title)")),
                }

        if unicode(dom.xpath("string(amendment/amendment_number)")):
            m = re.match(r"^S.Amdt. (\d+)", unicode(dom.xpath("string(amendment/amendment_number)")))
            if m:
                vote["amendment"] = {
                    "type": "s",
                    "number": int(m.group(1)),
                    "purpose": unicode(dom.xpath("string(amendment/amendment_purpose)")),
                }

            amendment_to = unicode(dom.xpath("string(amendment/amendment_to_document_number)"))
            if "Treaty" in amendment_to:
                treaty, number = amendment_to.split("-")
                vote["treaty"] = {
                    "congress": vote["congress"],
                    "number": number,
                }
            elif " " in amendment_to:
                bill_type, bill_number = amendment_to.split(" ")
                vote["bill"] = {
                    "congress": vote["congress"],
                    "type": bill_types[bill_type],
                    "number": int(bill_number),
                    "title": unicode(dom.xpath("string(amendment/amendment_to_document_short_title)")),
                }
            else:
                # Senate votes:
                # 102nd Congress, 2nd session (1992): 247, 248, 250; 105th Congress, 2nd session (1998): 106 through 116; 108th Congress, 1st session (2003): 41, 42
                logging.warn("Amendment without corresponding bill info in %s " % vote["vote_id"])

        # Count up the votes.
        vote["votes"] = {}

        def add_vote(vote_option, voter):
            if vote_option == "Present, Giving Live Pair":
                vote_option = "Present"
            vote["votes"].setdefault(vote_option, []).append(voter)

            # In the 101st Congress, 1st session (1989), votes 133 through 136 lack lis_member_id nodes.
            if voter != "VP" and voter["id"] == "":
                voter["id"] = self.lookup_legislator(vote["congress"], "sen", voter["last_name"], voter["state"], voter["party"], vote["date"], "lis")
                if voter["id"] == None:
                    logging.error("[%s] Missing lis_member_id and name lookup failed for %s" % (vote["vote_id"], voter["last_name"]))
                    raise Exception("Could not find ID for %s (%s-%s)" % (voter["last_name"], voter["state"], voter["party"]))
                else:
                    logging.info("[%s] Missing lis_member_id, falling back to name lookup for %s" % (vote["vote_id"], voter["last_name"]))

        # Ensure the options are noted, even if no one votes that way.
        if unicode(dom.xpath("string(question)")) == "Guilty or Not Guilty":
            vote["votes"]['Guilty'] = []
            vote["votes"]['Not Guilty'] = []
        else:
            vote["votes"]['Yea'] = []
            vote["votes"]['Nay'] = []
        vote["votes"]['Present'] = []
        vote["votes"]['Not Voting'] = []

        # VP tie-breaker?
        if str(dom.xpath("string(tie_breaker/by_whom)")):
            add_vote(str(dom.xpath("string(tie_breaker/tie_breaker_vote)")), "VP")

        for member in dom.xpath("members/member"):
            add_vote(str(member.xpath("string(vote_cast)")), {
                "id": str(member.xpath("string(lis_member_id)")),
                "state": str(member.xpath("string(state)")),
                "party": str(member.xpath("string(party)")),
                "display_name": unicode(member.xpath("string(member_full)")),
                "first_name": str(member.xpath("string(first_name)")),
                "last_name": str(member.xpath("string(last_name)")),
            })

    def output_vote(self, vote, id_type=None):
        logging.info("[%s] Writing to disk..." % vote['vote_id'])

        # output JSON - so easy!
        self.storage.write(
            json.dumps(vote, sort_keys=True, indent=2, default=format_datetime),
            self.output_for_vote(vote["vote_id"], "json"),
            options=self.options
        )

        xmloutput = self.generate_xml(vote, id_type)

        self.storage.write(
            xmloutput,
            self.output_for_vote(vote['vote_id'], "xml"),
            options=self.options
        )

    def generate_xml(self, vote, id_type=None):

        # What kind of IDs are we passed for Members of Congress?
        # For current data, we infer from the chamber. For historical data from voteview,
        # we're passed the type in id_type, which is set to "bioguide".
        if not id_type:
            id_type = ("bioguide" if vote["chamber"] == "h" else "lis")

        # output XML
        root = etree.Element("roll")

        root.set("where", "house" if vote['chamber'] == "h" else "senate")
        root.set("session", str(vote["congress"]))
        root.set("year", str(vote["date"].year))
        root.set("roll", str(vote["number"]))
        if "voteview" in vote["source_url"]:
            root.set("source", "keithpoole")
        else:
            root.set("source", "house.gov" if vote["chamber"] == "h" else "senate.gov")

        root.set("datetime", format_datetime(vote['date']))
        root.set("updated", format_datetime(vote['updated_at']))

        def get_votes(option):
            return len(vote["votes"].get(option, []))
        root.set("aye", str(get_votes("Yea") + get_votes("Aye")))
        root.set("nay", str(get_votes("Nay") + get_votes("No")))
        root.set("nv", str(get_votes("Not Voting")))
        root.set("present", str(get_votes("Present")))

        make_node(root, "category", vote["category"])
        make_node(root, "type", vote["type"])
        make_node(root, "question", vote["question"])
        make_node(root, "required", vote["requires"])
        make_node(root, "result", vote["result"])

        if vote.get("bill"):
            govtrack_type_codes = {'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc'}
            make_node(root, "bill", None, session=str(vote["bill"]["congress"]), type=govtrack_type_codes[vote["bill"]["type"]], number=str(vote["bill"]["number"]))

        if "amendment" in vote:
            n = make_node(root, "amendment", None)
            if vote["amendment"]["type"] == "s":
                n.set("ref", "regular")
                n.set("session", str(vote["congress"]))
                n.set("number", "s" + str(vote["amendment"]["number"]))
            elif vote["amendment"]["type"] == "h-bill":
                n.set("ref", "bill-serial")
                n.set("session", str(vote["congress"]))
                n.set("number", str(vote["amendment"]["number"]))

        # well-known keys for certain vote types: +/-/P/0
        option_keys = {"Aye": "+", "Yea": "+", "Nay": "-", "No": "-", "Present": "P", "Not Voting": "0", "Guilty": "+", "Not Guilty": "-" }

        # preferred order of output: ayes, nays, present, then not voting, and similarly for guilty/not-guilty
        # and handling other options like people's names for votes for the Speaker.
        option_sort_order = ('Aye', 'Yea', 'Guilty', 'No', 'Nay', 'Not Guilty', 'OTHER', 'Present', 'Not Voting')
        options_list = sorted(vote["votes"].keys(), key=lambda o: option_sort_order.index(o) if o in option_sort_order else option_sort_order.index("OTHER"))
        for option in options_list:
            if option not in option_keys:
                option_keys[option] = option
            make_node(root, "option", option, key=option_keys[option])

        for option in options_list:
            for v in vote["votes"][option]:
                n = make_node(root, "voter", None)
                if v == "VP":
                    n.set("id", "0")
                    n.set("VP", "1")
                elif not self.options.get("govtrack", False):
                    n.set("id", str(v["id"]))
                else:
                    pass
                    # TODO: this is ridiculously complicated id creation schema, does anybody even use it?
                    #n.set("id", str(utils.get_govtrack_person_id(id_type, v["id"])))
                n.set("vote", option_keys[option])
                n.set("value", option)
                if v != "VP":
                    n.set("state", v["state"])
                    if v.get("voteview_votecode_extra") is not None:
                        n.set("voteview_votecode_extra", v["voteview_votecode_extra"])

        xmloutput = etree.tostring(root, pretty_print=True, encoding="utf8")

        # mimick two hard line breaks in GovTrack's legacy output to ease running diffs
        xmloutput = re.sub('(source=".*?") ', r"\1\n  ", xmloutput)
        xmloutput = re.sub('(updated=".*?") ', r"\1\n  ", xmloutput)

        return xmloutput

    @staticmethod
    def normalize_vote_type(vote_type):
        """
        Takes the "type" field of a House or Senate vote and returns a
        normalized version of the same, as best as possible.

        Note that these allow .* after each pattern, so some things look like
        no-ops but they are really truncating the type after the specified text.

        @param vote_type:
        @type vote_type:
        @return:
        @rtype:
        """
        mapping = (
            (r"^On the Resolution of Ratification.*", "On the Resolution of Ratification"), # order matters so must go before other resolutions
            (r"On (Agreeing to )?the (Joint |Concurrent )?Resolution", "On the $2Resolution"),
            (r"On (Agreeing to )?the Conference Report", "On the Conference Report"),
            (r"On (Agreeing to )?the (En Bloc )?Amendments?", "On the Amendment"),
            (r"On (?:the )?Motion to Recommit", "On the Motion to Recommit"),
            (r"(On Motion to )?(Concur in|Concurring|On Concurring|Agree to|On Agreeing to) (the )?Senate (Amendment|amdt|Adt)s?", "Concurring in the Senate Amendment"),
            (r"(On Motion to )?Suspend (the )?Rules and (Agree|Concur|Pass)(, As Amended)", "On Motion to Suspend the Rules and $3$4"),
            (r"Will the House Now Consider the Resolution|On (Question of )?Consideration of the Resolution", "On Consideration of the Resolution"),
            (r"On (the )?Motion to Adjourn", "On the Motion to Adjourn"),
            (r"On (the )?Cloture Motion", "On the Cloture Motion"),
            (r"On Cloture on the Motion to Proceed", "On the Cloture Motion"),
            (r"On (the )?Nomination", "On the Nomination"),
            (r"On Passage( of the Bill|$)", "On Passage of the Bill"),
            (r"On (the )?Motion to Proceed", "On the Motion to Proceed"),
        )

        for regex, replacement in mapping:
            m = re.match(regex, vote_type, re.I)
            if m:
                if m.groups():
                    for i, val in enumerate(m.groups()):
                        replacement = replacement.replace("$%d" % (i + 1), val if val else "")
                return replacement

        return vote_type

    @staticmethod
    def get_vote_category(vote_question):
        """
        Takes the type/question field of a House or Senate vote and returns a normalized
        category for the vote type.

        Based on Eric's vote_type_for function in sunlightlabs/congress.

        @param vote_question:
        @type vote_question:
        @return:
        @rtype:
        """

        mapping = (
            # empty text (historical data)
            (r"^$", "unknown"),

            # common
            (r"^On Overriding the Veto", "veto-override"),
            (r"^On Presidential Veto", "veto-override"),
            (r"Objections of the President Not ?Withstanding", "veto-override"),  # order matters so must go before bill passage
            (r"^On Passage", "passage"),
            (r"^On the Resolution of Ratification.*", "treaty"), # order matters so must go before other resolutions
            (r"^On (Agreeing to )?the (Joint |Concurrent )?Resolution", "passage"),
            (r"^On (Agreeing to )?the Conference Report", "passage"),
            (r"^On (Agreeing to )?the (En Bloc )?Amendments?", "amendment"),

            # senate only
            (r"cloture", "cloture"),
            (r"^On the Nomination", "nomination"),
            (r"^Guilty or Not Guilty", "conviction"),  # was "impeachment" in sunlightlabs/congress but that's not quite right
            (r"^On (?:the )?Motion to Recommit", "recommit"),
            (r"^On the Motion \(Motion to Concur", "passage"),

            # house only
            (r"^(On Motion (to|that the House) )?(Concur in|Concurring|Concurring in|On Concurring|Agree to|On Agreeing to) (the )?Senate (Amendment|amdt|Adt)s?", "passage"),
            (r"^(On Motion to )?Suspend (the )?Rules and (Agree|Concur|Pass)", "passage-suspension"),
            (r"^Call of the House$", "quorum"),
            (r"^Call by States$", "quorum"),
            (r"^Election of the Speaker$", "leadership"),

            # various procedural things
            # order matters, so these must go last
            (r"^On Ordering the Previous Question", "procedural"),
            (r"^On Approving the Journal", "procedural"),
            (r"^Will the House Now Consider the Resolution|On (Question of )?Consideration of the Resolution", "procedural"),
            (r"^On (the )?Motion to Adjourn", "procedural"),
            (r"Authoriz(e|ing) Conferees", "procedural"),
            (r"On the Point of Order|Sustaining the Ruling of the Chair", "procedural"),
            (r"^On .*Motion ", "procedural"),  # $1 is a name like "Broun of Georgia"
            (r"^On the Decision of the Chair", "procedural"),
            (r"^Whether the Amendment is Germane", "procedural"),
        )

        for regex, category in mapping:
            if re.search(regex, vote_question, re.I):
                return category

        # unhandled
        logging.warn("Unhandled vote question: %s" % vote_question)
        return "unknown"

    @staticmethod
    def split_vote_id(vote_id):
        # Sessions are either four-digit years for modern day votes or a digit or letter
        # for historical votes before sessions were basically calendar years.
        return re.match("^(h|s)(\d+)-(\d+).(\d\d\d\d|[0-9A-Z])$", vote_id).groups()
