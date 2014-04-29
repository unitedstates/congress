import utils
import logging
import json

from bills import bill_ids_for, save_bill_search_state
from bill_info import fetch_bill, output_for_bill

from amendment_info import fetch_amendment


def run(options):
    amendment_id = options.get('amendment_id', None)
    bill_id = options.get('bill_id', None)

    search_state = {}

    if amendment_id:
        amendment_type, number, congress = utils.split_bill_id(amendment_id)
        to_fetch = [amendment_id]

    elif bill_id:
        # first, crawl the bill
        bill_type, number, congress = utils.split_bill_id(bill_id)
        bill_status = fetch_bill(bill_id, options)
        if bill_status['ok']:
            bill = json.loads(utils.read(output_for_bill(bill_id, "json")))
            to_fetch = [x["amendment_id"] for x in bill["amendments"]]
        else:
            logging.error("Couldn't download information for that bill.")
            return None

    else:
        congress = options.get('congress', utils.current_congress())

        to_fetch = bill_ids_for(congress, utils.merge(options, {'amendments': True}), bill_states=search_state)
        if not to_fetch:
            if options.get("fast", False):
                logging.warn("No amendments changed.")
            else:
                logging.error("Error figuring out which amendments to download, aborting.")

            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    if options.get('pages_only', False):
        return None

    logging.warn("Going to fetch %i amendments from congress #%s" % (len(to_fetch), congress))
    saved_amendments = utils.process_set(to_fetch, fetch_amendment, options)

    # keep record of the last state of all these amendments, for later fast-searching
    save_bill_search_state(saved_amendments, search_state)
