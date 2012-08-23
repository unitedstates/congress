import utils
from utils import log


def run(options):
  session = options.get('session', utils.current_session())
  bill_id = options.get('bill_id', None)
  
  if not bill_id:
    log("Provide a 'bill_id' parameter to fetch data for an individual bill.")
    return

  print bill_id

  






def handle_for(session, bill_type, number):
  "http://hdl.loc.gov/loc.uscongress/legislation.%i%s%i" % (session, bill_type, number)