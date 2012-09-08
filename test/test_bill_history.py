import unittest
import bill_info
import fixtures

import datetime

class BillHistory(unittest.TestCase):

  def test_normal_enacted_bill(self):
    history = fixtures.bill("hr3590-111")['history']

    self.assertEqual(history['house_passage_result'], 'pass')
    self.assertEqual(self.to_date(history['house_passage_result_at']), "2010-03-21 22:48")
    self.assertEqual(history['senate_passage_result'], 'pass')
    self.assertEqual(self.to_date(history['senate_passage_result_at']), "2009-12-24")
    self.assertEqual(history['vetoed'], False)
    self.assertEqual(history['awaiting_signature'], False)
    self.assertEqual(history['enacted'], True)
    self.assertEqual(self.to_date(history["enacted_at"]), "2010-03-23")

  def to_date(self, time):
    if isinstance(time, str):
      return time
    else:
      return datetime.datetime.strftime(time, "%Y-%m-%d %H:%M")