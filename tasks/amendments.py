import utils
import logging

from bills import bill_ids_for, save_bill_search_state

from amendment_info import fetch_amendment

def run(options):
  amdt_id = options.get('amendment_id', None)
  
  search_state = { }

  if amdt_id:
    amdt_type, number, congress = utils.split_bill_id(amdt_id)
    to_fetch = [amdt_id]
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

  save_bill_search_state(saved_amendments, search_state)
