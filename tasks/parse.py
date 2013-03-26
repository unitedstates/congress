import logging
import utils
import json
from amendment_code import parse_amendment_text
from utils import write

def run(options):
  bill_id = options.get('bill_id', None)
  if not bill_id:
      logging.error("You must specificy a bill")
      return None
    
  bill_type, number, congress = utils.split_bill_id(bill_id)
  # TODO run scripts to get bill and extract text if not found
  print "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, "data.json")
  try:
    bill = json.load(open("%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, "data.json"), 'r'))
  except:
    logging.error("Couldn't find bill. Have you scraped it yet?")
    return None

  try:                  
    data = json.load(open("%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, "lines.json"), 'r'))
  except:
    logging.error("Couldn't find text of bill. Have you run --extract yet?")
    return None

  start = options.get('start', None)
  if not start:
    start = int(bill["amendments"][0]["number"])

  end = options.get('end', None)
  if not end:
    end = int(bill["amendments"][-1]["number"])

  all_amendments = {}

  for a in range(start, end+1):
    logging.info("Parsing amendment %d" % a)
    try:
        amendment = json.load(open("data/%s/amendments/samdt/samdt%s/text.json" % (congress, a), 'r'))       
    except:
        print "Couldn't find parsed text for amendment %d" % a
        continue
    amendment = parse_amendment_text(amendment, data)
    if len(amendment["commands"]):
        logging.info("Found %d commands in amendment %d" % (len(amendment["commands"]), a))
        all_amendments[str(a)] = amendment
    else:
        logging.info("Didn't find any commands in amendment %d" % a)
                     
  write(json.dumps(all_amendments, indent=2), "data/%s/amendments/samdt/combined/%i_%i.json" % (congress, start, end))
  
