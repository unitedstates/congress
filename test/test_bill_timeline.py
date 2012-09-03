import unittest
import bill_info
import fixtures

class BillTimeline(unittest.TestCase):

  def test_load_fixture(self):
    bill = fixtures.bill("hr3590-111")
    