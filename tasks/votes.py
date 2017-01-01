import utils
import json
import iso8601
import datetime
import os
import os.path
import re
import urlparse
import time
import datetime
from lxml import html, etree
import logging

import vote_info


def run(options):
    vote_id = options.get('vote_id', None)

    if vote_id:
        vote_chamber, vote_number, congress, session_year = utils.split_vote_id(vote_id)
        to_fetch = [vote_id]
    else:
        congress = options.get('congress', None)
        if congress:
            session_year = options.get('session', None)
            if not session_year:
                logging.error("If you provide a --congress, provide a --session year.")
                return None
        else:
            congress = utils.current_congress()
            session_year = options.get('session', str(utils.current_legislative_year()))

        chamber = options.get('chamber', None)

        if chamber == "house":
            to_fetch = vote_ids_for_house(congress, session_year, options)
        elif chamber == "senate":
            to_fetch = vote_ids_for_senate(congress, session_year, options)
        else:
            to_fetch = (vote_ids_for_house(congress, session_year, options) or []) + (vote_ids_for_senate(congress, session_year, options) or [])

        if not to_fetch:
            if not options.get("fast", False):
                logging.error("Error figuring out which votes to download, aborting.")
            else:
                logging.warn("No new or recent votes.")
            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    if options.get('pages_only', False):
        return None

    logging.warn("Going to fetch %i votes from congress #%s session %s" % (len(to_fetch), congress, session_year))

    utils.process_set(to_fetch, vote_info.fetch_vote, options)

# page through listing of House votes of a particular congress and session


def vote_ids_for_house(congress, session_year, options):
    vote_ids = []

    index_page = "http://clerk.house.gov/evs/%s/index.asp" % session_year
    group_page = r"ROLL_(\d+)\.asp"
    link_pattern = r"http://clerk.house.gov/cgi-bin/vote.asp\?year=%s&rollnumber=(\d+)" % session_year

    # download index page, find the matching links to the paged listing of votes
    page = utils.download(
        index_page,
        "%s/votes/%s/pages/house.html" % (congress, session_year),
        options)

    if not page:
        logging.error("Couldn't download House vote index page, skipping")
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
        page = utils.download(
            urlparse.urljoin(index_page, link.get("href")),
            "%s/votes/%s/pages/house_%s.html" % (congress, session_year, grp),
            options)

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
            if not should_process(vote_id, options):
                continue
            vote_ids.append(vote_id)

    return utils.uniq(vote_ids)


def vote_ids_for_senate(congress, session_year, options):
    session_num = int(session_year) - utils.get_congress_first_year(int(congress)) + 1

    vote_ids = []

    url = "http://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_%s_%d.xml" % (congress, session_num)
    page = utils.download(
        url,
        "%s/votes/%s/pages/senate.xml" % (congress, session_year),
        utils.merge(options, {'binary': True})
    )

    if not page or "Requested Page Not Found (404)" in page:
        logging.error("Couldn't download Senate vote XML index %s, skipping" % url)
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
        if not should_process(vote_id, options):
            continue
        vote_ids.append(vote_id)
    return vote_ids


def should_process(vote_id, options):
    if not options.get("fast", False):
        return True

    # If --fast is used, only download new votes or votes taken in the last
    # three days (when most vote changes and corrections should occur).
    f = vote_info.output_for_vote(vote_id, "json")
    if not os.path.exists(f):
        return True

    v = json.load(open(f))
    now = utils.eastern_time_zone.localize(datetime.datetime.now())
    return (now - iso8601.parse_date(v["date"])) < datetime.timedelta(days=3)
