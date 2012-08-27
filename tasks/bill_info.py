import utils
from utils import log
import re
from pyquery import PyQuery as pq

def run(options):
  bill_id = options.get('bill_id', None)
  
  if bill_id:
    fetch_bill(bill_id, options)
  else:
    log("To run this task directly, supply a bill_id.")


# download and cache landing page for bill
# can raise an exception under various conditions
def fetch_bill(bill_id, options):
  log("[%s] Fetching..." % bill_id)

  body = utils.download(
    bill_url_for(bill_id), 
    bill_cache_for(bill_id, "information.html"),
    options.get('force', False))

  doc = pq(body, parser='html')
  
  sponsor = sponsor_for(body)
  summary = summary_for(doc)

  print summary


def sponsor_for(body):
  match = re.search(r"<b>Sponsor: </b>(No Sponsor|<a [^>]+>(.*)</a>\s+\[((\w\w)(-(\d+))?)\])", body, re.I)
  if match:
    if match.group(1) == "No Sponsor":
      return None
    else:
      return (match.group(2), match.group(3))
  else:
    raise Exception("Choked finding sponsor information.")

def summary_for(doc):
  selector = doc("b a")
  for i, elem in enumerate(selector):
    if elem.text == "SUMMARY AS OF:":
      parent = selector.eq(i).parent()
      
      summary = []

      next = parent.next()
      while len(next) > 0:
        if next[0].tag == "hr":
          break
        elif (next[0].tag == "p") or (next[0].tag == "ul"):
          if next[0].find("b") is None:
            fragment = next.text().strip()
            if fragment:
              summary.append(fragment)
        next = next.next()

      if len(summary) == 0:
        raise Exception("Choked finding summary.")

      return str.join("\n\n", summary)



# "All Information" page for a bill
def bill_url_for(bill_id):
  bill_type, number, session = utils.split_bill_id(bill_id)
  thomas_type = utils.thomas_types[bill_type][0]
  return "http://thomas.loc.gov/cgi-bin/bdquery/z?d%s:%s%s:@@@L&summ2=m&" % (session, thomas_type, number)

def bill_cache_for(bill_id, file):
  bill_type, number, session = utils.split_bill_id(bill_id)
  return "data/bills/%s/%s%s/%s" % (session, bill_type, number, file)