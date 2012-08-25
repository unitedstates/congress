import utils
from utils import log
import os

def run(options):
  session = options.get('session', utils.current_session())
  bill_id = options.get('bill_id', None)

  if not bill_id:
    log("Provide a 'bill_id' parameter to fetch data for an individual bill.")
    return

  fetch_bill(bill_id, options)


def fetch_bill(bill_id, options):
  if options.get('force', False):
    body = utils.download_now(handle_for(bill_id), cache_for(bill_id, "home.html"))
  else:
    body = utils.download(handle_for(bill_id), cache_for(bill_id, "home.html"))

  print body

def cache_for(bill_id, file):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "data/bills/%s/%s%s/%s" % (session, bill_type, number, file)

def handle_for(bill_id):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "http://hdl.loc.gov/loc.uscongress/legislation.%s%s%s" % (session, bill_type, number)