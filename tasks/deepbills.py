import logging
import json
from datetime import datetime
import iso8601
import utils

from tasks import Task, current_congress
from tasks.bills import Bills


class Deepbills(Task):

    def __init__(self, options=None, config=None):
        super(Deepbills, self).__init__(options, config)

    def run(self):
        bill_version_id = self.options.get("bill_version_id", None)

        if bill_version_id:
            bill_type, bill_number, congress, version_code = Bills.split_bill_version_id(bill_version_id)
            bill_id = Bills.build_bill_id(bill_type, bill_number, congress)
        else:
            version_code = None
            bill_id = self.options.get("bill_id", None)

            if bill_id:
                bill_type, bill_number, congress = Bills.split_bill_id(bill_id)
            else:
                bill_type = bill_number = None
                congress = self.options.get("congress", current_congress())

        force = self.options.get("force", False)

        to_fetch = self.bill_version_ids_for(congress, bill_type, bill_number, version_code, force)

        if not to_fetch:
            return None

        self.process_set(to_fetch, self.write_bill_catoxml)

    def newer_version_available(self, our_filename, their_last_changed_timestamp):
        their_last_changed_datetime = iso8601.parse_date(their_last_changed_timestamp)
        return (not (self.storage.exists(our_filename) and
                (datetime.fromtimestamp(self.storage.fs.getinfo(our_filename).get('modified_time'),
                    their_last_changed_datetime.tzinfo) > their_last_changed_datetime)))

    def bill_version_ids_for(self, congress, bill_type=None, bill_number=None, version_code=None, force=False):
        if int(congress) < 113:
            logging.error("The DeepBills Project currently only supports the 113th Congress forward.")
            return

        # Bypass the bill index if the user is forcing a download and has provided enough information.
        if force and (version_code is not None) and (bill_number is not None) and (bill_type is not None):
            bill_version_id = utils.build_bill_version_id(bill_type, bill_number, congress, version_code)
            return [bill_version_id]

        bill_version_ids = []

        bill_index_json = self.fetch_bill_index_json()

        if len(bill_index_json) == 0:
            logging.error("Could not retrieve bill index. Aborting...")
            return

        for bill in bill_index_json:
            # Ignore bills from a different Congress than the one requested.
            if int(bill["congress"]) != int(congress):
                continue

            # Ignore bills with a different bill type than the one requested, if applicable.
            if (bill_type is not None) and (str(bill["billtype"]) != bill_type):
                continue

            # Ignore bills with a different bill number than the one requested, if applicable.
            if (bill_number is not None) and (str(bill["billnumber"]) != bill_number):
                continue

            # Ignore bills with a different version code than the one requested, if applicable.
            if (version_code is not None) and (str(bill["billversion"]) != version_code):
                continue

            bill_version_id = Bills.build_bill_version_id(bill["billtype"], bill["billnumber"], bill["congress"], bill["billversion"])

            # Only download a file that has a newer version available.
            if (not force) and (not self.newer_version_available(self.catoxml_filename_for(bill_version_id), bill["commitdate"])):
                logging.debug("No newer version of %s available." % (bill_version_id))
                continue
            else:
                logging.info("Adding %s to list of files to download." % (bill_version_id))

            bill_version_ids.append(bill_version_id)

        return bill_version_ids

    def fetch_bill_index_json(self):
        return json.loads(self.download("http://deepbills.cato.org/api/1/bills"))

    def deepbills_url_for(self, bill_version_id):
        bill_type, number, congress, version_code = Bills.split_bill_version_id(bill_version_id)
        return "http://deepbills.cato.org/api/1/bill?congress=%s&billtype=%s&billnumber=%s&billversion=%s" % (congress, bill_type, number, version_code)

    def fetch_single_bill_json(self, bill_version_id):
        return json.loads(self.download(self.deepbills_url_for(bill_version_id)))

    def extract_xml_from_json(self, single_bill_json):
        return single_bill_json["billbody"].encode("utf-8")

    def document_filename_for(self, bill_version_id, filename):
        bill_type, number, congress, version_code = Bills.split_bill_version_id(bill_version_id)
        return "%s/%s/bills/%s/%s%s/text-versions/%s/%s" % (self.storage.data_dir, congress, bill_type, bill_type, number, version_code, filename)

    def catoxml_filename_for(self, bill_version_id):
        return self.document_filename_for(bill_version_id, "catoxml.xml")

    def write_bill_catoxml(self, bill_version_id):
        catoxml_filename = self.catoxml_filename_for(bill_version_id)
        self.storage.write(self.extract_xml_from_json(self.fetch_single_bill_json(bill_version_id)), catoxml_filename)
        return {"ok": True, "saved": True}
