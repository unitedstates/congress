from congress.tasks import utils
import logging
import re
import json
from lxml import etree
import time
import datetime
import os
import os.path


def fetch_vote(vote_id, options):
    logging.info("\n[%s] Fetching..." % vote_id)

    vote_chamber, vote_number, vote_congress, vote_session_year = utils.split_vote_id(vote_id)

    if vote_chamber == "h":
        url = "https://clerk.house.gov/evs/%s/roll%03d.xml" % (vote_session_year, int(vote_number))
    else:
        session_num = int(vote_session_year) - utils.get_congress_first_year(int(vote_congress)) + 1
        url = "https://www.senate.gov/legislative/LIS/roll_call_votes/vote%d%d/vote_%d_%d_%05d.xml" % (int(vote_congress), session_num, int(vote_congress), session_num, int(vote_number))

    # fetch vote XML page
    body = utils.download(
        url,
        "%s/votes/%s/%s%s/%s%s.xml" % (vote_congress, vote_session_year, vote_chamber, vote_number, vote_chamber, vote_number),
        utils.merge(options, {'binary': True}),
    )

    if not body:
        return {'saved': False, 'ok': False, 'reason': "failed to download"}

    if options.get("download_only", False):
        return {'saved': False, 'ok': True, 'reason': "requested download only"}

    if b"This vote was vacated" in body:
        # Vacated votes: 2011-484, 2012-327, ...
        # Remove file, since it may previously have existed with data.
        for f in (output_for_vote(vote_id, "json"), output_for_vote(vote_id, "xml")):
            if os.path.exists(f):
                os.unlink(f)
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
        parse_house_vote(dom, vote)
    elif vote_chamber == "s":
        parse_senate_vote(dom, vote)

    # output and return

    output_vote(vote, options)

    return {'ok': True, 'saved': True}


def output_vote(vote, options, id_type=None):
    logging.info("[%s] Writing to disk..." % vote['vote_id'])

    # output JSON - so easy!
    utils.write(
        json.dumps(vote, sort_keys=True, indent=2, default=utils.format_datetime),
        output_for_vote(vote["vote_id"], "json"),
        options=options
    )

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

    root.set("datetime", utils.format_datetime(vote['date']))
    root.set("updated", utils.format_datetime(vote['updated_at']))

    def get_votes(option):
        return len(vote["votes"].get(option, []))
    root.set("aye", str(get_votes("Yea") + get_votes("Aye")))
    root.set("nay", str(get_votes("Nay") + get_votes("No")))
    root.set("nv", str(get_votes("Not Voting")))
    root.set("present", str(get_votes("Present")))

    utils.make_node(root, "category", vote["category"])
    utils.make_node(root, "type", vote["type"])
    utils.make_node(root, "question", vote["question"])
    utils.make_node(root, "required", vote["requires"])
    utils.make_node(root, "result", vote["result"])

    if vote.get("bill"):
        govtrack_type_codes = {'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc'}
        utils.make_node(root, "bill", None, session=str(vote["bill"]["congress"]), type=govtrack_type_codes[vote["bill"]["type"]], number=str(vote["bill"]["number"]))

    if "amendment" in vote:
        n = utils.make_node(root, "amendment", None)
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
        utils.make_node(root, "option", option, key=option_keys[option])

    for option in options_list:
        for v in vote["votes"][option]:
            # Rep-elect Letlow is included as not voting in the first House vote of the 117th Congress
            # where the clerk calls a quorum roll call. But because Letlow had died prior to this date,
            # he is not represented in congress-legislators and has no GovTrack-id, and so we cannot
            # represent this record in the data.
            if isinstance(v, dict) and v["id"] == "L000555" and options.get("govtrack", False): continue

            n = utils.make_node(root, "voter", None)
            if v == "VP":
                n.set("id", "0")
                n.set("VP", "1")
            elif not options.get("govtrack", False):
                n.set("id", str(v["id"]))
            else:
                n.set("id", str(utils.translate_legislator_id(id_type, v["id"], 'govtrack')))
            n.set("vote", option_keys[option])
            n.set("value", option)
            if v != "VP":
                n.set("state", v["state"])
                if v.get("voteview_votecode_extra") is not None:
                    n.set("voteview_votecode_extra", v["voteview_votecode_extra"])

    xmloutput = etree.tostring(root, pretty_print=True, encoding="unicode")

    # mimick two hard line breaks in GovTrack's legacy output to ease running diffs
    xmloutput = re.sub('(source=".*?") ', r"\1\n  ", xmloutput)
    xmloutput = re.sub('(updated=".*?") ', r"\1\n  ", xmloutput)

    utils.write(
        xmloutput,
        output_for_vote(vote['vote_id'], "xml"),
        options=options
    )


def output_for_vote(vote_id, format):
    vote_chamber, vote_number, vote_congress, vote_session_year = utils.split_vote_id(vote_id)
    return "%s/%s/votes/%s/%s%s/%s" % (utils.data_dir(), vote_congress, vote_session_year, vote_chamber, vote_number, "data.%s" % format)


def parse_senate_vote(dom, vote):
    def parse_date(d):
        return datetime.datetime.strptime(d, "%B %d, %Y, %I:%M %p")

    vote["date"] = parse_date(dom.xpath("string(vote_date)"))
    if len(dom.xpath("modify_date")) > 0:
        vote["record_modified"] = parse_date(dom.xpath("string(modify_date)"))  # some votes like s1-110.2008 don't have a modify_date
    vote["question"] = str(dom.xpath("string(vote_question_text)"))
    if vote["question"] == "":
        vote["question"] = str(dom.xpath("string(question)"))  # historical votes?
    vote["type"] = str(dom.xpath("string(vote_question)"))
    if vote["type"] == "":
        vote["type"] = vote["question"]
    vote["type"] = normalize_vote_type(vote["type"])
    vote["category"] = get_vote_category(vote["type"])
    vote["subject"] = str(dom.xpath("string(vote_title)"))
    vote["requires"] = str(dom.xpath("string(majority_requirement)"))
    vote["result_text"] = str(dom.xpath("string(vote_result_text)"))
    vote["result"] = str(dom.xpath("string(vote_result)"))

    # Senate cloture votes have consistently bad vote_question_text values: They don't say what the cloture
    # was about specifically, just what bill was relevant. So cloture on an amendment just appears as
    # cloture on the bill. The vote_title text is correctly specific in those cases. So swap the two fields
    # in those cases so that our 'question' field is reliably a good title, and subject provides additional
    # information. Check that the subject is non-empty before using it, just in case. Example:
    #  "question": "On the Cloture Motion H.R. 2578"
    #  "subject": "Motion to Invoke Cloture on the Motion to Commit H.R. 2578 with instructions (Amdt. No. 4750)"
    # https://www.senate.gov/legislative/LIS/roll_call_votes/vote1142/vote_114_2_00104.xml
    if "Cloture" in vote["question"] and vote["subject"]:
        x = vote["question"]
        vote["question"] = vote["subject"]
        vote["subject"] = x

    # "Motion to Proceed to Legislative Session" is also consistently buried and weirdly attached to a nomination.
    # Swap the fields in that case too and unlink it from the nomination because it's confusing.
    # (Should we do the swap for all motions to proceed?)
    # https://www.senate.gov/legislative/LIS/roll_call_votes/vote1151/vote_115_1_00049.xml
    elif "Legislative Session" in vote["subject"]:
        x = vote["question"]
        vote["question"] = vote["subject"]
        vote["subject"] = x
        for n in dom.xpath("document/document_type"): n.text = None

    bill_types = {"S.": "s", "S.Con.Res.": "sconres", "S.J.Res.": "sjres", "S.Res.": "sres", "H.R.": "hr", "H.Con.Res.": "hconres", "H.J.Res.": "hjres", "H.Res.": "hres"}

    if str(dom.xpath("string(document/document_type)")):
        if dom.xpath("string(document/document_type)") == "PN":
            vote["nomination"] = {
                "number": str(dom.xpath("string(document/document_number)")),
                "title": str(dom.xpath("string(document/document_title)")),
            }
            vote["question"] += ": " + vote["nomination"]["title"]
        elif dom.xpath("string(document/document_type)") == "Treaty Doc.":
            vote["treaty"] = {
                "title": str(dom.xpath("string(document/document_title)")),
            }
        elif str(dom.xpath("string(document/document_type)")) in bill_types:
            vote["bill"] = {
                "congress": int(dom.xpath("number(document/document_congress|congress)")),  # some historical files don't have document/document_congress so take the first of document/document_congress or the top-level congress element as a fall-back
                "type": bill_types[str(dom.xpath("string(document/document_type)"))],
                "number": int(dom.xpath("number(document/document_number)")),
                "title": str(dom.xpath("string(document/document_title)")),
            }
        else:
            # s294-115.2017 through s302-115.2017 have S.Amdt. in document_type,
            # but it probably should be empty since <amendment> is filled in and
            # the rest of <document> is blank.
            pass

    if str(dom.xpath("string(amendment/amendment_number)")):
        m = re.match(r"^S.Amdt. (\d+)", str(dom.xpath("string(amendment/amendment_number)")))
        if m:
            vote["amendment"] = {
                "type": "s",
                "number": int(m.group(1)),
                "purpose": str(dom.xpath("string(amendment/amendment_purpose)")),
            }

        amendment_to = str(dom.xpath("string(amendment/amendment_to_document_number)"))
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
                "title": str(dom.xpath("string(amendment/amendment_to_document_short_title)")),
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
            voter["id"] = utils.lookup_legislator(vote["congress"], "sen", voter["last_name"], voter["state"], voter["party"], vote["date"], "lis")
            if voter["id"] == None:
                logging.error("[%s] Missing lis_member_id and name lookup failed for %s" % (vote["vote_id"], voter["last_name"]))
                raise Exception("Could not find ID for %s (%s-%s)" % (voter["last_name"], voter["state"], voter["party"]))
            else:
                logging.info("[%s] Missing lis_member_id, falling back to name lookup for %s" % (vote["vote_id"], voter["last_name"]))

    # Ensure the options are noted, even if no one votes that way.
    if str(dom.xpath("string(question)")) == "Guilty or Not Guilty":
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
            "display_name": str(member.xpath("string(member_full)")),
            "first_name": str(member.xpath("string(first_name)")),
            "last_name": str(member.xpath("string(last_name)")),
        })


def parse_house_vote(dom, vote):
    def parse_date(d):
        d = d.strip()
        if " " in d:
            return datetime.datetime.strptime(d, "%d-%b-%Y %I:%M %p")
        else:  # some votes have no times?
            print(vote)
            return datetime.datetime.strptime(d, "%d-%b-%Y")

    vote["date"] = parse_date(str(dom.xpath("string(vote-metadata/action-date)")) + " " + str(dom.xpath("string(vote-metadata/action-time)")))
    vote["question"] = str(dom.xpath("string(vote-metadata/vote-question)"))
    vote["type"] = str(dom.xpath("string(vote-metadata/vote-question)"))
    vote["type"] = normalize_vote_type(vote["type"])
    if str(dom.xpath("string(vote-metadata/vote-desc)")).startswith("Impeaching "):
        vote["category"] = "impeachment"
    else:
        vote["category"] = get_vote_category(vote["question"])
    vote["subject"] = str(dom.xpath("string(vote-metadata/vote-desc)"))
    if not vote["subject"]:
        del vote["subject"]
        

    vote_types = {"YEA-AND-NAY": "1/2", "2/3 YEA-AND-NAY": "2/3", "3/5 YEA-AND-NAY": "3/5", "1/2": "1/2", "2/3": "2/3", "QUORUM": "QUORUM", "RECORDED VOTE": "1/2", "2/3 RECORDED VOTE": "2/3", "3/5 RECORDED VOTE": "3/5"}
    vote["requires"] = vote_types.get(str(dom.xpath("string(vote-metadata/vote-type)")), "unknown")

    vote["result_text"] = str(dom.xpath("string(vote-metadata/vote-result)"))
    vote["result"] = str(dom.xpath("string(vote-metadata/vote-result)"))

    bill_num = str(dom.xpath("string(vote-metadata/legis-num)"))
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
            "author": str(dom.xpath("string(vote-metadata/amendment-author)")),
        }

    # Assemble a complete question from the vote type, amendment, and bill number.
    if "amendment" in vote and "bill" in vote:
        vote["question"] += ": Amendment %s to %s" % (vote["amendment"]["number"], str(dom.xpath("string(vote-metadata/legis-num)")))
    elif "amendment" in vote:
        vote["question"] += ": Amendment %s to [unknown bill]" % vote["amendment"]["number"]
    elif "bill" in vote:
        vote["question"] += ": " + str(dom.xpath("string(vote-metadata/legis-num)"))
        if "subject" in vote:
            vote["question"] += " " + vote["subject"]
    elif "subject" in vote:
        vote["question"] += ": " + vote["subject"]

    # Count up the votes.
    vote["votes"] = {}  # by vote type

    def add_vote(vote_option, voter):
        vote["votes"].setdefault(vote_option, []).append(voter)

    # Ensure the options are noted, even if no one votes that way.
    if str(dom.xpath("string(vote-metadata/vote-question)")) == "Election of the Speaker":
        for n in dom.xpath('vote-metadata/vote-totals/totals-by-candidate/candidate'):
            vote["votes"][n.text] = []
    elif str(dom.xpath("string(vote-metadata/vote-question)")) == "Call of the House":
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
        display_name = str(member.xpath("string(legislator)"))
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
        v["id"] = utils.lookup_legislator(vote["congress"], "rep", display_name, v["state"], v["party"], vote["date"], "bioguide", exclude=seen_ids)

        if v["id"] == None:
            logging.error("[%s] Missing bioguide ID and name lookup failed for %s (%s-%s on %s)" % (vote["vote_id"], display_name, v["state"], v["party"], vote["date"]))
            raise Exception("No bioguide ID for %s (%s-%s)" % (display_name, v["state"], v["party"]))
        else:
            if vote["congress"] > 107:
                logging.warn("[%s] Used name lookup for %s because bioguide ID was missing." % (vote["vote_id"], v["display_name"]))
            seen_ids.add(v["id"])


def normalize_vote_type(vote_type):
    # Takes the "type" field of a House or Senate vote and returns a normalized
    # version of the same, as best as possible.

    # note that these allow .* after each pattern, so some things look like
    # no-ops but they are really truncating the type after the specified text.
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
        (r"On the Motion \(Motion to ((Recede )from the Senate Amendment to \S+ \d+ (and ))?Concur( with Further Amendment)?", "On the Motion to $2$3Concur$4"),
        (r"On the Motion \(Motion to (.*)\)$", "On the Motion to $1"),
    )

    for regex, replacement in mapping:
        m = re.match(regex, vote_type, re.I)
        if m:
            if m.groups():
                for i, val in enumerate(m.groups()):
                    replacement = replacement.replace("$%d" % (i + 1), val if val else "")
            return replacement

    return vote_type


def get_vote_category(vote_question):
    # Takes the type/question field of a House or Senate vote and returns a normalized
    # category for the vote type.
    #
    # Based on Eric's vote_type_for function in sunlightlabs/congress.

    mapping = (
        # empty text (historical data)
        (r"^$", "unknown"),

        # common
        (r"^On Overriding the Veto", "veto-override"),
        (r"^On Presidential Veto", "veto-override"),
        (r"Objections of the President (To The Contrary )?Not ?Withstanding", "veto-override"),  # order matters so must go before bill passage
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
        (r"^On the Motion to Concur", "passage"),
        (r"^On the Motion to Recede and Concur with Further Amendment", "passage"), # this is a normalized type that is returned by a function above

        # house only
        (r"^(On Motion (to|that the House) )?(Concur in|Concurring|Concurring in|On Concurring|On Concurring in|Agree to|On Agreeing to) (the )?Senate (Amendment|amdt|Adt)s?", "passage"),
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
        (r"^Table Appeal of the Ruling of the Chair", "procedural"),
    )

    for regex, category in mapping:
        if re.search(regex, vote_question, re.I):
            return category

    # unhandled
    logging.warn("Unhandled vote question: %s" % vote_question)
    return "unknown"
