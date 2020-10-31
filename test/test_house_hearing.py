import committee_meetings
import lxml.etree
import os
import unittest
import utils

# Parsing the House hearing info


class HearingInfo(unittest.TestCase):

    def test_hearing(self):
        committees = {}
        for c in utils.yaml_load(
                "test/fixtures/committees-current.yaml"):
            committees[c["thomas_id"]] = c
            if "house_committee_id" in c:
                committees[c["house_committee_id"] + "00"] = c
            c["subcommittees"] = dict((s["thomas_id"], s)
                                      for s in c.get("subcommittees", []))

        hearing_xml = "test/fixtures/hearings/sample_hearing.xml"
        file_xml = open(hearing_xml, "r")
        dom = lxml.etree.parse(file_xml)
        test_output = committee_meetings.parse_house_committee_meeting(
            '102252', dom, [], committees, {"debug": False}, None, ["BILLS-113hr4435ih.pdf", "BILLS-113hr4435ih.xml"])
        
#          event_id, dom, existing_meetings, committees, options, witnesses, uploaded_documents
        self.assertEqual(test_output['bill_ids'], ['hr4435-113'])
        self.assertEqual(test_output['chamber'], 'house')
        self.assertEqual(test_output['committee'], 'HSRU')
        self.assertEqual(test_output['congress'], 113)
        self.assertEqual(test_output['house_meeting_type'], 'HMTG')
        self.assertEqual(test_output['meeting_documents'][0][
                         'description'], 'H.R. 4435 (as introduced)')
        self.assertEqual(
            test_output['meeting_documents'][0]['bill_id'],
            'hr4435-113')
        self.assertEqual(
            test_output['meeting_documents'][0]['version_code'], 'ih')
        self.assertEqual(test_output['meeting_documents'][0]['type'], 'BR')
        self.assertEqual(
            test_output['meeting_documents'][0]['urls'], [
                        {'url': 'http://beta.congress.gov/113/bills/hr4435/BILLS-113hr4435ih.pdf', 'file_found': True}, 
                        {'url': 'http://beta.congress.gov/113/bills/hr4435/BILLS-113hr4435ih.xml', 'file_found': True},])
        self.assertEqual(test_output['occurs_at'], '2014-05-19T17:00:00')
        self.assertEqual(test_output['room'], 'CAPITOL H-313')
        self.assertEqual(test_output['subcommittee'], None)
        self.assertEqual(test_output[
                         'topic'], 'H.R. 4435\u2014National Defense Authorization Act for Fiscal Year 2015 [General Debate]; H.R. 4660\u2014Commerce, Justice, Science, and Related Agencies Appropriations Act, 2015')
        self.assertEqual(test_output[
                         'url'], 'http://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=102252')

    def test_witnesses(self):
        witness_xml = "test/fixtures/hearings/sample_witness.xml"
        file_xml = open(witness_xml, "r")
        witness_tree = lxml.etree.parse(file_xml)
        uploaded_documents = ["HHRG-113-GO25-Bio-CochraneJ-20140522.pdf"]
        event_id = "102266"
        test_output = committee_meetings.parse_witness_list(witness_tree, uploaded_documents, event_id)["hearing_witness_info"]

        self.assertEqual(test_output[0]['documents'][0]['type'], 'WB')
        self.assertEqual(
            test_output[0]['documents'][0]['description'], 'Cochrane Bio')
        self.assertEqual(test_output[0]['documents'][0]['urls'], [
                         {'url': 'http://docs.house.gov/meetings/GO/GO25/20140522/102266/HHRG-113-GO25-Bio-CochraneJ-20140522.pdf', 'file_found': True}])
        self.assertEqual(test_output[0]['house_event_id'], '102266')
        self.assertEqual(test_output[0]['first_name'], 'James')
        self.assertEqual(test_output[0]['last_name'], 'Cochrane')
        self.assertEqual(
            test_output[0]['position'],
            'Chief Information Officer and Executive Vice President')
        self.assertEqual(test_output[0]['organization'], 'U.S. Postal Service')
