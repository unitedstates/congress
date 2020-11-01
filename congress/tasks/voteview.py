import re
import io
import csv
import datetime
import time
import logging

from congress.tasks import utils
from congress.tasks.vote_info import output_vote

# load some hard-coded codes
special_vote_options = { }
for rec in csv.reader(open("tasks/voteview_codedoptions.csv")):
    if rec[0] == "vote date": continue # header
    special_vote_options[rec[1]] = (rec[2], dict((int(r.split(':', 1)[0]), r.split(':', 1)[1]) for r in rec[3].split(';')))


def run(options):
    congress = options.get("congress", None)
    congress = int(congress) if congress else utils.current_congress()

    chamber = options.get('chamber', None)

    # we're going to need to map votes to sessions because in modern history the numbering resets by session
    session_dates = list(csv.DictReader(io.StringIO(utils.download("http://www.govtrack.us/data/us/sessions.tsv").encode("utf8")), delimiter="\t"))

    # download the vote data now
    if chamber and chamber in [ "h", "s" ]:
        votes = get_votes(chamber, congress, options, session_dates)
    else:
        votes = get_votes("h", congress, options, session_dates) + get_votes("s", congress, options, session_dates)

    utils.process_set(votes, put_vote, options)


def vote_list_source_urls_for(congress, chamber, options):
    url = "http://www.voteview.com/%s%02d.htm" % (("house" if chamber == "h" else "senate"), congress)
    index_page = utils.download(url, cache_file_for(congress, chamber, "html"), options)
    if index_page == None:
        raise Exception("No data.")  # should only happen on a 404

    def match(pattern):
        matches = re.findall(pattern, index_page, re.I)
        if len(matches) != 1:
            raise ValueError("Index page %s did not match one value for pattern %s." % (url, pattern))
        return matches[0]

    return match("ftp://voteview.com/[^\.\s]+\.ord"), match("ftp://voteview.com/dtl/[^\.\s]+\.dtl")


def cache_file_for(congress, chamber, file_type):
    return "voteview/%s-%s.%s" % (congress, chamber, file_type)


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
        99: None,  # Used by presidents
    }

    return icpsr_state_code_map[icpsr_state_code]


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

    return icpsr_party_code_map.get(icpsr_party_code)


def parse_voteview_vote_code(vote_code):
    # Convert the integer codes into a tuple containing:
    #    standard vote options "Yea", "Nay", "Not Voting", "Present"
    #    an additional string so that we don't lose any information provided by voteview
    # Probably the House used Aye and No in some votes, but we don't
    # know which. "Yea" and "Nay" are always used by the Senate, and always
    # in the House on the passage of bills.
    # A paired vote is when two members plan to be absent in a way that
    # does not affect the vote outcome. You can see in the Congressional
    # record who is paired with who. Sometimes the pairings are for a
    # particular vote, other pairings are "until further notice." The paired
    # members are recorded as not voting. A live pair is when one half of
    # the pair is present and withdraws their vote and votes present because
    # the other half of the pair isn't there. Live pairs aren't recorded
    # in this data and are treated simply as pairs (and thus for us, not
    # voting). Some paired members are recorded simply as present in this
    # data --- not clear why that would be.
    # See the House vote on the Civil Rights Act of 1957 (85th Congress,
    # Jun 18, 1957, what this data calls #42, volume 103 page 9518 of
    # the Congressional Record) for an example of paired votes.
    vote_code_map = {
        0: (None, None),  # not a member at the time of the vote (but sometimes recorded as Not Voting)
        1: ("Yea", None),
        2: ("Not Voting", "paired-yea"),
        3: ("Not Voting", "announced-yea"),
        4: ("Not Voting", "announced-nay"),
        5: ("Not Voting", "paired-nay"),
        6: ("Nay", None),
        7: ("Present", "type-seven"),
        8: ("Present", "type-eight"),
        9: ("Not Voting", None),
    }
    return vote_code_map[vote_code]


def parse_vote_list_line(vote_list_line):
    return re.match(r"^([\s\d]{2}\d)([\s\d]{4}\d)([\s\d]\d)([\s\d]{2})([^\d]+?)([\s\d]{3}\d)([\s\d])([\s\d])([^\s\d][^\d]+?(?:\d\s+)?)(\d+)$", vote_list_line).groups()


def parse_rollcall_dtl_list_line(rollcall_list_line):
    return re.match(r"^([\s\d]{3}\d)([\s\d]{4}\d)?([\s\d]\d)\s(.*?)\s*$", rollcall_list_line).groups()


def parse_rollcall_dtl_list_first_line(rollcall_dtl_first_line):
    return re.match(r"^(.{14})(.{15})(.{10})?(.+?)(?:\s{3,}\d{2,3})?$", rollcall_dtl_first_line).groups()


def parse_rollcall_dtl_date(rollcall_dtl_date):
    from datetime import datetime

    potential_date_formats = [
        "%b %d, %Y",  # JAN 1, 1900
        "%B %d, %Y",  # JANUARY 1, 1900
        "%b, %d, %Y",  # JAN, 1, 1900
        "%B, %d, %Y",  # JANUARY, 1, 1900
        "%b.%d, %Y",  # JAN.1, 1900
    ]

    # Make things easier by removing periods after month abbreviations.
    rollcall_dtl_date = rollcall_dtl_date.replace(". ", " ")

    # Make things easier by inserting spaces after commas where they are missing.
    rollcall_dtl_date = rollcall_dtl_date.replace(",1", ", 1")

    # Python doesn't consider "SEPT" a valid abbreviation for September.
    rollcall_dtl_date = rollcall_dtl_date.replace("SEPT ", "SEP ")

    parsed_date = None

    for potential_date_format in potential_date_formats:
        try:
            parsed_date = datetime.strptime(rollcall_dtl_date, potential_date_format)
        except ValueError:
            pass
        else:
            break

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
        "votes": [int(icpsr_vote_code) for icpsr_vote_code in parsed_vote_list_line[9]],
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
    # Each line in the vote list file is for a Member of Congress, with
    # identifying data in the left column followed by one character per
    # vote (1=aye, etc.).

    logging.info("Parsing vote list file...")

    vote_list_info = []

    for vote_list_line in vote_list_file.split("\r\n"):
        if not vote_list_line.strip():
            continue

        vote_info = extract_vote_info_from_parsed_vote_list_line(parse_vote_list_line(vote_list_line))

        vote_info["state"] = get_state_from_icpsr_state_code(vote_info["icpsr_state"]) if vote_info["icpsr_state"] is not None else None
        vote_info["party"] = get_party_from_icpsr_party_code(vote_info["icpsr_party"]) if vote_info["icpsr_party"] is not None else None

        icpsr_id = vote_info["icpsr_id"]

        # I think these are mistakes? Don't know if the 9- codes something special.
        if icpsr_id == 91449: icpsr_id = 1449
        if icpsr_id == 92484: icpsr_id = 2484
        if icpsr_id == 94804: icpsr_id = 4804
        if icpsr_id == 94891: icpsr_id = 4891
        if icpsr_id == 96738: icpsr_id = 6738
        if icpsr_id == 98500: icpsr_id = 8500
        if icpsr_id == 99369: icpsr_id = 9369
        if icpsr_id == 90618: icpsr_id = 10618
        if icpsr_id == 90634: icpsr_id = 10634
        if icpsr_id == 91043: icpsr_id = 11043
        if icpsr_id == 93033: icpsr_id = 13033
        if icpsr_id == 94428: icpsr_id = 14428
        if icpsr_id == 94454: icpsr_id = 14454
        if icpsr_id == 94602: icpsr_id = 14602
        if icpsr_id == 94628: icpsr_id = 14628
        if icpsr_id == 95122: icpsr_id = 15122
        if icpsr_id == 95415: icpsr_id = 15415
        if icpsr_id == 3769: icpsr_id = 15101 # guy was given two ids
        if icpsr_id == 14240: icpsr_id = 94240 # per our id

        try:
            bioguide_id = utils.get_person_id("icpsr" if vote_info["state_name"] != "USA" else "icpsr_prez", icpsr_id, "bioguide")
        except KeyError as e:
            # skip some guys named Poe (99999) and Chambers (10509) that don't seem to have existed and didn't cast actual votes,
            # and Jack Swigert (15067) who died before being sworn in.
            # and presidents may not have bioguide IDs
            if icpsr_id not in (99999, 10509, 15067) and vote_info["state_name"] != "USA":
                logging.error("Problem with member %s ([%d] %s) of %s %s: %s" % (vote_info["member_name"], vote_info["icpsr_party"], vote_info["party"],
                                                                             vote_info["state_name"], vote_info["district"], e.message))
                #logging.error(vote_info)
            bioguide_id = None
        else:
            logging.debug("Parsed member %s ([%d] %s) of %s %s..." % (vote_info["member_name"], vote_info["icpsr_party"], vote_info["party"],
                                                                      vote_info["state_name"], vote_info["district"]))
        vote_info["bioguide_id"] = bioguide_id

        # This is used to record the President's position, or something.
        # Mark this record so build_votes can separated it out from Member votes.
        vote_info["is_president"] = True if vote_info["icpsr_state"] == 99 else False

        vote_list_info.append(vote_info)

    return vote_list_info


def parse_rollcall_dtl_list_file(rollcall_dtl_list_file, congress):
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

            rollcall_info["date_unparsed"] = rollcall_dtl_list_first_line_parts[3].strip()
            rollcall_info["date"] = parse_rollcall_dtl_date(rollcall_info["date_unparsed"])

            rollcall_info["bill_unparsed"] = rollcall_dtl_list_first_line_parts[2].strip()
            m = re.match(r"([A-Z]+)([0-9]+)$", rollcall_info["bill_unparsed"])
            if m:
                bill_type_map = {
                   'HR': 'hr', 'H': 'hr',
                   'S': 's',
                   'HJR': 'hjres', 'HJ': 'hjres', 'HJRE': 'hjres', 'HJRES': 'hjres',
                   'SJR': 'sjres', 'SJ': 'sjres', 'SJRE': 'sjres', 'SJRES': 'sjres',
                   'HCR': 'hconres', 'HCRE': 'hconres', 'HCRES': 'hconres', 'HCONR': 'hconres', 'HCON': 'hconres',
                   'SCR': 'sconres', 'SCRE': 'sconres', 'SCRES': 'sconres', 'SCONRES': 'sconres', 'SCONR': 'sconres', 'SCON': 'sconres',
                   'HRE': 'hres', 'HRES': 'hres',
                   'SRE': 'sres', 'SR': 'sres', 'SRES': 'sres' }
                if not m.group(1) in bill_type_map:
                    logging.error('Could not parse bill: %s' % rollcall_info["bill_unparsed"])
                else:
                    rollcall_info["bill"] = { 'congress': congress, 'type': bill_type_map[m.group(1)], 'number': int(m.group(2)) }

        elif rollcall_dtl_list_line_info["line"] == 2:
            pass
        elif rollcall_dtl_list_line_info["line"] == 3:
            rollcall_info["description"] = rollcall_dtl_list_line_info["text"]
        else:
            rollcall_info["description"] += " " + rollcall_dtl_list_line_info["text"]

        rollcall_dtl_list_info[rollcall_dtl_list_line_info["vote"]] = rollcall_info

    return rollcall_dtl_list_info


def build_votes(vote_list):
    # Go from a list of individuals (and their votes) to a mapping
    # from votes to how the individuals voted on it.

    logging.info("Building votes...")

    votes = {}
    presidents_positions = {}

    for voter in vote_list:
        for i, choice in enumerate(voter["votes"]):
            # Separate the president's position from Member votes.
            if voter["is_president"]:
                presidents_positions[i] = choice
                continue

            # Drop anyone we didn't have a bioguide id for. We issued warnings
            # when we did the lookup if we couldn't find the id. Any remaining
            # cases are individuals who didn't actually take office and didn't
            # actually vote. Presidents may not have bioguide IDs so we filter
            # those first above.
            if voter["bioguide_id"] is None:
                continue

            # Make a record for this vote, grouped by vote option (Aye, etc).
            votes.setdefault(i, []).append({
                "id": voter["bioguide_id"],
                "display_name": voter["member_name"],
                "party": voter["party"],
                "state": voter["state"],
                "vote": choice,
            })

    # sort for output
    for voters in votes.values():
        voters.sort(key=lambda v: v['display_name'])

    return (votes, presidents_positions)


def session_from_date(date, session_dates):
    for sess in session_dates:
        if sess["start"] <= date <= sess["end"]:
            return int(sess["congress"]), sess["session"]
    return None, None

def parse_rollcall_description(rollcall):
    # The description sometimes has additional metadata. It's a little tricky
    # to parse because the description has hyphens at the ends of lines where
    # words are split.
    dparts = rollcall['description'].split(". ")
    while len(dparts) > 1:
        dpart = dparts[-1].strip(".- ") # remove trailing spaces, hyphens, and periods (which occur at the end of the final dpart but not inner ones because it is the split string)
        if dpart == "NAY SUPPORTS PRESIDENT'S POSITION":
            rollcall['presidents_position'] =  { "option": "Nay" } # also recorded in the big table, so we probably already have this
        elif dpart == "YEA SUPPORTS PRESIDENT'S POSITION":
            rollcall['presidents_position'] =  { "option": "Yea" }
        elif dpart in ("REJECTED", "PASSED", "AGREED TO", "ADOPTED", "ACCEPTED", "CONFIRMED", "RATIFIED"):
            rollcall['result'] = dpart.title()
        elif dpart.startswith("(SEE CQ "):
            pass # remove this
        else:
            # Unrecognized, so stop here.
            break
        # Remove this part from the description.
        dparts.pop(-1)
    rollcall['description'] = ". ".join(dparts)
    if not rollcall['description'].endswith('.'): rollcall['description'] += "."

def build_votes_dict(votes_list, rollcall):    
    if rollcall.get("description") in special_vote_options:
        # Some votes are for things besides aye/no etc where the vote
        # description says how the numeric codes are mapped to options.
        # e.g. for Election of the Speaker, 1 will be one candidate, 2
        # will be another candidate. We've manually coded these and
        # loaded them at the top of the module. In these cases, we also
        # have replacement strings for the vote description.
        original_description = rollcall["description"]
        new_description, vote_codes = special_vote_options[original_description]
        rollcall["description"] = new_description
        for v in votes_list:
            if v["vote"] == 0:
                v["vote"] = None
            elif v["vote"] == 9:
                v["vote"] = "Not Voting"
            else:
                try:
                    v["vote"] = vote_codes[v["vote"]]
                except KeyError:
                    logging.error('Vote "%s" had a "%d" vote.' % (original_description, v["vote"]))
                    v["vote"] = "Unknown"

    else:
        # This is a regular vote. Use the regular voteview codebook.
        for v in votes_list:
            v["vote"], v["voteview_votecode_extra"] = parse_voteview_vote_code(v["vote"])

    # Now make a dict from vote option to the legislators who voted
    # that option. Preserve ordering of votes_list which is already
    # sorted.
    ret = {
        choice: [v for v in votes_list if v["vote"] == choice]
        for choice in set(v["vote"] for v in votes_list)
        if choice != None # legislators who were not serving at the time of the vote
    }

    # No longer need the "vote" keys.
    for v in votes_list:
        del v["vote"]

    return ret

def get_votes(chamber, congress, options, session_dates):
    logging.warn("Getting votes for %d-%s..." % (congress, chamber))

    vote_list_url, rollcall_list_url = vote_list_source_urls_for(congress, chamber, options)

    # Load the ORD file which contains the matrix of how people voted.

    vote_list_file = utils.download(vote_list_url, cache_file_for(congress, chamber, "ord"), options).encode("utf-8")
    if not vote_list_file:
        logging.error("Couldn't download vote list file.")
        return None

    vote_list = parse_vote_list_file(vote_list_file)
    votes, presidents_positions = build_votes(vote_list)

    # Load the DTL file which lists each roll call vote with textual metadata.

    rollcall_list_file = utils.download(rollcall_list_url, cache_file_for(congress, chamber, "dtl"), options).encode("utf-8")
    if not rollcall_list_file:
        logging.error("Couldn't download rollcall list file.")
        return None
    rollcall_list = parse_rollcall_dtl_list_file(rollcall_list_file, congress)

    # Some dates are valid but incorrect. When the date doesn't even fall
    # within the Congress that we know the vote falls in, clear out the
    # date so we can try to guess a valid date in the next step.
    for rollcall_number in rollcall_list:
        rollcall = rollcall_list[rollcall_number]
        if rollcall["date"]:
            d_congress, d_session = session_from_date(rollcall["date"], session_dates)
            if d_congress != congress:
                rollcall["date"] = None

    # The dates listed in the DTL file were originally OCRd and have tons
    # of errors. Many strings could not be parsed. There are occasional
    # invalid dates (like Feb 29 on a non-leap year --- the 9s are probably
    # incorrectly OCR'd 5's). Try to resolve these quickly without resorting
    # to manual fact-checking...
    for i in range(min(rollcall_list)+1, max(rollcall_list) - 1):
        if rollcall_list[i]["date"]:
            continue  # was OK
        if not rollcall_list[i - 1]["date"]:
            continue  # preceding date not OK

        # If the vote is surrounded by votes on the same day, set the date to that day.
        if rollcall_list[i - 1]["date"] == rollcall_list[i + 1]["date"]:
            rollcall_list[i]["date"] = rollcall_list[i - 1]["date"]
            logging.error("Replacing %s with %s." % (rollcall_list[i]["date_unparsed"], rollcall_list[i - 1]["date"]))

        # Lump the vote with the previous date.
        else:
            rollcall_list[i]["date"] = rollcall_list[i - 1]["date"]
            logging.error("Replacing %s with %s (but might be as late as %s)." % (rollcall_list[i]["date_unparsed"], rollcall_list[i - 1]["date"], rollcall_list[i + 1]["date"]))

    # Form the output data.

    vote_output_list = []

    for rollcall_number in rollcall_list:
        vote_results = votes[rollcall_number - 1]
        rollcall = rollcall_list[rollcall_number]

        # Which session is this in? Compare the vote's date to the sessions.tsv file.
        if not rollcall["date"]:
            logging.error("Vote on %s was an invalid date, so we can't determine the session to save the file.. | %s" % (rollcall["date_unparsed"], rollcall["description"]))
            continue

        s_congress, session = session_from_date(rollcall["date"], session_dates)
        if s_congress != congress:
            # should not occur - handled above
            logging.error("Vote on %s disagrees about which Congress it is in." % rollcall["date"])
            continue
        if session is None:
            # This vote did not occur durring a session of Congress. Some sort of data error.
            logging.error("Vote on %s is not within a session of Congress." % rollcall["date"])
            continue

        # Only process votes from the requested session.
        if options.get("session") and session != options["session"]:
            continue

        rollcall['result'] = "unknown"
        if "description" in rollcall:
            parse_rollcall_description(rollcall)

        # Make the votes dictionary, but also replace the description
        # text when it contains coded vote information.
        votes_dict = build_votes_dict(vote_results, rollcall)

        # Form the vote dict.
        vote_output = {
            "vote_id": "%s%s-%d.%s" % (chamber, rollcall_number, congress, session),
            "source_url": "http://www.voteview.com",
            "updated_at": datetime.datetime.fromtimestamp(time.time()),

            "congress": congress,
            "session": session,
            "chamber": chamber,
            "number": rollcall_number,  # XXX: This is not the right number.
            "question": rollcall["description"] if "description" in rollcall else None,  # Sometimes there isn't a description.
            "type": normalize_vote_type(rollcall["description"]) if "description" in rollcall else None,
            "date": datetime.date(*[int(dd) for dd in rollcall["date"].split("-")]),  # turn YYYY-MM-DD into datetime.date() instance
            "date_unparsed": rollcall["date_unparsed"],
            "votes": votes_dict,
            "presidents_position": presidents_positions.get(rollcall_number) or rollcall.get('presidents_position'),
            "bill": rollcall.get('bill'),

            "category": "unknown",
            "requires": "unknown",
            "result": rollcall['result'],
        }

        vote_output_list.append(vote_output)

    return vote_output_list


def put_vote(vote, options):
    output_vote(vote, options, id_type="bioguide")
    return {"ok": True, "saved": True}


def normalize_vote_type(descr):
    if descr.startswith("TO PASS "):
        return "On Passage"
    if descr.startswith("TO AMEND "):
        return "On the Amendment"
    if descr.startswith("TO CONCUR IN THE SENATE AMENDMENT "):
        return "Concurring in the Senate Amendment"
    if descr.startswith("TO READ THE SECOND TIME "):
        return "Reading the Second Time"
    if descr.startswith("TO ADVISE AND CONSENT TO THE RATIFICATION OF THE TREATY"):
        return "On the Treaty"
    #logging.error("Unknown vote type: " + descr)
    return descr
