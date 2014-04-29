import unittest
import bill_info
import fixtures

# Parsing the bill information


class BillInfo(unittest.TestCase):

    def test_summary(self):
        bill_id = "hr547-113"
        bill_html = fixtures.open_bill(bill_id)
        expected_summary = "Border Security and Responsibility Act 2013 - Directs the Secretary of Homeland Security (DHS), the Secretary of the Interior, the Secretary of Agriculture (USDA), the Secretary of Defense (DOD), and the Secretary of Commerce, in consultation with tribal, state, and local officials, to submit to Congress a border protection strategy for the international land borders of the United States. Specifies strategy elements.\n\nAmends the the Illegal Immigration Reform and Immigrant Responsibility Act of 1996 to revise international land border security provisions, including: (1) eliminating existing southwest border fencing requirements; (2) requiring that border control actions be in accordance with the border strategy required under this Act; and (3) giving priority to the use of remote cameras, sensors, removal of nonnative vegetation, incorporation of natural barriers, additional manpower, unmanned aerial vehicles, or other low impact border enforcement techniques.\n\nProhibits construction of border fencing, physical barriers, roads, lighting, cameras, sensors, or other tactical infrastructure prior to 90 days after such border strategy's submission to Congress.\n\nDirects the Secretary of Homeland Security, in consultation with the Secretary of the Interior, the Secretary of Agriculture, the Secretary of Defense, the Secretary of Commerce, and the heads of appropriate state and tribal wildlife agencies, to implement a comprehensive monitoring and mitigation plan to address the ecological and environmental impacts of security infrastructure and activities along the international land borders of the United States. Specifies plan requirements."
        summary_text = bill_info.summary_for(bill_html)['text']
        self.assertEqual(summary_text, expected_summary)
