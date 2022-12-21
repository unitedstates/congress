from congress.tasks import utils
import logging
import re
import json
from lxml import etree
import copy
import datetime


def create_govtrack_xml(bill, options):
    govtrack_type_codes = {'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc'}
    root = etree.Element("bill")
    root.set("session", bill['congress'])
    root.set("type", govtrack_type_codes[bill['bill_type']])
    root.set("number", bill['number'])
    root.set("updated", utils.format_datetime(bill['updated_at']))

    def make_node(parent, tag, text, **attrs):
        if options.get("govtrack", False):
            # Rewrite bioguide_id attributes as just id with GovTrack person IDs.
            attrs2 = {}
            for k, v in attrs.items():
                if v:
                    if k == "bioguide_id":
                        # remap "bioguide_id" attributes to govtrack "id"
                        k = "id"
                        v = str(utils.translate_legislator_id('bioguide', v, 'govtrack'))
                    if k == "thomas_id":
                        # remap "thomas_id" attributes to govtrack "id"
                        k = "id"
                        v = str(utils.translate_legislator_id('thomas', v, 'govtrack'))
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
                n.set(k, str(v))
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
        if title['textVersionCode']:
            n.set("textVersionCode", title['textVersionCode'])
        if title['is_for_portion']:
            n.set("partial", "1")

    def get_legislator_id_attr(p):
      if "bioguide_id" in p: return { "bioguide_id": p["bioguide_id"] }
      if "thomas_id" in p: return { "thomas_id": p["thomas_id"] }
      return { }

    if bill['sponsor']:
        # TODO: Sponsored by committee?
        make_node(root, "sponsor", None, **get_legislator_id_attr(bill['sponsor']))
    else:
        make_node(root, "sponsor", None)

    cosponsors = make_node(root, "cosponsors", None)
    for cosp in bill['cosponsors']:
        n = make_node(cosponsors, "cosponsor", None, **get_legislator_id_attr(cosp))
        if cosp["sponsored_at"]:
            n.set("joined", cosp["sponsored_at"])
        if cosp.get("withdrawn_at"): # no longer present in GPO BILLSTATUS XML schema 3.0.0
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
        make_node(root, "summary", bill['summary']['text'], date=bill['summary']['date'], status=bill['summary']['as'])

    if bill.get('committee_reports'):
      committee_reports = make_node(root, "committee-reports", None)
      for report in bill.get('committee_reports', []):
          make_node(committee_reports, "report", report)

    return etree.tostring(root, pretty_print=True)


def sponsor_for(sponsor_dict):
    if sponsor_dict is None:
        # TODO: This can hopefully be removed. In testing s414-113
        # was missing sponsor data. But all bills have a sponsor?
        return None

    # TODO: Don't do regex matching here. Find another way.
    m = re.match(r'(?P<title>(Rep\.|Sen\.|Del\.|Resident Commissioner)) (?P<name>.*?) +\[(?P<party>[DRIL])-(?P<state>[A-Z][A-Z])(-(?P<district>\d{1,2}|At Large|None))?\]$',
        sponsor_dict['fullName'])

    if not m:
        raise ValueError(sponsor_dict)

    return {
        'title': m.group("title"),
        'name': m.group("name"), # the firstName, middleName, lastName fields have inconsistent capitalization - some are all uppercase
        'state': sponsor_dict["state"],
        'district': sponsor_dict.get("district"), # missing for senators
        #'party': m.group('party'),
        'bioguide_id': sponsor_dict['bioguideId'],
        'type': 'person'
    }

def summary_for(summaries):
    # Some bills are missing the summaries entirely?
    if summaries is None:
        return None

    # Take the most recent summary, by looking at the lexicographically last updateDate.
    summary = sorted(summaries, key = lambda s: s['updateDate'])[-1]

    # Build dict.
    return {
        "date": summary['updateDate'],
        "as": summary['actionDesc'],
        "asOf": summary['actionDate'],
        "text": strip_tags(summary['text']),
    }

def strip_tags(text):
    # Preserve paragraph breaks. Convert closing p tags (and surrounding whitespace) into two newlines. Strip trailing whitespace
    text = re.sub("\s*</\s*p\s*>\s*", "\n\n", text).strip()

    # naive stripping of tags, should work okay in this limited context
    text = re.sub("<[^>]+>", "", text)

    # compress and strip whitespace artifacts, except for the paragraph breaks
    text = re.sub("[ \t\r\f\v]{2,}", " ", text).strip()

    # Replace HTML entities with characters.
    text = utils.unescape(text)

    return text


def committees_for(committee_list):
    if committee_list is None:
        return []

    committee_list = committee_list['item']

    activity_text_map = {
        "Referred to": ["referral"],
        "Hearings by": ["hearings"],
        "Markup by": ["markup"],
        "Reported by": ["reporting"],
        "Discharged from": ["discharged"],
        "Reported original measure": ["origin", "reporting"],
    }

    def fix_subcommittee_name(name):
        return re.sub("(.*) Subcommittee$",
            lambda m : "Subcommittee on " + m.group(1),
            name)

    def get_activitiy_list(item):
        if not item['activities']:
            return []
        return sum([activity_text_map.get(i['name'], [i['name']]) for i in item['activities']['item']], [])

    def fixup_committee_name(name):
        # Preserve backwards compatiblity.
        if name == "House House Administration":
            return "House Administration"
        return name

    def build_dict(item):
        committee_dict = {
            'activity': get_activitiy_list(item),
            'committee': fixup_committee_name(item['chamber'] + ' ' + re.sub(" Committee$", "", item['name'])),
            'committee_id': item['systemCode'][0:-2].upper(),
        }

        subcommittees_list = []
        if 'subcommittees' in item and item['subcommittees'] is not None:
            for subcommittee in item['subcommittees']['item']:
                subcommittee_dict = copy.deepcopy(committee_dict)
                subcommittee_dict.update({
                    'subcommittee': fix_subcommittee_name(subcommittee['name']),
                    'subcommittee_id': subcommittee['systemCode'][-2:],
                    'activity': get_activitiy_list(subcommittee),
                })
                subcommittees_list.append(subcommittee_dict)

        return [committee_dict] + subcommittees_list

    return sum([build_dict(committee) for committee in committee_list], [])


def titles_for(title_list):
    def build_dict(item):

        full_type = item['titleType']
        is_for_portion = False

        # "Official Titles as Introduced", "Short Titles on Conference report"
        splits = re.split(" as | on ", full_type, 1)
        if len(splits) == 2:
            title_type, state = splits

            if state.endswith(" for portions of this bill"):
                is_for_portion = True
                state = state.replace(" for portions of this bill" ,"")

            state = state.replace(":", "").lower()
        else:
            title_type, state = full_type, None

        if "Popular Title" in title_type:
            title_type = "popular"
        elif "Short Title" in title_type:
            title_type = "short"
        elif "Official Title" in title_type:
            title_type = "official"
        elif "Display Title" in title_type:
            title_type = "display"
        elif title_type == "Non-bill-report":
            # TODO: What kind of title is this? Maybe assign
            # a better title_type code once we know.
            title_type = "nonbillreport"
        else:
            raise Exception("Unknown title type: " + title_type)

        return {
            'title': item['title'],
            'is_for_portion': is_for_portion,
            'as': state,
            'textVersionCode': item.get('TextVersionCode'),
            'type': title_type
        }

    titles = [build_dict(title) for title in title_list]

    # THOMAS used to give us the titles in a particular order:
    #  short as introduced
    #  short as introduced (for portion)
    #  short as some later stage
    #  short as some later stage (for portion)
    #  official as introduced
    #  official as some later stage
    # The "as" stages (introduced, etc.) were in the order in which actions
    # actually occurred. This was handy because to get the current title for
    # a bill, you need to know which action type was most recent. The new
    # order is reverse-chronological, so we have to turn the order around
    # for backwards compatibility. Rather than do a simple .reverse(), I'm
    # adding an explicit sort order here which gets very close to the THOMAS
    # order.
    # Unfortunately this can no longer be relied on because the new bulk
    # data has the "as" stages sometimes in the wrong order: The "reported to
    # senate" status for House bills seems to be consistently out of place.
    titles_copy = list(titles) # clone before beginning sort
    def first_index_of(**kwargs):
        for i, title in enumerate(titles_copy):
            for k, v in kwargs.items():
                k = k.replace("_", "")
                if title.get(k) != v:
                    break
            else:
                # break not called --- all match
                return i
    titles.sort(key = lambda title: (
        # keep the same 'short', 'official', 'display' order intact
        first_index_of(type=title['type']),

        # within each of those categories, reverse the 'as' order
        -first_index_of(type=title['type'], _as=title.get('as')),

        # put titles for portions last, within the type/as category
        title['is_for_portion'],

        # and within that, just sort alphabetically, case-insensitively (which is
        # what it appears THOMAS used to do)
        title['title'].lower(),
        ))

    return titles

# the most current title of a given type is the first one in the last 'as' subgroup
# of the titles for the whole bill (that is, if there's no title for the whole bill
# in the last 'as' subgroup, use the previous 'as' subgroup and so on) --- we think
# this logic matches THOMAS/Congress.gov.


def current_title_for(titles, title_type):
    current_title = None
    current_as = -1  # not None, cause for popular titles, None is a valid 'as'

    for title in titles:
        if title['type'] != title_type or title['is_for_portion'] == True:
            continue
        if title['as'] == current_as:
            continue
        # right type, new 'as', store first one
        current_title = title['title']
        current_as = title['as']

    return current_title


def actions_for(action_list, bill_id, title):
    # The bulk XML data has action history information from multiple sources. For
    # major actions, the Library of Congress (code 9) action item often duplicates
    # the information of a House/Senate action item. We have to skip one so that we
    # don't tag multiple history items with the same parsed action info, which
    # would imply the action (like a vote) ocurred multiple times. THOMAS appears
    # to have suppressed the Library of Congress action lines in certain cases
    # to avoid duplication - they were not in our older data files.
    #
    # Also, there are some ghost action items with totally empty text. Remove those.
    # TODO: When removed from upstream data, we can remove that check.
    closure = {
        "prev": None,
    }
    def keep_action(item, closure):
        if item['text'] in (None, ""):
            return False

        keep = True
        if closure['prev']:
            if item['sourceSystem'].get('code') == "9":
                # Date must match previous action..
                # If both this and previous have a time, the times must match.
                # The text must approximately match. Sometimes the LOC text has a prefix
                #   and different whitespace. And they may drop references -- so we'll
                # use our action_for helper function to drop references from both
                # prior to the string comparison.
                if   item['actionDate'] == closure["prev"]["actionDate"] \
                 and (item.get('actionTime') == closure["prev"].get("actionTime") or not item.get('actionTime') or not closure["prev"].get("actionTime")) \
                 and action_for(item)['text'].replace(" ", "").endswith(action_for(closure["prev"])['text'].replace(" ", "")):

                    keep = False
        closure['prev'] = item
        return keep

    action_list = [item for item in action_list
        if keep_action(item, closure)]

    # Turn the actions into dicts. The actions are in reverse-chronological
    # order in the bulk data XML. Process them in chronological order so that
    # our bill status logic sees the actions in the right order.

    def build_dict(item, closure):
        action_dict = action_for(item)

        extra_action_info, new_status = parse_bill_action(action_dict, closure['prev_status'], bill_id, title)

        # only change/reflect status change if there was one
        if new_status:
            action_dict['status'] = new_status
            closure['prev_status'] = new_status

        # add additional parsed fields
        if extra_action_info:
            action_dict.update(extra_action_info)

        return action_dict

    closure = {
        "prev_status": "INTRODUCED",
    }
    return [build_dict(action, closure) for action in reversed(action_list)]


# clean text, pull out the action type, any other associated metadata with an action
def action_for(item):
    # acted_at

    if not item.get('actionTime'):
        acted_at = item.get('actionDate', '')
    else:    
        # Although we get the action date & time in an ISO-ish format (split
        # across two fields), and although we know it's in local time at the
        # U.S. Capitol (i.e. U.S. Eastern), we don't know the UTC offset which
        # is a part of how we used to serialize the time. So parse and then
        # use pytz (via format_datetime) to re-serialize.
        acted_at = utils.format_datetime(datetime.datetime.strptime(item.get('actionDate', '') + " " + item['actionTime'], "%Y-%m-%d %H:%M:%S"))

    # text & references
    # (amendment actions don't always have text?)

    text = item['text'] if item.get('text') is not None else ''

    # strip out links
    text = re.sub(r"</?[Aa]( \S.*?)?>", "", text)

    # remove and extract references
    references = []
    match = re.search("\s*\(([^)]+)\)\s*$", text)
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

    # extract committee IDs
    if item.get('committee'):
      # Data format through Dec. 13, 2019 had only one <committee/> (though node could be empty).
      committee_nodes = [item['committee']]
    elif item.get('committees'):
      # Starting on Dec. 13, 2019, and with a slow rollout, multiple committees could be specified.
      # Thankfully our JSON output format allowed it already.
      committee_nodes = item['committees'].get("item", [])
    else:
      # <committee/> or <committees/>, whichever was present, was empty
      committee_nodes = []

    # form dict

    action_dict = {
        'acted_at': acted_at,
        'action_code': item.get('actionCode', ''),
        'committees': [committee_item['systemCode'][0:-2].upper() for committee_item in committee_nodes] if committee_nodes else None, # if empty, store None
        'references': references,
        'type': 'action', # replaced by parse_bill_action if a regex matches 
        'text': text,
    }

    if not action_dict["committees"]:
        # remove if empty - not present in how we used to generate the file
        del action_dict["committees"]


    # sometimes there are links (one case is for bills passed by a rule in a resolution, the link will point to the resolution)
    if (item.get("links") or {}).get("link") is not None:
        action_dict["links"] = item["links"]["link"]

    return action_dict


def cosponsors_for(cosponsors_list):
    if cosponsors_list is None:
        return []

    cosponsors_list = cosponsors_list['item']

    def build_dict(item):
        cosponsor_dict = sponsor_for(item)
        del cosponsor_dict["type"] # always 'person'
        cosponsor_dict.update({
            'sponsored_at': item['sponsorshipDate'],
            # 'withdrawn_at': item['sponsorshipWithdrawnDate'], # no longer present in GPO BILLSTATUS XML schema 3.0.0?
            'original_cosponsor': item['isOriginalCosponsor'] == 'True'
        })
        return cosponsor_dict

    cosponsors = [build_dict(cosponsor) for cosponsor in cosponsors_list]

    # TODO: Can remove. Sort like the old THOMAS order to make diffs easier.
    cosponsors.sort(key = lambda c: c['name'].lower())

    return cosponsors


def related_bills_for(related_bills_list):
    if related_bills_list is None:
        return []

    related_bills_list = related_bills_list['item']

    def build_dict(item):

        return {
            'reason': item['relationshipDetails']['item'][0]['type'].replace('bill', '').strip().lower(),
            'bill_id': '{0}{1}-{2}'.format(item['type'].replace('.', '').lower(), item['number'], item['congress']),
            'type': 'bill',
            'identified_by': item['relationshipDetails']['item'][0]['identifiedBy']
        }

        # Are these THOMAS related bill relation texts gone from the bulk data?
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

    return [build_dict(related_bill) for related_bill in related_bills_list]

# get the public or private law number from any enacted action


def slip_law_from(actions):
    for action in actions:
        if action["type"] == "enacted":
            return {
                'law_type': action["law"],
                'congress': action["congress"],
                'number': action["number"]
            }

# find the latest status change in a set of processed actions


def latest_status(actions, introduced_at):
    status, status_date = "INTRODUCED", introduced_at
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
    line = re.sub(", the Passed", ", Passed", line) # 106 h4733 and others
    m = re.search("("
        + "|".join([
            "On passage",
            "Passed House",
            "Two-thirds of the Members present having voted in the affirmative the bill is passed,?",
            "On motion to suspend the rules and pass the (?:bill|resolution)",
            "On agreeing to the (?:resolution|conference report)",
            "On motion to suspend the rules and agree to the (?:resolution|conference report)",
            "House Agreed to Senate Amendments.*?",
            "On motion (?:that )?the House (?:suspend the rules and )?(?:agree(?: with an amendment)? to|concur in) the Senate amendments?(?: to the House amendments?| to the Senate amendments?)*",
        ])
        + ")"
        + "(, the objections of the President to the contrary notwithstanding.?)?"
        + "(, as amended| \(Amended\))?"
        + "\.? (Passed|Failed|Agreed to|Rejected)?" # hr1625-115 has a stray period here
        + " ?(by voice vote|without objection|by (the Yeas and Nays?|Yea-Nay Vote|recorded vote)"
        + "(:? \(2/3 required\))?: (\d+ ?- ?\d+(, \d+ Present)? [ \)]*)?\((Roll no\.|Record Vote No:) \d+\))",
        line, re.I)
    if m != None:
        motion, is_override, as_amended, pass_fail, how = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)

        # print(line)
        # print(m.groups())

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
        if "the House agree with an amendment" in motion:
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
        if bill_id == "s2012-114" and "Roll no. 250" in line: as_amended = True
        if bill_id == "s2943-114" and "On passage Passed without objection" in line: as_amended = True

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, suspension, as_amended, title, prev_status)
        if new_status:
            status = new_status

    # Passed House, not necessarily by an actual vote (think "deem")
    m = re.search(r"Passed House pursuant to|House agreed to Senate amendment (with amendment )?pursuant to|Pursuant to the provisions of [HSCONJRES\. ]+ \d+, [HSCONJRES\. ]+ \d+ is considered passed House", line, re.I)
    if m != None:
        vote_type = "vote" if (bill_type[0] == "h") else "vote2"
        if "agreed to Senate amendment" in line: vote_type = "pingpong"
        pass_fail = "pass"
        as_amended = ("with amendment" in line) or ("as amended" in line)

        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = "by special rule"
        action["where"] = "h"
        action["result"] = pass_fail

        # It's always pursuant to another bill, and a bill number is given in the action line, which we parse out
        # into the bill_ids field of the action. It's also represented
        # structurally in the links->link elements of the original XML which we just put in "links".

        # get the new status of the bill after this vote
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, False, as_amended, title, prev_status)

        if new_status:
            status = new_status

    m = re.search(r"Pursuant to .* the following bills passed under suspension of the rules: (.*)\.$", line, re.I)
    if m:
        # The list should certainly include this bill, but was it passed "as amended"?
        as_amended = None
        bill_list = m.group(1)
        bill_list = bill_list.replace("and the following resolution was agreed to under suspension of the rules: ", "")
        bill_list = bill_list.replace("and the following resolutions were agreed to under suspension of the rules: ", "")
        bill_list = bill_list.replace("and ", "")
        bill_list = re.split(r"\s*(?:;|,(?! as amended))\s*", bill_list)
        for bill_item in bill_list:
            bill_item = bill_item.lower().replace(".", "").replace(" ", "").split(",")
            if bill_item[0] == (bill_type + number):
                as_amended = len(bill_item) > 1
        if as_amended is None: raise ValueError("Did not find bill in list: " + line)

        vote_type = "vote" if (bill_type[0] == "h") else "vote2"
        pass_fail = "pass"
        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = "by special rule"
        action["where"] = "h"
        action["result"] = pass_fail
        new_status = new_status_after_vote(vote_type, pass_fail == "pass", "h", bill_type, False, as_amended, title, prev_status)
        if new_status:
            status = new_status

    # House motions to table adversely dispose of a pending matter, if agreed to. An agreed-to "motion to table the measure",
    # which is very infrequent, kills the legislation. If not agreed to, nothing changes. So this regex only captures
    # agreed-to motions to table.
    m = re.search("On motion to table the measure Agreed to"
        + " ?(by voice vote|without objection|by (the Yeas and Nays|Yea-Nay Vote|recorded vote)"
        + ": (\d+ - \d+(, \d+ Present)? [ \)]*)?\((Roll no\.|Record Vote No:) \d+\))",
        line, re.I)
    if m != None:
        how = m.group(1)
        pass_fail = 'fail'

        # In order to classify this as resulting in the same thing as regular failed vote on passage, new_status_after_vote
        # needs to know if this was a vote in the originating chamber or not.
        if prev_status in ("INTRODUCED", "REPORTED") or bill_id.startswith("hres"):
            vote_type = "vote"
        elif False:
            vote_type = "vote2"
        else:
            raise Exception("Need to classify %s as being in the originating chamber or not." % prev_status)

        roll = None
        m = re.search(r"\((Roll no\.|Record Vote No:) (\d+)\)", how, re.I)
        if m != None:
            how = "roll"  # normalize the ugly how
            roll = m.group(2)

        action["type"] = "vote"
        action["vote_type"] = vote_type
        action["how"] = how
        action['where'] = "h"
        action['result'] = pass_fail
        if roll:
            action["roll"] = roll

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
        "Senate receded from its amendment and concurred", # hr1-115
        r"Cloture \S*\s?on the motion to proceed .*?not invoked in Senate",
        r"Cloture(?: motion)? on the motion to proceed to the (?:bill|measure) invoked in Senate",
        "Cloture invoked in Senate",
        "Cloture on (?:the motion to (?:proceed to |concur in )(?:the House amendment (?:to the Senate amendment )?to )?)(?:the bill|H.R. .*) (?:not )?invoked in Senate",
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
        if re.search("disagreed|not invoked", motion, re.I):
            pass_fail = "fail"
        elif re.search("passed|agreed|concurred|invoked", motion, re.I):
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

    # Useless. But GovTrack has had it.
    m = re.search(r"Placed on (the )?([\w ]+) Calendar( under ([\w ]+))?[,\.] Calendar No\. (\d+)\.", line, re.I)
    if m != None:
        action["type"] = "calendar"
        action["calendar"] = m.group(2)
        action["under"] = m.group(4)
        action["number"] = m.group(5)

    # COMMITTEE ACTIONS

    # Ordered Reported (because GovTrack did this, but maybe should be changed to not combine with actual reported bills)
    m = re.search(r"Ordered to be Reported|Committee Agreed to Seek Consideration Under Suspension of the Rules", line, re.I)
    if m != None:
        action["type"] = "ordered-reported"
        if prev_status in ("INTRODUCED", "REFERRED"):
            status = "REPORTED"

    # reported
    m = re.search(r"Committee on (.*)\. (Original measure )?[Rr]eported (to Senate )?by", line, re.I)
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

    m = re.search("Sent to Archivist of the United States unsigned", line, re.I)
    if m != None:
        status = "ENACTED:TENDAYRULE"

    m = re.search("^(?:Became )?(Public|Private) Law(?: No:)? ([\d\-]+)\.", line, re.I)
    if m != None:
        action["law"] = m.group(1).lower()
        pieces = m.group(2).split("-")
        action["congress"] = pieces[0]
        action["number"] = pieces[1]
        action["type"] = "enacted"
        if prev_status in ("ENACTED:SIGNED", "ENACTED:VETO_OVERRIDE", "ENACTED:TENDAYRULE"):
            pass  # this is a final administrative step
        elif prev_status == "PROV_KILL:VETO" or prev_status.startswith("VETOED:"):
            # somehow missed the override steps
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

    # sweep the action line for bill IDs of related bills
    bill_ids = utils.extract_bills(line, congress)
    bill_ids = [b for b in bill_ids if b != bill_id]
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
                # The override passed both chambers -- the veto is overridden.
                return "ENACTED:VETO_OVERRIDE"
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


def amendments_for(amendment_list):
    if amendment_list is None:
        return []

    amendment_list = amendment_list['amendment']

    def build_dict(item):
        # Malformed XML containing duplicate elements causes attributes to parse as a list
        for attr in ['type', 'number', 'congress']:
            if type(item[attr]) is list:
                item[attr] = item[attr][0]
        return {
            'amendment_id': "{0}{1}-{2}".format(item['type'].lower(), item['number'], item['congress']),
            'amendment_type': item['type'].lower(),
            'chamber': item['type'][0].lower(),
            'number': item['number']
        }
    return [build_dict(amendment) for amendment in amendment_list]

def committee_reports_for(committeeReports):
    ret = []
    for report in (committeeReports or {}).get("committeeReport", []):
        ret.append( report["citation"] )
    return ret
