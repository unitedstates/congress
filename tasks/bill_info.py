import utils
import logging
import re
import json
from lxml import etree
import time
import datetime
from lxml.html import fromstring, HtmlElement

def create_govtrack_xml(bill, task, options):
    # output XML
    govtrack_type_codes = {'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc'}
    root = etree.Element("bill")
    root.set("session", bill['congress'])
    root.set("type", govtrack_type_codes[bill['bill_type']])
    root.set("number", bill['number'])
    root.set("updated", utils.format_datetime(bill['updated_at']))

    def make_node(parent, tag, text, **attrs):
        if options.get("govtrack", False):
            # Rewrite thomas_id attributes as just id with GovTrack person IDs.
            attrs2 = {}
            for k, v in attrs.items():
                if v:
                    if k == "thomas_id":
                        # remap "bioguide_id" attributes to govtrack "id"
                        k = "id"
                        v = str(task.lookup_legislator_by_id("thomas", v)["id"]["govtrack"])
                    attrs2[k] = v
            attrs = attrs2

        return utils.make_node(parent, tag, text, **attrs)

    # for American Memory Century of Lawmaking bills...
    for source in bill.get("sources", []):
        n = make_node(root, "source", "")
        for k, v in sorted(source.items()):
            if k == "source":
                n.text = v
            elif k == "source_url":
                n.set("url", v)
            else:
                n.set(k, unicode(v))
    if "original_bill_number" in bill:
        make_node(root, "bill-number", bill["original_bill_number"])

    make_node(root, "state", bill['status'], datetime=bill['status_at'])
    old_status = make_node(root, "status", None)
    make_node(old_status, "introduced" if bill['status'] in ("INTRODUCED", "REFERRED") else "unknown", None, datetime=bill['status_at'])  # dummy for the sake of comparison

    make_node(root, "introduced", None, datetime=bill['introduced_at'])
    titles = make_node(root, "titles", None)
    for title in bill['titles']:
        n = make_node(titles, "title", title['title'])
        n.set("type", title['type'])
        if title['as']:
            n.set("as", title['as'])
        if title['is_for_portion']:
            n.set("partial", "1")

    if bill['sponsor']:
        # TODO: Sponsored by committee?
        make_node(root, "sponsor", None, thomas_id=bill['sponsor']['thomas_id'])
    else:
        make_node(root, "sponsor", None)

    cosponsors = make_node(root, "cosponsors", None)
    for cosp in bill['cosponsors']:
        n = make_node(cosponsors, "cosponsor", None, thomas_id=cosp["thomas_id"])
        if cosp["sponsored_at"]:
            n.set("joined", cosp["sponsored_at"])
        if cosp["withdrawn_at"]:
            n.set("withdrawn", cosp["withdrawn_at"])

    actions = make_node(root, "actions", None)
    for action in bill['actions']:
        a = make_node(actions,
                      action['type'] if action['type'] in ("vote", "vote-aux", "calendar", "topresident", "signed", "enacted", "vetoed") else "action",
                      None,
                      datetime=action['acted_at'])
        if action.get("status"):
            a.set("state", action["status"])
        if action['type'] in ('vote', 'vote-aux'):
            a.clear()  # re-insert date between some of these attributes
            a.set("how", action["how"])
            a.set("type", action["vote_type"])
            if action.get("roll") != None:
                a.set("roll", action["roll"])
            a.set("datetime", utils.format_datetime(action['acted_at']))
            a.set("where", action["where"])
            a.set("result", action["result"])
            if action.get("suspension"):
                a.set("suspension", "1")
            if action.get("status"):
                a.set("state", action["status"])
        if action['type'] == 'calendar' and "calendar" in action:
            a.set("calendar", action["calendar"])
            if action["under"]:
                a.set("under", action["under"])
            if action["number"]:
                a.set("number", action["number"])
        if action['type'] == 'enacted':
            a.clear()  # re-insert date between some of these attributes
            a.set("number", "%s-%s" % (bill['congress'], action["number"]))
            a.set("type", action["law"])
            a.set("datetime", utils.format_datetime(action['acted_at']))
            if action.get("status"):
                a.set("state", action["status"])
        if action['type'] == 'vetoed':
            if action.get("pocket"):
                a.set("pocket", "1")
        if action.get('text'):
            make_node(a, "text", action['text'])
        if action.get('in_committee'):
            make_node(a, "committee", None, name=action['in_committee'])
        for cr in action['references']:
            make_node(a, "reference", None, ref=cr['reference'], label=cr['type'])

    committees = make_node(root, "committees", None)
    for cmt in bill['committees']:
        make_node(committees, "committee", None, code=(cmt["committee_id"] + cmt["subcommittee_id"]) if cmt.get("subcommittee_id", None) else cmt["committee_id"], name=cmt["committee"], subcommittee=cmt.get("subcommittee").replace("Subcommittee on ", "") if cmt.get("subcommittee") else "", activity=", ".join(c.title() for c in cmt["activity"]))

    relatedbills = make_node(root, "relatedbills", None)
    for rb in bill['related_bills']:
        if rb['type'] == "bill":
            rb_bill_type, rb_number, rb_congress = utils.split_bill_id(rb['bill_id'])
            make_node(relatedbills, "bill", None, session=rb_congress, type=govtrack_type_codes[rb_bill_type], number=rb_number, relation="unknown" if rb['reason'] == "related" else rb['reason'])

    subjects = make_node(root, "subjects", None)
    if bill['subjects_top_term']:
        make_node(subjects, "term", None, name=bill['subjects_top_term'])
    for s in bill['subjects']:
        if s != bill['subjects_top_term']:
            make_node(subjects, "term", None, name=s)

    amendments = make_node(root, "amendments", None)
    for amd in bill['amendments']:
        make_node(amendments, "amendment", None, number=amd["chamber"] + str(amd["number"]))

    if bill.get('summary'):
        make_node(root, "summary", bill['summary']['text'], date=bill['summary']['date'], as_of_status=bill['summary']['as'])

    return etree.tostring(root, pretty_print=True)



def related_bills_for(body, congress, bill_id):
    match = re.search("RELATED BILL DETAILS.*?<p>.*?<table border=\"0\">(.*?)(?:<hr|<div id=\"footer\">)", body, re.S)
    if not match:
        if re.search("RELATED BILL DETAILS:((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
            return []
        else:
            raise Exception("Couldn't find related bills section.")

    text = match.group(1).strip()

    related_bills = []

    for line in re.split("<tr><td", text):
        if (line.strip() == "") or ("Bill:" in line):
            continue

        m = re.search("<a[^>]+>(.+?)</a>.*?<td>(.+?)</td>", line)
        if not m:
            raise Exception("Choked processing related bill line.")

        bill_code, reason = m.groups()

        related_id = "%s-%s" % (bill_code.lower().replace(".", "").replace(" ", ""), congress)

        if "amdt" in related_id:
            details = {"type": "amendment", "amendment_id": related_id}
        else:
            details = {"type": "bill", "bill_id": related_id}

        reasons = (
            ("Identical bill identified by (CRS|House|Senate)", "identical"),
            ("Companion bill", "identical"),
            ("Related bill (as )?identified by (CRS|the House Clerk's office|House committee|Senate)", "related"),
            ("passed in (House|Senate) in lieu of .*", "supersedes"),
            ("Rule related to .* in (House|Senate)", "rule"),
            ("This bill has text inserted from .*", "includes"),
            ("Text from this bill was inserted in .*", "included-in"),
            ("Bill related to rule .* in House", "ruled-by"),
            ("This bill caused other related action on .*", "caused-action"),
            ("Other related action happened to this bill because of .*", "action-caused-by"),
            ("Bill that causes .* to be laid on table in House", "caused-action"),
            ("Bill laid on table by virtue of .* passage in House", "action-caused-by"),
            ("Bill that caused the virtual passage of .* in House", "caused-action"),
            ("Bill passed by virtue of .* passage in House", "caused-action-by"),
            ("Bill on wich enrollment has been corrected by virtue of .* passage in House", "caused-action"),
        )
        for reason_re, reason_code in reasons:
            if re.search(reason_re + "$", reason, re.I):
                reason = reason_code
                break
        else:
            logging.error("[%s] Unknown bill relation with %s: %s" % (bill_id, related_id, reason.strip()))
            reason = "unknown"

        details['reason'] = reason

        related_bills.append(details)

    return related_bills


def parse_bill_action(action_dict, prev_status, bill_id, title):
    """Parse a THOMAS bill action line. Returns attributes to be set in the XML file on the action line."""

    bill_type, number, congress = utils.split_bill_id(bill_id)
    if not utils.committee_names:
        utils.fetch_committee_names(congress, {})

    line = action_dict['text']

    status = None
    action = {
        "type": "action"
    }

    # If a line starts with an amendment number, this action is on the amendment and cannot
    # be parsed yet.
    m = re.search(r"^(H|S)\.Amdt\.(\d+)", line, re.I)
    if m != None:
        # Process actions specific to amendments separately.
        return None, None

    # Otherwise, parse the action line for key actions.

    # VOTES

    # A House Vote.
    line = re.sub(", the Passed", ", Passed", line)
    # 106 h4733 and others

    m = re.search("("
        + "|".join([
            "On passage",
            "Passed House",
            "Two-thirds of the Members present having voted in the affirmative the bill is passed,?",
            "On motion to suspend the rules and pass the (?:bill|resolution)",
            "On agreeing to the (?:resolution|conference report)",
            "On motion to suspend the rules and agree to the (?:resolution|conference report)",
            "House Agreed to Senate Amendments.*?",
            "On motion that the House (?:suspend the rules and )?(?:agree(?: with an amendment)? to|concur in) the Senate amendments?(?: to the House amendments?| to the Senate amendments?)*",
        ])
        + ")"
        + "(, the objections of the President to the contrary notwithstanding.?)?"
        + "(, as amended| \(Amended\))?"
        + " (Passed|Failed|Agreed to|Rejected)?"
        + " ?(by voice vote|without objection|by (the Yeas and Nays|Yea-Nay Vote|recorded vote)"
        + "(:? \(2/3 required\))?: (\d+ - \d+(, \d+ Present)? [ \)]*)?\((Roll no\.|Record Vote No:) \d+\))",
        line, re.I)
    if m != None:
        motion, is_override, as_amended, pass_fail, how = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)

        # print line
        # print m.groups()

        if re.search(r"Passed House|House Agreed to", motion, re.I):
            pass_fail = 'pass'
        elif re.search("(ayes|yeas) had prevailed", line, re.I):
            pass_fail = 'pass'
        elif re.search(r"Pass|Agreed", pass_fail, re.I):
            pass_fail = 'pass'
        else:
            pass_fail = 'fail'

        if "Two-thirds of the Members present" in motion:
            is_override = True

        if is_override:
            vote_type = "override"
        elif re.search(r"(agree (with an amendment )?to|concur in) the Senate amendment", line, re.I):
            vote_type = "pingpong"
        elif re.search("conference report", line, re.I):
            vote_type = "conference"
        elif bill_type[0] == "h":
            vote_type = "vote"
        else:
            vote_type = "vote2"

        roll = None
        m = re.search(r"\((Roll no\.|Record Vote No:) (\d+)\)", how, re.I)
        if m != None:
            how = "roll"  # normalize the ugly how
            roll = m.group(2)

        suspension = None
        if roll and "On motion to suspend the rules" in motion:
            suspension = True

        # alternate form of as amended, e.g. hr3979-113
        if "that the House agree with an amendment" in motion:
            as_amended = True

        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = how
        action['where'] = "h"
        action['result'] = pass_fail
        if roll:
            action["roll"] = roll
        action["suspension"] = suspension

        # correct upstream data error
        if bill_id == "s2012-114" and "Roll no. 250" in line:
            as_amended = True

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, suspension, as_amended, title, prev_status)
        if new_status:
            status = new_status

    # Passed House, not necessarily by an actual vote (think "deem")
    m = re.search(r"Passed House pursuant to|House agreed to Senate amendment (with amendment )?pursuant to", line, re.I)
    if m != None:
        vote_type = "vote" if (bill_type[0] == "h") else "vote2"
        if "agreed to Senate amendment" in line: vote_type = "pingpong"
        pass_fail = "pass"
        as_amended = bool(m.group(1))

        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = "by special rule"
        action["where"] = "h"
        action["result"] = pass_fail

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, False, as_amended, title, prev_status)

        if new_status:
            status = new_status

    # A Senate Vote
    # (There are some annoying weird cases of double spaces which are taken care of
    # at the end.)
    m = re.search("("
        + "|".join([
        "Passed Senate",
        "Failed of passage in Senate",
        "Disagreed to in Senate",
        "Resolution agreed to in Senate",
        "Senate (?:agreed to|concurred in) (?:the )?(?:conference report|House amendment(?: to the Senate amendments?| to the House amendments?)*)",
        r"Cloture \S*\s?on the motion to proceed .*?not invoked in Senate",
        r"Cloture(?: motion)? on the motion to proceed to the (?:bill|measure) invoked in Senate",
        "Cloture invoked in Senate",
        "Cloture on (?:the motion to proceed to )?the bill (?:not )?invoked in Senate",
        "(?:Introduced|Received|Submitted) in the Senate, (?:read twice, |considered, |read the third time, )+and (?:passed|agreed to)",
        ])
        + ")"
        + "(,?.*,?) "
        + "(without objection|by Unanimous Consent|by Voice Vote|(?:by )?Yea-Nay( Vote)?\. \d+\s*-\s*\d+\. Record Vote (No|Number): \d+)",
        line.replace("  ", " "), re.I)
    if m != None:
        motion, extra, how = m.group(1), m.group(2), m.group(3)
        roll = None

        # put disagreed check first, cause "agreed" is contained inside it
        if re.search("disagreed", motion, re.I):
            pass_fail = "fail"
        elif re.search("passed|agreed|concurred|bill invoked|measure invoked|cloture invoked", motion, re.I):
            pass_fail = "pass"
        else:
            pass_fail = "fail"

        voteaction_type = "vote"
        if re.search("over veto", extra, re.I):
            vote_type = "override"
        elif re.search("conference report", motion, re.I):
            vote_type = "conference"
        elif re.search("cloture", motion, re.I):
            vote_type = "cloture"
            voteaction_type = "vote-aux"  # because it is not a vote on passage
        elif re.search("Senate agreed to (the )?House amendment|Senate concurred in (the )?House amendment", motion, re.I):
            vote_type = "pingpong"
        elif bill_type[0] == "s":
            vote_type = "vote"
        else:
            vote_type = "vote2"

        m = re.search(r"Record Vote (No|Number): (\d+)", how, re.I)
        if m != None:
            roll = m.group(2)
            how = "roll"

        as_amended = False
        if re.search(r"with amendments|with an amendment", extra, re.I):
            as_amended = True

        action["type"] = voteaction_type
        action["vote_type"] = vote_type
        action["how"] = how
        action["result"] = pass_fail
        action["where"] = "s"
        if roll:
            action["roll"] = roll

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "s", bill_type, False, as_amended, title, prev_status)

        if new_status:
            status = new_status

    # OLD-STYLE VOTES (93rd Congress-ish)

    m = re.search(r"Measure passed (House|Senate)(, amended(?: \(.*?\)|, with an amendment to the title)?)?(?:,? in lieu[^,]*)?(?:, roll call #(\d+) \(\d+-\d+\))?", line, re.I)
    if m != None:
        chamber = m.group(1)[0].lower()  # 'h' or 's'
        as_amended = m.group(2)
        roll_num = m.group(3)
        # GovTrack legacy scraper missed these: if chamber == 's' and (as_amended or roll_num or "lieu" in line): return action, status
        pass_fail = "pass"
        vote_type = "vote" if bill_type[0] == chamber else "vote2"
        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = "(method not recorded)" if not roll_num else "roll"
        if roll_num:
            action["roll"] = roll_num
        action["result"] = pass_fail
        action["where"] = chamber
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", chamber, bill_type, False, as_amended, title, prev_status)
        if new_status:
            status = new_status

    m = re.search(r"(House|Senate) agreed to (?:House|Senate) amendments?( with an amendment)?( under Suspension of the Rules)?(?:, roll call #(\d+) \(\d+-\d+\))?\.", line, re.I)
    if m != None:
        chamber = m.group(1)[0].lower()  # 'h' or 's'
        as_amended = m.group(2)
        suspension = m.group(3)
        roll_num = m.group(4)
        # GovTrack legacy scraper missed these: if (chamber == 'h' and not roll_num) or (chamber == 's' and rull_num): return action, status # REMOVE ME
        pass_fail = "pass"
        vote_type = "pingpong"
        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = "(method not recorded)" if not roll_num else "roll"
        if roll_num:
            action["roll"] = roll_num
        action["result"] = pass_fail
        action["where"] = chamber
        action["suspension"] = (suspension != None)
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", chamber, bill_type, False, as_amended, title, prev_status)
        if new_status:
            status = new_status

    # PSUDO-REPORTING (because GovTrack did this, but should be changed)

    # TODO: Make a new status for this as pre-reported.
    m = re.search(r"Placed on (the )?([\w ]+) Calendar( under ([\w ]+))?[,\.] Calendar No\. (\d+)\.|Committee Agreed to Seek Consideration Under Suspension of the Rules|Ordered to be Reported", line, re.I)
    if m != None:
        # TODO: This makes no sense.
        if prev_status in ("INTRODUCED", "REFERRED"):
            status = "REPORTED"

        action["type"] = "calendar"

        # TODO: Useless. But good for GovTrack compatibility.
        if m.group(2):  # not 'Ordered to be Reported'
            action["calendar"] = m.group(2)
            action["under"] = m.group(4)
            action["number"] = m.group(5)

    # COMMITTEE ACTIONS

    # reported
    m = re.search(r"Committee on (.*)\. Reported by", line, re.I)
    if m != None:
        action["type"] = "reported"
        action["committee"] = m.group(1)
        if prev_status in ("INTRODUCED", "REFERRED"):
            status = "REPORTED"
    m = re.search(r"Reported to Senate from the (.*?)( \(without written report\))?\.", line, re.I)
    if m != None:  # 93rd Congress
        action["type"] = "reported"
        action["committee"] = m.group(1)
        if prev_status in ("INTRODUCED", "REFERRED"):
            status = "REPORTED"

    # hearings held by a committee
    m = re.search(r"(Committee on .*?)\. Hearings held", line, re.I)
    if m != None:
        action["committee"] = m.group(1)
        action["type"] = "hearings"

    m = re.search(r"Committee on (.*)\. Discharged (by Unanimous Consent)?", line, re.I)
    if m != None:
        action["committee"] = m.group(1)
        action["type"] = "discharged"
        if prev_status in ("INTRODUCED", "REFERRED"):
            status = "REPORTED"

    m = re.search("Cleared for White House|Presented to President", line, re.I)
    if m != None:
        action["type"] = "topresident"

    m = re.search("Signed by President", line, re.I)
    if m != None:
        action["type"] = "signed"
        status = "ENACTED:SIGNED"

    m = re.search("Pocket Vetoed by President", line, re.I)
    if m != None:
        action["type"] = "vetoed"
        action["pocket"] = "1"
        status = "VETOED:POCKET"

    # need to put this in an else, or this regex will match the pocket veto and override it
    else:
        m = re.search("Vetoed by President", line, re.I)
        if m != None:
            action["type"] = "vetoed"
            status = "PROV_KILL:VETO"

    m = re.search("^(?:Became )?(Public|Private) Law(?: No:)? ([\d\-]+)\.", line, re.I)
    if m != None:
        action["law"] = m.group(1).lower()
        pieces = m.group(2).split("-")
        action["congress"] = pieces[0]
        action["number"] = pieces[1]
        action["type"] = "enacted"
        if prev_status == "ENACTED:SIGNED":
            pass  # this is a final administrative step
        elif prev_status == "PROV_KILL:VETO" or prev_status.startswith("VETOED:"):
            status = "ENACTED:VETO_OVERRIDE"
        elif bill_id in ("s2641-93", "hr1589-94", "s2527-100", "hr1677-101", "hr2978-101", "hr2126-104", "s1322-104"):
            status = "ENACTED:TENDAYRULE"
        else:
            raise Exception("Missing Signed by President action? If this is a case of the 10-day rule, hard code the bill id %s here." % bill_id)

    # Check for referral type
    m = re.search(r"Referred to (?:the )?(House|Senate)?\s?(?:Committee|Subcommittee)?", line, re.I)
    if m != None:
        action["type"] = "referral"
        if prev_status == "INTRODUCED":
            status = "REFERRED"

    # no matter what it is, sweep the action line for bill IDs of related bills
    bill_ids = utils.extract_bills(line, congress)
    bill_ids = filter(lambda b: b != bill_id, bill_ids)
    if bill_ids and (len(bill_ids) > 0):
        action['bill_ids'] = bill_ids

    return action, status


def new_status_after_vote(vote_type, passed, chamber, bill_type, suspension, amended, title, prev_status):
    if vote_type == "vote":  # vote in originating chamber
        if passed:
            if bill_type in ("hres", "sres"):
                return 'PASSED:SIMPLERES'  # end of life for a simple resolution
            if chamber == "h":
                return 'PASS_OVER:HOUSE'  # passed by originating chamber, now in second chamber
            else:
                return 'PASS_OVER:SENATE'  # passed by originating chamber, now in second chamber
        if suspension:
            return 'PROV_KILL:SUSPENSIONFAILED'  # provisionally killed by failure to pass under suspension of the rules
        if chamber == "h":
            return 'FAIL:ORIGINATING:HOUSE'  # outright failure
        else:
            return 'FAIL:ORIGINATING:SENATE'  # outright failure
    if vote_type in ("vote2", "pingpong"):  # vote in second chamber or subsequent pingpong votes
        if passed:
            if amended:
                # mesure is passed but not in identical form
                if chamber == "h":
                    return 'PASS_BACK:HOUSE'  # passed both chambers, but House sends it back to Senate
                else:
                    return 'PASS_BACK:SENATE'  # passed both chambers, but Senate sends it back to House
            else:
                # bills and joint resolutions not constitutional amendments, not amended from Senate version
                if bill_type in ("hjres", "sjres") and title.startswith("Proposing an amendment to the Constitution of the United States"):
                    return 'PASSED:CONSTAMEND'  # joint resolution that looks like an amendment to the constitution
                if bill_type in ("hconres", "sconres"):
                    return 'PASSED:CONCURRENTRES'  # end of life for concurrent resolutions
                return 'PASSED:BILL'  # passed by second chamber, now on to president
        if vote_type == "pingpong":
            # chamber failed to accept the other chamber's changes, but it can vote again
            return 'PROV_KILL:PINGPONGFAIL'
        if suspension:
            return 'PROV_KILL:SUSPENSIONFAILED'  # provisionally killed by failure to pass under suspension of the rules
        if chamber == "h":
            return 'FAIL:SECOND:HOUSE'  # outright failure
        else:
            return 'FAIL:SECOND:SENATE'  # outright failure
    if vote_type == "cloture":
        if not passed:
            return "PROV_KILL:CLOTUREFAILED"
        else:
            return None
    if vote_type == "override":
        if not passed:
            if bill_type[0] == chamber:
                if chamber == "h":
                    return 'VETOED:OVERRIDE_FAIL_ORIGINATING:HOUSE'
                else:
                    return 'VETOED:OVERRIDE_FAIL_ORIGINATING:SENATE'
            else:
                if chamber == "h":
                    return 'VETOED:OVERRIDE_FAIL_SECOND:HOUSE'
                else:
                    return 'VETOED:OVERRIDE_FAIL_SECOND:SENATE'
        else:
            if bill_type[0] == chamber:
                if chamber == "h":
                    return 'VETOED:OVERRIDE_PASS_OVER:HOUSE'
                else:
                    return 'VETOED:OVERRIDE_PASS_OVER:SENATE'
            else:
                return None  # just wait for the enacted line
    if vote_type == "conference":
        # This is tricky to integrate into status because we have to wait for both
        # chambers to pass the conference report.
        if passed:
            if prev_status.startswith("CONFERENCE:PASSED:"):
                if bill_type in ("hjres", "sjres") and title.startswith("Proposing an amendment to the Constitution of the United States"):
                    return 'PASSED:CONSTAMEND'  # joint resolution that looks like an amendment to the constitution
                if bill_type in ("hconres", "sconres"):
                    return 'PASSED:CONCURRENTRES'  # end of life for concurrent resolutions
                return 'PASSED:BILL'
            else:
                if chamber == "h":
                    return 'CONFERENCE:PASSED:HOUSE'
                else:
                    return 'CONFERENCE:PASSED:SENATE'

    return None

