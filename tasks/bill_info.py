import utils
import logging
import re
import json
from lxml import etree
import time
import datetime
from lxml.html import fromstring, HtmlElement

# can be run on its own, just require a bill_id


def run(options):
    bill_id = options.get('bill_id', None)

    if bill_id:
        result = fetch_bill(bill_id, options)
        logging.warn("\n%s" % result)
    else:
        logging.error("To run this task directly, supply a bill_id.")


# download and cache landing page for bill
# can raise an exception under various conditions
def fetch_bill(bill_id, options):
    logging.info("\n[%s] Fetching..." % bill_id)

    # fetch committee name map, if it doesn't already exist
    bill_type, number, congress = utils.split_bill_id(bill_id)
    if not utils.committee_names:
        utils.fetch_committee_names(congress, options)

    # fetch bill details body
    body = utils.download(
        bill_url_for(bill_id),
        bill_cache_for(bill_id, "information.html"),
        options)

    if not body:
        return {'saved': False, 'ok': False, 'reason': "failed to download"}

    if options.get("download_only", False):
        return {'saved': False, 'ok': True, 'reason': "requested download only"}

    if reserved_bill(body):
        logging.warn("[%s] Reserved bill, not real, skipping..." % bill_id)
        return {'saved': False, 'ok': True, 'reason': "reserved bill"}

    # conditions where we want to parse the bill from multiple pages instead of one:

    # 1) the all info page is truncated (~5-10 bills a congress)
    #     e.g. s1867-112, hr2112-112, s3240-112
    if "</html>" not in body:
        logging.info("[%s] Main page truncated, fetching many pages..." % bill_id)
        bill = parse_bill_split(bill_id, body, options)

    # 2) there are > 150 amendments, use undocumented amendments list (~5-10 bills a congress)
    #     e.g. hr3590-111, sconres13-111, s3240-112
    elif too_many_amendments(body):
        logging.info("[%s] Too many amendments, fetching many pages..." % bill_id)
        bill = parse_bill_split(bill_id, body, options)

    # 3) when I feel like it
    elif options.get('force_split', False):
        logging.info("[%s] Forcing a split, fetching many pages..." % bill_id)
        bill = parse_bill_split(bill_id, body, options)

    # Otherwise, get the bill's data from a single All Information page
    else:
        bill = parse_bill(bill_id, body, options)

    output_bill(bill, options)

    # output PDF and/or HTML file if requested

    if not options.get("formats", False):
        return {'ok': True, 'saved': True}

    status = {'ok': True, 'saved': True}

    options["formats"] = options["formats"].lower()

    if options["formats"].lower() == "all":
        formats = ["pdf", "html"]
    else:
        formats = options["formats"].split(",")

    gpo_urls = get_GPO_url_for_bill(bill_id, options)

    for fmt in formats:
        if gpo_urls and fmt in gpo_urls:
            utils.write(utils.download(gpo_urls[fmt], bill_cache_for(bill_id, "bill." + fmt), {'binary': True}), output_for_bill(bill_id, fmt))
            logging.info("Saving %s format for %s" % (fmt, bill_id))
            status[fmt] = True
        else:
            status[fmt] = False

    return status


def parse_bill(bill_id, body, options):
    bill_type, number, congress = utils.split_bill_id(bill_id)

    # parse everything out of the All Information page
    introduced_at = introduced_at_for(body)
    by_request = parse_by_request(body)
    sponsor = sponsor_for(body)
    cosponsors = cosponsors_for(body)
    summary = summary_for(body)
    titles = titles_for(body)
    actions = actions_for(body, bill_id)
    related_bills = related_bills_for(body, congress, bill_id)
    subjects = subjects_for(body)
    committees = committees_for(body, bill_id)
    amendments = amendments_for(body, bill_id)

    return process_bill(bill_id, options, introduced_at, by_request, sponsor, cosponsors,
                        summary, titles, actions, related_bills, subjects, committees, amendments)


# parse information pieced together from various pages
def parse_bill_split(bill_id, body, options):
    bill_type, number, congress = utils.split_bill_id(bill_id)

    # get some info out of the All Info page, since we already have it
    introduced_at = introduced_at_for(body)
    by_request = parse_by_request(body)
    sponsor = sponsor_for(body)
    subjects = subjects_for(body)

    # cosponsors page
    cosponsors_body = utils.download(
        bill_url_for(bill_id, "P"),
        bill_cache_for(bill_id, "cosponsors.html"),
        options)
    cosponsors_body = utils.unescape(cosponsors_body)
    cosponsors = cosponsors_for(cosponsors_body)

    # summary page
    summary_body = utils.download(
        bill_url_for(bill_id, "D"),
        bill_cache_for(bill_id, "summary.html"),
        options)
    summary_body = utils.unescape(summary_body)
    summary = summary_for(summary_body)

    # titles page
    titles_body = utils.download(
        bill_url_for(bill_id, "T"),
        bill_cache_for(bill_id, "titles.html"),
        options)
    titles_body = utils.unescape(titles_body)
    titles = titles_for(titles_body)

    # actions page
    actions_body = utils.download(
        bill_url_for(bill_id, "X"),
        bill_cache_for(bill_id, "actions.html"),
        options)
    actions_body = utils.unescape(actions_body)
    actions = actions_for(actions_body, bill_id)

    related_bills_body = utils.download(
        bill_url_for(bill_id, "K"),
        bill_cache_for(bill_id, "related_bills.html"),
        options)
    related_bills_body = utils.unescape(related_bills_body)
    related_bills = related_bills_for(related_bills_body, congress, bill_id)

    amendments_body = utils.download(
        bill_url_for(bill_id, "A"),
        bill_cache_for(bill_id, "amendments.html"),
        options)
    amendments_body = utils.unescape(amendments_body)
    amendments = amendments_for_standalone(amendments_body, bill_id)

    committees_body = utils.download(
        bill_url_for(bill_id, "C"),
        bill_cache_for(bill_id, "committees.html"),
        options)
    committees_body = utils.unescape(committees_body)
    committees = committees_for(committees_body, bill_id)

    return process_bill(bill_id, options, introduced_at, by_request, sponsor, cosponsors,
                        summary, titles, actions, related_bills, subjects, committees, amendments)


# take the initial parsed content, extract more information, assemble output data
def process_bill(bill_id, options,
                 introduced_at, by_request, sponsor, cosponsors,
                 summary, titles, actions, related_bills, subjects, committees, amendments):

    bill_type, number, congress = utils.split_bill_id(bill_id)

    # for convenience: extract out current title of each type
    official_title = current_title_for(titles, "official")
    short_title = current_title_for(titles, "short")
    popular_title = current_title_for(titles, "popular")

    # add metadata to each action, establish current status
    actions = process_actions(actions, bill_id, official_title, introduced_at)

    # pull out latest status change and the date of it
    status, status_date = latest_status(actions)
    if not status:  # default to introduced
        status = "INTRODUCED"
        status_date = introduced_at

    # pull out some very useful history information from the actions
    history = history_from_actions(actions)

    slip_law = slip_law_from(actions)

    return {
        'bill_id': bill_id,
        'bill_type': bill_type,
        'number': number,
        'congress': congress,
        
        'url': bill_url_for(bill_id),

        'introduced_at': introduced_at,
        'by_request': by_request,
        'sponsor': sponsor,
        'cosponsors': cosponsors,

        'actions': actions,
        'history': history,
        'status': status,
        'status_at': status_date,
        'enacted_as': slip_law,

        'titles': titles,
        'official_title': official_title,
        'short_title': short_title,
        'popular_title': popular_title,

        'summary': summary,
        'subjects_top_term': subjects[0],
        'subjects': subjects[1],

        'related_bills': related_bills,
        'committees': committees,
        'amendments': amendments,

        'updated_at': datetime.datetime.fromtimestamp(time.time()),
    }


def output_bill(bill, options):
    logging.info("[%s] Writing to disk..." % bill['bill_id'])

    # output JSON - so easy!
    utils.write(
        json.dumps(bill, sort_keys=True, indent=2, default=utils.format_datetime),
        output_for_bill(bill['bill_id'], "json"),
        options=options,
    )

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
                        # remap "thomas_id" attributes to govtrack "id"
                        k = "id"
                        v = str(utils.get_govtrack_person_id('thomas', v))
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
        make_node(root, "summary", re.sub(r"^0|(/)0", lambda m: m.group(1), datetime.datetime.strftime(datetime.datetime.strptime(bill['summary']['date'], "%Y-%m-%d"), "%m/%d/%Y")) + "--" + bill['summary'].get('as', '?') + ".\n" + bill['summary']['text'])  # , date=bill['summary'].get('date'), status=bill['summary'].get('as'))

    utils.write(
        etree.tostring(root, pretty_print=True),
        output_for_bill(bill['bill_id'], "xml"),
        options=options
    )


# This routine is also used by amendment processing. One difference is the
# lack of <b> tags on amendment pages but their presence on bill pages.
# Also, amendments can be sponsored by committees.
def sponsor_for(body):
    match = re.search(r"(?:<b>)?Sponsor: (?:</b>)?(No Sponsor|<a href=[^>]+\+(\d{5}|[hs]...\d\d).*>(.+)</a>(?:\s+\[((\w\w)(-(\d+))?)\])?)", body, re.I)
    if match:
        if (match.group(3) == "No Sponsor") or (match.group(1) == "No Sponsor"):
            return None
        elif match.group(4):  # has a state/district, so it's a rep
            if len(match.group(4).split('-')) == 2:
                state, district = match.group(4).split('-')
            else:
                state, district = match.group(4), None

            thomas_id = match.group(2)
            if not re.match(r"\d{5}$", thomas_id):
                raise Exception("Choked parsing sponsor.")

            # zero-pad and apply corrections
            thomas_id = "%05d" % int(thomas_id)
            thomas_id = utils.thomas_corrections(thomas_id)

            name = match.group(3).strip()
            title, name = re.search("^(Rep|Sen|Del|Com)\.? (.*?)$", name).groups()

            return {
                'type': 'person',
                'title': title,
                'name': name,
                'thomas_id': thomas_id,
                'state': state,
                'district': district
            }
        else:  # it's a committee
            committee_id = match.group(2)
            name = match.group(3).strip()
            if not re.match(r"[hs]...\d\d$", committee_id):
                raise Exception("Choked parsing apparent committee sponsor.")
            return {
                'type': 'committee',
                'name': name,
                'committee_id': committee_id,
            }

    else:
        raise Exception("Choked finding sponsor information.")


def summary_for(body):
    match = re.search("SUMMARY AS OF:</a></b>(.*?)(?:<hr|<div id=\"footer\">)", body, re.S)
    if not match:
        if re.search("<b>SUMMARY:</b><p>\*\*\*NONE\*\*\*", body, re.I):
            return None  # expected when no summary
        else:
            raise Exception("Choked finding summary.")

    ret = {}

    text = match.group(1).strip()

    # strip out the bold explanation of a new summary, if present
    text = re.sub("\s*<p><b>\(This measure.*?</b></p>\s*", "", text)

    # strip out the intro date thing
    sumdate = u"(\d+/\d+/\d+)--([^\s].*?)(\u00a0\u00a0\u00a0\u00a0\(There (is|are) \d+ <a href=\"[^>]+\">other (summary|summaries)</a>\))?(\n|<p>)"
    m = re.search(sumdate, text)
    if m:
        d = m.group(1)
        if d == "7/11/1794":
            d = "7/11/1974"  # THOMAS error
        ret["date"] = datetime.datetime.strptime(d, "%m/%d/%Y")
        ret["date"] = datetime.datetime.strftime(ret["date"], "%Y-%m-%d")
        ret["as"] = m.group(2)
        if ret["as"].endswith("."):
            ret["as"] = ret["as"][:-1]
    text = re.sub(sumdate, "", text)

    # Preserve paragraph breaks. Convert closing p tags (and surrounding whitespace) into two newlines. Strip trailing whitespace
    text = re.sub("\s*</\s*p\s*>\s*", "\n\n", text).strip()

    # naive stripping of tags, should work okay in this limited context
    text = re.sub("<[^>]+>", "", text)

    # compress and strip whitespace artifacts, except for the paragraph breaks
    text = re.sub("[ \t\r\f\v]{2,}", " ", text).strip()

    ret["text"] = text

    return ret


def parse_committee_rows(rows, bill_id):
    # counts on having been loaded already
    committee_names = utils.committee_names

    committee_info = []
    top_committee = None
    for row in rows:
        # ignore header/end row that contain no committee information
        match_header = re.search("</?table", row)
        if match_header:
            continue

        # identifies and pulls out committee name
        # Can handle committee names with letters, white space, dashes, slashes, parens, periods, apostrophes, and ampersands.
        match2 = re.search("(?<=\">)[-.\w\s,()\'&/]+(?=</a>)", row)
        if match2:
            committee = match2.group().strip()
            # remove excess internal spacing
            committee = re.sub("\\s{2,}", " ", committee)
        else:
            raise Exception("Couldn't find committee name. Line was: " + row)

        # identifies and pulls out committee activity
        match3 = re.search("(?<=<td width=\"65%\">).*?(?=</td>)", row)
        if match3:
            activity_string = match3.group().strip().lower()

            # splits string of activities into activity list
            activity_list = activity_string.split(",")

            # strips white space from each activity in list
            activity = []
            for x in activity_list:
                activity.append(x.strip())

        else:
            raise Exception("Couldn't find committee activity.")

        # identifies subcommittees by change in table cell width
        match4 = re.search("<td width=\"5%\">", row)
        if match4:
            if not top_committee:
                # Subcommittees are a little finicky, so don't raise an exception if the subcommittee can't be processed.
                logging.warn("[%s] Subcommittee specified without a parent committee: %s" % (bill_id, committee))
                continue
            committee_info.append({"committee": top_committee, "activity": activity, "subcommittee": committee, "committee_id": committee_names[top_committee]})
            # Subcommittees are a little finicky, so don't raise an exception if the subcommittee is not found.
            # Just skip writing the id attribute.
            try:
                committee_info[-1]["subcommittee_id"] = committee_names[committee_names[top_committee] + "|" + committee.replace("Subcommittee on ", "")]
            except KeyError:
                logging.warn("[%s] Subcommittee not found in %s: %s" % (bill_id, committee_names[top_committee], committee))

        else:
            top_committee = committee  # saves committee for the next row in case it is a subcommittee
            committee_info.append({"committee": committee, "activity": activity, "committee_id": committee_names[committee]})

    return committee_info


def committees_for(body, bill_id):
    # depends on them already having been loaded
    committee_names = utils.committee_names

    # grabs entire Committee & Subcommittee table
    match = re.search("COMMITTEE\(S\):<.*?<ul>.*?</table>", body, re.I | re.S)
    if match:
        committee_text = match.group().strip()

        # returns empty array for bills not assigned to a committee; e.g. bill_id=hr19-112
        none_match = re.search("\*\*\*NONE\*\*\*", committee_text)
        if none_match:
            committee_info = []
        else:
            # splits Committee & Subcommittee table up by table row
            rows = committee_text.split("</tr>")
            committee_info = parse_committee_rows(rows, bill_id)

        return committee_info

    if not match:
        raise Exception("Couldn't find committees section.")


def titles_for(body):
    match = re.search("TITLE\(S\):<.*?<ul>.*?<p><li>(.*?)(?:<hr|<div id=\"footer\">)", body, re.I | re.S)
    if not match:
        raise Exception("Couldn't find titles section.")

    titles = []

    text = match.group(1).strip()
    sections = text.split("<p><li>")
    for section in sections:
        if section.strip() == "":
            continue

        # move the <I> that indicates subsequent titles are for a portion of the bill
        # to after the <br> that follows it so that it's associated with the right title.
        section = re.sub("<I><br ?/>", "<br/><I>", section)

        # ensure single newlines between each title in the section
        section = re.sub("\n?<br ?/>", "\n", section)

        pieces = section.split("\n")

        full_type, type_titles = pieces[0], pieces[1:]
        if " AS " in full_type:
            type, state = full_type.split(" AS ")
            state = state.replace(":", "").lower()
        else:
            type, state = full_type, None

        if "POPULAR TITLE" in type:
            type = "popular"
        elif "SHORT TITLE" in type:
            type = "short"
        elif "OFFICIAL TITLE" in type:
            type = "official"
        else:
            raise Exception("Unknown title type: " + type)

        is_for_portion = False
        for title in type_titles:
            if title.startswith("<I>"):
                # This and subsequent titles in this piece are all for a portion of the bill.
                # The <I> tag will be removed below.
                is_for_portion = True

            # Strip, remove tabs, and replace whitespace and nonbreaking spaces with spaces,
            # since occasionally (e.g. s649-113) random \r's etc. appear instead of spaces.
            title = re.sub("<[^>]+>", "", title)  # strip tags
            title = re.sub(ur"[\s\u00a0]+", " ", title.strip())  # strip space and normalize spaces
            if title == "":
                continue

            if type == "popular":
                title = re.sub(r" \(identified.+?$", "", title)

            titles.append({
                'title': title,
                'is_for_portion': is_for_portion,
                'as': state,
                'type': type,
            })

    return titles

    if len(titles) == 0:
        raise Exception("No titles found.")

    return titles

# the most current title of a given type is the first one in the last 'as' subgroup
# of the titles for the whole bill (that is, if there's no title for the whole bill
# in the last 'as' subgroup, use the previous 'as' subgroup and so on) --- we think
# this logic matches THOMAS/Congress.gov.


def current_title_for(titles, type):
    current_title = None
    current_as = -1  # not None, cause for popular titles, None is a valid 'as'

    for title in titles:
        if title['type'] != type or title['is_for_portion'] == True:
            continue
        if title['as'] == current_as:
            continue
        # right type, new 'as', store first one
        current_title = title['title']
        current_as = title['as']

    return current_title


def actions_for(body, bill_id, is_amendment=False):
    if not is_amendment:
        match = re.search(">ALL ACTIONS:<.*?<dl>(.*?)(?:<hr|<div id=\"footer\">)", body, re.I | re.S)
    else:
        # This function is also used by amendment_info.py.
        match = re.search(">STATUS:<.*?<dl>(.*?)(?:<hr|<div id=\"footer\">)", body, re.I | re.S)

        # The Status section is optional for amendments.
        if not match:
            return None

    if not match:
        if re.search("ALL ACTIONS:((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
            return []  # no actions, can happen for bills reserved for the Speaker
        else:
            raise Exception("Couldn't find action section.")

    actions = []
    indentation_level = 0
    last_top_level_action = None
    last_committee_level_action = None

    text = match.group(1).strip()

    pieces = text.split("\n")
    for piece in pieces:
        if re.search("<strong>", piece) is None:
            continue

        action_pieces = re.search("((?:</?dl>)*)<dt><strong>(.*?):</strong><dd>(.+?)$", piece)
        if not action_pieces:
            raise Exception("Choked on parsing an action: %s" % piece)

        indentation_changes, timestamp, text = action_pieces.groups()

        # indentation indicates a committee action, track the indentation level
        for indentation_change in re.findall("</?dl>", indentation_changes):
            if indentation_change == "<dl>":
                indentation_level += 1
            if indentation_change == "</dl>":
                indentation_level -= 1
        if indentation_level < 0 or indentation_level > 2:
            raise Exception("Action indentation level %d out of bounds." % indentation_level)

        # timestamp of the action
        if re.search("(am|pm)", timestamp):
            action_time = datetime.datetime.strptime(timestamp, "%m/%d/%Y %I:%M%p")
        else:
            action_time = datetime.datetime.strptime(timestamp, "%m/%d/%Y")
            action_time = datetime.datetime.strftime(action_time, "%Y-%m-%d")

        cleaned_text, references = action_for(text)

        action = {
            'text': cleaned_text,
            'type': "action",
            'acted_at': action_time,
            'references': references
        }
        actions.append(action)

        # Associate subcommittee actions with the parent committee by including
        # a reference to the last top-level action line's dict, since we haven't
        # yet parsed which committee it is in. Likewise for 2nd-level indentation
        # to the top-level and 1st-level indentation actions. In some cases,
        # 2nd-level indentation occurs without any preceding 1st-level indentation.
        if indentation_level == 0:
            last_top_level_action = action
            last_committee_level_action = None
        elif indentation_level == 1:
            if last_top_level_action:
                action["committee_action_ref"] = last_top_level_action
            else:
                logging.info("[%s] Committee-level action without a preceding top-level action." % bill_id)
            last_committee_level_action = action
        elif indentation_level == 2:
            if last_top_level_action:
                action["committee_action_ref"] = last_top_level_action
                if last_committee_level_action:
                    action["subcommittee_action_ref"] = last_committee_level_action
                else:
                    logging.info("[%s] Sub-committee-level action without a preceding committee-level action." % bill_id)
            else:
                logging.info("[%s] Sub-committee-level action without a preceding top-level action." % bill_id)

    # THOMAS has a funny way of outputting actions. It is sorted by date,
    # except that committee events are grouped together. Once we identify
    # the committees related to events, we should sort the events properly
    # in time order. But (of course there's a but) not all dates have times,
    # meaning we will come to having to compare equal dates and dates with
    # times on those dates. In those cases, preserve the original order
    # of the events as shown on THOMAS.
    #
    # Note that we do this *before* process actions, since we must get
    # this in chronological order before running our status finite state machine.
    def action_comparer(a, b):
        a = a["acted_at"]
        b = b["acted_at"]
        if type(a) == str or type(b) == str:
            # If either is a plain date without time, compare them only on the
            # basis of the date parts, meaning the unspecified time is treated
            # as unknown, rather than treated as midnight.
            if type(a) == datetime.datetime:
                a = datetime.datetime.strftime(a, "%Y-%m-%d")
            if type(b) == datetime.datetime:
                b = datetime.datetime.strftime(b, "%Y-%m-%d")
        else:
            # Otherwise if both are date+time's, do a normal comparison
            pass
        return cmp(a, b)
    actions.sort(action_comparer)  # .sort() is stable, so original order is preserved where cmp == 0

    return actions


# clean text, pull out the action type, any other associated metadata with an action
def action_for(text):
    # strip out links
    text = re.sub(r"</?[Aa]( \S.*?)?>", "", text)

    # remove and extract references
    references = []
    match = re.search("\s+\(([^)]+)\)\s*$", text)
    if match:
        # remove the matched section
        text = text[0:match.start()] + text[match.end():]

        types = match.group(1)

        # fix use of comma or colon instead of a semi colon between reference types
        # have seen some accidental capitalization combined with accidental comma, thus the 'T'
        # e.g. "text of Title VII as reported in House: CR H3075-3077, Text omission from Title VII:" (hr5384-109)
        types = re.sub("[,:] ([a-zT])", r"; \1", types)
        # fix "CR:"
        types = re.sub("CR:", "CR", types)
        # fix a missing semicolon altogether between references
        # e.g. sres107-112, "consideration: CR S1877-1878 text as"
        types = re.sub("(\d+) +([a-z])", r"\1; \2", types)

        for reference in re.split("; ?", types):
            if ": " not in reference:
                type, reference = None, reference
            else:
                type, reference = reference.split(": ", 1)

            references.append({'type': type, 'reference': reference})

    return text, references


def introduced_at_for(body):
    doc = fromstring(body)

    introduced_at = None
    for meta in doc.cssselect('meta'):
        if meta.get('name') == 'dc.date':
            introduced_at = meta.get('content')

    if not introduced_at:
        raise Exception("Couldn't find an introduction date in the meta tags.")

    # maybe silly to parse and re-serialize, but I'd like to make explicit the format we publish dates in
    parsed = datetime.datetime.strptime(introduced_at, "%Y-%m-%d")
    return datetime.datetime.strftime(parsed, "%Y-%m-%d")


def parse_by_request(body):
    """
    Check whether the bill was introduced by the request.

    Return boolean value.
    """
    doc = fromstring(body)

    # Extract all text nodes from the range
    # <b>Sponsor: </b> .... <br />
    b_node = doc.xpath('//b[normalize-space(text()) = "Sponsor:"]')[0]
    text_items = []
    for node in b_node.xpath('.//following-sibling::node()'):
        if isinstance(node, HtmlElement):
            if node.tag == 'br':
                break
        if isinstance(node, unicode):
            text_items.append(unicode(node))
    text = u' '.join(text_items)
    return u'by request' in text


def cosponsors_for(body):
    match = re.search("COSPONSORS\((\d+)\).*?<p>(?:</br>)?(.*?)(?:</br>)?(?:<hr|<div id=\"footer\">)", body, re.S)
    if not match:
        none = re.search("COSPONSOR\(S\):</b></a><p>\*\*\*NONE\*\*\*", body)
        if none:
            return []  # no cosponsors, it happens, nothing to be ashamed of
        else:
            raise Exception("Choked finding cosponsors section.")

    count = match.group(1)
    text = match.group(2)

    # fix some bad line breaks
    text = re.sub("</br>", "<br/>", text)

    cosponsors = []

    lines = re.compile("<br ?/>").split(text)
    for line in lines:
        # can happen on stand-alone cosponsor pages
        if line.strip() == "</div>":
            continue

        m = re.search(r"<a href=[^>]+(\d{5}).*>(Rep|Sen) (.+?)</a> \[([A-Z\d\-]+)\]\s*- (\d\d?/\d\d?/\d\d\d\d)(?:\(withdrawn - (\d\d?/\d\d?/\d\d\d\d)\))?", line, re.I)
        if not m:
            raise Exception("Choked scanning cosponsor line: %s" % line)

        thomas_id, title, name, district, join_date, withdrawn_date = m.groups()

        # zero-pad thomas ID and apply corrections
        thomas_id = "%05d" % int(thomas_id)
        thomas_id = utils.thomas_corrections(thomas_id)

        if len(district.split('-')) == 2:
            state, district_number = district.split('-')
        else:
            state, district_number = district, None

        join_date = datetime.datetime.strptime(join_date, "%m/%d/%Y")
        join_date = datetime.datetime.strftime(join_date, "%Y-%m-%d")
        if withdrawn_date:
            withdrawn_date = datetime.datetime.strptime(withdrawn_date, "%m/%d/%Y")
            withdrawn_date = datetime.datetime.strftime(withdrawn_date, "%Y-%m-%d")

        cosponsors.append({
            'thomas_id': thomas_id,
            'title': title,
            'name': name,
            'state': state,
            'district': district_number,
            'sponsored_at': join_date,
            'withdrawn_at': withdrawn_date
        })

    return cosponsors


def subjects_for(body):
    doc = fromstring(body)
    subjects = []
    top_term = None
    for meta in doc.cssselect('meta'):
        if meta.get('name') == 'dc.subject':
            subjects.append(meta.get('content'))
            if not top_term:
                top_term = meta.get('content')
    subjects.sort()

    return top_term, subjects


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

# get the public or private law number from any enacted action


def slip_law_from(actions):
    for action in actions:
        if action["type"] == "enacted":
            return {
                'law_type': action["law"],
                'congress': action["congress"],
                'number': action["number"]
            }

# given the parsed list of actions from actions_for, run each action
# through metadata extraction and figure out what current status the bill is in


def process_actions(actions, bill_id, title, introduced_date):

    status = "INTRODUCED"  # every bill is at least introduced
    status_date = introduced_date
    new_actions = []

    for action in actions:
        new_action, new_status = parse_bill_action(action, status, bill_id, title)

        # only change/reflect status change if there was one
        if new_status:
            new_action['status'] = new_status
            status = new_status

        # an action can opt-out of inclusion altogether
        if new_action:
            action.update(new_action)
            new_actions.append(action)

            if "subcommittee_action_ref" in action:
                action["in_committee"] = action["committee_action_ref"].get("committee", None)
                action["in_subcommittee"] = action["subcommittee_action_ref"].get("subcommittee", None)
                del action["subcommittee_action_ref"]
                del action["committee_action_ref"]
            elif "committee_action_ref" in action:
                action["in_committee"] = action["committee_action_ref"].get("committee", None)
                del action["committee_action_ref"]

    return new_actions

# find the latest status change in a set of processed actions


def latest_status(actions):
    status, status_date = None, None
    for action in actions:
        if action.get('status', None):
            status = action['status']
            status_date = action['acted_at']
    return status, status_date

# look at the final set of processed actions and pull out the major historical events


def history_from_actions(actions):

    history = {}

    activation = activation_from(actions)
    if activation:
        history['active'] = True
        history['active_at'] = activation['acted_at']
    else:
        history['active'] = False

    house_vote = None
    for action in actions:
        if (action['type'] == 'vote') and (action['where'] == 'h') and (action['vote_type'] != "override"):
            house_vote = action
    if house_vote:
        history['house_passage_result'] = house_vote['result']
        history['house_passage_result_at'] = house_vote['acted_at']

    senate_vote = None
    for action in actions:
        if (action['type'] == 'vote') and (action['where'] == 's') and (action['vote_type'] != "override"):
            senate_vote = action
    if senate_vote:
        history['senate_passage_result'] = senate_vote['result']
        history['senate_passage_result_at'] = senate_vote['acted_at']

    senate_vote = None
    for action in actions:
        if (action['type'] == 'vote-aux') and (action['vote_type'] == 'cloture') and (action['where'] == 's') and (action['vote_type'] != "override"):
            senate_vote = action
    if senate_vote:
        history['senate_cloture_result'] = senate_vote['result']
        history['senate_cloture_result_at'] = senate_vote['acted_at']

    vetoed = None
    for action in actions:
        if action['type'] == 'vetoed':
            vetoed = action
    if vetoed:
        history['vetoed'] = True
        history['vetoed_at'] = vetoed['acted_at']
    else:
        history['vetoed'] = False

    house_override_vote = None
    for action in actions:
        if (action['type'] == 'vote') and (action['where'] == 'h') and (action['vote_type'] == "override"):
            house_override_vote = action
    if house_override_vote:
        history['house_override_result'] = house_override_vote['result']
        history['house_override_result_at'] = house_override_vote['acted_at']

    senate_override_vote = None
    for action in actions:
        if (action['type'] == 'vote') and (action['where'] == 's') and (action['vote_type'] == "override"):
            senate_override_vote = action
    if senate_override_vote:
        history['senate_override_result'] = senate_override_vote['result']
        history['senate_override_result_at'] = senate_override_vote['acted_at']

    enacted = None
    for action in actions:
        if action['type'] == 'enacted':
            enacted = action
    if enacted:
        history['enacted'] = True
        history['enacted_at'] = action['acted_at']
    else:
        history['enacted'] = False

    topresident = None
    for action in actions:
        if action['type'] == 'topresident':
            topresident = action
    if topresident and (not history['vetoed']) and (not history['enacted']):
        history['awaiting_signature'] = True
        history['awaiting_signature_since'] = action['acted_at']
    else:
        history['awaiting_signature'] = False

    return history


# find the first action beyond the standard actions every bill gets.
# - if the bill's first action is "referral" then the first action not those
#     most common
#     e.g. hr3590-111 (active), s1-113 (inactive)
# - if the bill's first action is "action", then the next action, if one is present
#     resolutions
#     e.g. sres5-113 (active), sres4-113 (inactive)
# - if the bill's first action is anything else (e.g. "vote"), then that first action
#     bills that skip committee
#     e.g. s227-113 (active)
def activation_from(actions):
    # there's NOT always at least one :(
    # as of 2013-06-10, hr2272-113 has no actions at all
    if len(actions) == 0:
        return None

    first = actions[0]

    if first['type'] in ["referral", "calendar", "action"]:
        for action in actions[1:]:
            if (action['type'] != "referral") and (action['type'] != "calendar") and ("Sponsor introductory remarks" not in action['text']):
                return action
        return None
    else:
        return first


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
        + "((:)? \(2/3 required\))?: \d+ - \d+(, \d+ Present)? [ \)]*\((Roll no\.|Record Vote No:) \d+\))",
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

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, suspension, as_amended, title, prev_status)
        if new_status:
            status = new_status

    # Passed House, not necessarily by an actual vote (think "deem")
    m = re.search(r"Passed House pursuant to", line, re.I)
    if m != None:
        vote_type = "vote" if (bill_type[0] == "h") else "vote2"
        pass_fail = "pass"

        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = "by special rule"
        action["where"] = "h"
        action["result"] = pass_fail

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, False, False, title, prev_status)

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
        elif bill_id in ("hr1589-94", "s2527-100", "hr1677-101", "hr2978-101", "hr2126-104", "s1322-104"):
            status = "ENACTED:TENDAYRULE"
        else:
            raise Exception("Missing Signed by President action? If this is a case of the 10-day rule, hard code the bill number here.")

    # Check for referral type
    m = re.search(r"Referred to (?:the )?(House|Senate)?\s?(?:Committee|Subcommittee)?", line, re.I)
    if m != None:
        action["type"] = "referral"
        if prev_status == "INTRODUCED":
            status = "REFERRED"

    # Check for committee name, and store committee ids

    # Build a regex to find mentioned committees in the action line.
    cmte_names = []
    for name in utils.committee_names.keys():
        # excluding subcommittee names (they have pipes),
        if name.find('|') == -1:
            # name = re.sub(r"\(.*\)", '', name).strip()
            name = re.sub(r"^(House|Senate) ", "", name)
            cmte_names.append(name)
    cmte_reg = r"(House|Senate)?\s*(?:Committee)?\s*(?:on)?\s*(?:the)?\s*({0})".format("|".join(cmte_names))

    # "Rules" occurs often in "suspend the rules" not referring to a committee, so
    # wipe that out so that it doesn't get picked up as House Rules and subsequently
    # generate an error for not, in lowercase?, actually matching a committee name.
    # Likewise for "budgetary" triggering the budget committees.
    line_for_cmte_reg = line.replace("suspend the rules", "XXX").replace("suspension of the rules", "XXX").replace("closed rule", "XXX")\
        .replace("budgetary", "XXX")

    m = re.search(cmte_reg, line_for_cmte_reg, re.I)
    if m:
        committees = []
        chamber = m.groups()[0]  # optional match

        # This could be made to look for multiple committee names.
        cmte_name_candidates = [" ".join([t for t in m.groups() if t is not None]).replace("House House", "House")]

        for cand in cmte_name_candidates:
            # many actions just say "Committee on the Judiciary", without a chamber
            # do our best to assign a chamber if we can be sure
            if ("House" not in cand) and ("Senate" not in cand):
                in_house = utils.committee_names.get("House %s" % cand, False)
                in_senate = utils.committee_names.get("Senate %s" % cand, False)
                if in_house and not in_senate:
                    cand = "House %s" % cand
                elif in_senate and not in_house:
                    cand = "Senate %s" % cand

                # if this action is a committee-level action (indented on THOMAS), look
                # at the parent action to infer the chamber
                elif len(action_dict.get("committee_action_ref", {}).get("committees", [])) > 0:
                    chamber = action_dict["committee_action_ref"]["committees"][0][0]  # H, S, or J
                    if chamber == "H":
                        cand = "House %s" % cand
                    elif chamber == "S":
                        cand = "Senate %s" % cand

                # look at other signals on the action line
                elif re.search("Received in the House|Reported to House", line):
                    cand = "House %s" % cand
                elif re.search("Received in the Senate|Reported to Senate", line):
                    cand = "Senate %s" % cand

                # if a bill is in an early stage where we're pretty sure activity is in the originating
                # chamber, fall back to the bill's originating chamber
                elif prev_status in ("INTRODUCED", "REFERRED", "REPORTED") and bill_id.startswith("h"):
                    cand = "House %s" % cand
                elif prev_status in ("INTRODUCED", "REFERRED", "REPORTED") and bill_id.startswith("s"):
                    cand = "Senate %s" % cand

            try:
                cmte_id = utils.committee_names[cand]
                committees.append(cmte_id)
            except KeyError:
                # pass
                logging.warn("[%s] Committee id not found for '%s' in action <%s>" % (bill_id, cand, line))
        if committees:
            action['committees'] = committees

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

# parse amendments out of undocumented standalone amendments page


def amendments_for_standalone(body, bill_id):
    bill_type, number, congress = utils.split_bill_id(bill_id)

    amendments = []

    for code, chamber, number in re.findall("<a href=\"/cgi-bin/bdquery/z\?d\d+:(SU|SP|HZ)\d+:\">(S|H)\.(?:UP\.)?AMDT\.(\d+)</a>", body, re.I):
        chamber = chamber.lower()

        # there are "senate unprinted amendments" for the 97th and 98th Congresses, with their own numbering scheme
        # make those use 'su' as the type instead of 's'
        amendment_type = chamber + "amdt"
        if code == "SU":
            amendment_type = "supamdt"

        amendments.append({
            'chamber': chamber,
            'amendment_type': amendment_type,
            'number': number,
            'amendment_id': "%s%s-%s" % (amendment_type, number, congress)
        })

    if len(amendments) == 0:
        if not re.search("AMENDMENT\(S\):((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
            raise Exception("Couldn't find amendments section.")

    return amendments


def amendments_for(body, bill_id):
    bill_type, number, congress = utils.split_bill_id(bill_id)

    # it is possible in older sessions for the amendments section to not appear at all.
    # if this method is being run, we know the page is not truncated, so if the header
    # is not at all present, assume the page is missing amendments because there are none.
    if not re.search("AMENDMENT\(S\):", body):
        return []

    amendments = []

    for code, chamber, number in re.findall("<b>\s*\d+\.</b>\s*<a href=\"/cgi-bin/bdquery/z\?d\d+:(SU|SP|HZ)\d+:\">(S|H)\.(?:UP\.)?AMDT\.(\d+)\s*</a> to ", body, re.I):
        chamber = chamber.lower()

        # there are "senate unprinted amendments" for the 97th and 98th Congresses, with their own numbering scheme
        # make those use 'supamdt' as the type instead of 's'
        amendment_type = chamber + "amdt"
        if code == "SU":
            amendment_type = "supamdt"

        amendments.append({
            'chamber': chamber,
            'amendment_type': amendment_type,
            'number': number,
            'amendment_id': "%s%s-%s" % (amendment_type, number, congress)
        })

    if len(amendments) == 0:
        if not re.search("AMENDMENT\(S\):((?:(?!\<hr).)+)\*\*\*NONE\*\*\*", body, re.S):
            raise Exception("Couldn't find amendments section.")

    return amendments


# are there at least 150 amendments listed in this body? a quick tally
# not the end of the world if it's wrong once in a great while, it just sparks
# a less efficient way of gathering this bill's data
def too_many_amendments(body):
    # example:
    # "<b>150.</b> <a href="/cgi-bin/bdquery/z?d111:SP02937:">S.AMDT.2937 </a> to <a href="/cgi-bin/bdquery/z?d111:HR03590:">H.R.3590</a>"
    amendments = re.findall("(<b>\s*\d+\.</b>\s*<a href=\"/cgi-bin/bdquery/z\?d\d+:(SP|HZ)\d+:\">(S|H)\.AMDT\.\d+\s*</a> to )", body, re.I)
    return (len(amendments) >= 150)

# bills reserved for the Speaker or Minority Leader are not actual legislation,
# just markers that the number will not be used for ordinary members' bills


def reserved_bill(body):
    if re.search("OFFICIAL TITLE AS INTRODUCED:((?:(?!\<hr).)+)Reserved for the (Speaker|Minority Leader)", body, re.S | re.I):
        return True
    else:
        return False

# fetch GPO URLs for PDF and HTML formats


def get_GPO_url_for_bill(bill_id, options):
    # we need the URL of the pdf on GPO
    # there may be a way to calculate it, but in the meantime we'll get it the old-fashioned way
    # first get the THOMAS landing page. This may be duplicating work, but didn't see anything
    # Maybe TODO -- reconcile with fdsys script (ideally without downloading large sitemaps for a single bill)
    bill_type, number, congress = utils.split_bill_id(bill_id)
    thomas_type = utils.thomas_types[bill_type][0]
    congress = int(congress)
    landing_url = "http://thomas.loc.gov/cgi-bin/bdquery/D?d%03d:%s:./list/bss/d%03d%s.lst:" % (congress, number, congress, thomas_type)
    landing_page = utils.download(
        landing_url,
        bill_cache_for(bill_id, "landing_page.html"),
        options)
    text_landing_page_url = "http://thomas.loc.gov/cgi-bin/query/z" + re.search('href="/cgi-bin/query/z?(.*?)">Text of Legislation', landing_page, re.I | re.S).groups(1)[0]
    text_landing_page = utils.download(
        text_landing_page_url,
        bill_cache_for(bill_id, "text_landing_page.html"),
        options)
    gpo_urls = re.findall('http://www.gpo.gov/fdsys/(.*?)\.pdf', text_landing_page, re.I | re.S)
    if not len(gpo_urls):
        logging.info("No GPO link discovered")
        return False
    # get last url on page, in cases where there are several versions of bill
    # THOMAS advises us to use the last one (e.g. http://thomas.loc.gov/cgi-bin/query/z?c113:S.CON.RES.1: )

    return {
        "pdf": "http://www.gpo.gov/fdsys/" + gpo_urls[-1] + ".pdf",
        "html": "http://www.gpo.gov/fdsys/" + gpo_urls[-1].replace("pdf", "html") + ".htm"
    }


# directory helpers

def output_for_bill(bill_id, format, is_data_dot=True):
    bill_type, number, congress = utils.split_bill_id(bill_id)
    if is_data_dot:
        fn = "data.%s" % format
    else:
        fn = format
    return "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, fn)

# defaults to "All Information" page for a bill


def bill_url_for(bill_id, page="L"):
    bill_type, number, congress = utils.split_bill_id(bill_id)
    thomas_type = utils.thomas_types[bill_type][0]
    congress = int(congress)
    return "http://thomas.loc.gov/cgi-bin/bdquery/z?d%03d:%s%s:@@@%s&summ2=m&" % (congress, thomas_type, number, page)


def bill_cache_for(bill_id, file):
    bill_type, number, congress = utils.split_bill_id(bill_id)
    return "%s/bills/%s/%s%s/%s" % (congress, bill_type, bill_type, number, file)
