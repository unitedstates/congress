import json, os.path, logging
import utils

def run(options):
  bill_id = options.get('bill_id', None)
  bill_version_id = options.get('bill_version_id', None)

  # using a specific bill or version overrides the congress flag/default
  if bill_id:
    bill_type, number, congress = utils.split_bill_id(bill_id)
  elif bill_version_id:
    bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  else:
    congress = options.get('congress', utils.current_congress())

  if bill_version_id:
    to_fetch = [bill_version_id]
  else:
    to_fetch = bill_version_ids_for(congress, options)
    if not to_fetch:
      return None

  saved_versions = utils.process_set(to_fetch, write_bill_catoxml, options)

def bill_version_ids_for(only_congress, options):
  if int(only_congress) != 113:
    raise Exception("The DeepBills Project currently only supports the 113th Congress.")

  bill_version_ids = []

  bill_index_json = fetch_bill_index_json()
  if len(bill_index_json) == 0:
    logging.error("Error figuring out which bills to download, aborting.")

  for bill in bill_index_json:
    bill_ver_id = "%s%s-%s-%s" % (bill["billtype"], bill["billnumber"], bill["congress"], bill["billversion"])

    # Until we have last modified dates, just skip files if we've already downloaded them.
    fn = document_filename_for(bill_ver_id, "catoxml.xml")
    if os.path.exists(fn): continue

    bill_version_ids.append(bill_ver_id)

  return bill_version_ids

def fetch_bill_index_json():
  return json.loads(utils.download("http://deepbills.cato.org/api/1/bills"))

def deepbills_url_for(bill_version_id):
  bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  return "http://deepbills.cato.org/api/1/bill?congress=%s&billtype=%s&billnumber=%s&billversion=%s" % ( congress, bill_type, number, version_code )

def fetch_single_bill_json(bill_version_id):
  return json.loads(utils.download(deepbills_url_for(bill_version_id)))

def extract_xml_from_json(single_bill_json):
  return single_bill_json["billbody"].encode("utf-8")

def document_filename_for(bill_version_id, filename):
  bill_type, number, congress, version_code = utils.split_bill_version_id(bill_version_id)
  return "%s/%s/bills/%s/%s%s/text-versions/%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, version_code, filename)

def write_bill_catoxml(bill_version_id, options):
  fn = document_filename_for(bill_version_id, "catoxml.xml")

  utils.write(
    extract_xml_from_json(fetch_single_bill_json(bill_version_id)),
    fn
  )

  return {'ok': True, 'saved': True}
