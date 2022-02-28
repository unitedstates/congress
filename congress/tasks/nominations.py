from congress.tasks import utils
import os
import os.path
import re
from lxml import html, etree
import logging

from congress.tasks import nomination_info


def run(options):
    nomination_id = options.get('nomination_id', None)

    if nomination_id:
        nomination_type, number, congress = utils.split_nomination_id(nomination_id)
        to_fetch = [nomination_id]
    else:
        congress = options.get('congress', utils.current_congress())
        to_fetch = nomination_ids_for(congress, options)
        if not to_fetch:
            if options.get("fast", False):
                logging.warn("No nominations changed.")
            else:
                logging.error("Error figuring out which nominations to download, aborting.")
            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    logging.warn("Going to fetch %i nominations from congress #%s" % (len(to_fetch), congress))

    saved_nominations = utils.process_set(to_fetch, nomination_info.fetch_nomination, options)

# page through listings for bills of a particular congress


def nomination_ids_for(congress, options={}):
    nomination_ids = []

    page = page_for(congress, options)
    if not page:
        logging.error("Couldn't download page for %d congress" % congress)
        return None

    # extract matching links
    doc = html.document_fromstring(page)
    raw_nomination_ids = doc.xpath('//div[@id="content"]/p[2]/a/text()')
    nomination_ids = []

    for raw_id in raw_nomination_ids:
        pieces = raw_id.split(' ')

        # ignore these
        if raw_id in ["PDF", "Text", "split into two or more parts"]:
            pass
        elif len(pieces) < 2:
            logging.error("Bad nomination ID detected: %s" % raw_id)
            return None
        else:
            nomination_ids.append(pieces[1])

    return utils.uniq(nomination_ids)


def page_cache_for(congress):
    return "%s/nominations/pages/search.html" % congress

# unlike bills.py, we're going to fetch the page instead of producing the URL,
# since a POST is required.


def page_for(congress, options):
    congress = int(congress)
    postdata = {
        "database": "nominations",
        "MaxDocs": '5000',
        "submit": "SEARCH",
        "querytype": "phrase",
        "query": "",
        "Stemming": "No",
        "congress": "%d" % congress,
        "CIVcategory": "on",
        "LSTcategory": "on",
        "committee": "",
        "LBDateSel": "FLD606",
        "EBSDate": "",
        "EBEDate": "",
        "sort": "sh_docid_rc",
    }

    post_options = {'postdata': postdata}
    post_options.update(options)

    # unused: never cache search listing
    cache = page_cache_for(congress)

    page = utils.download("http://thomas.loc.gov/cgi-bin/thomas",
                          None,
                          post_options
                          )
    return page
