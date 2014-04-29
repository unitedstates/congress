import unittest
import bill_info
import fixtures
import utils

import datetime


class BillHistory(unittest.TestCase):

    # hr3590-111 went through everything except a veto

    def test_normal_enacted_bill(self):
        utils.fetch_committee_names(111, {'test': True})

        history = fixtures.bill("hr3590-111")['history']

        self.assertEqual(history['active'], True)
        self.assertEqual(self.to_date(history['active_at']), "2009-10-07 14:35")
        self.assertEqual(history['house_passage_result'], 'pass')
        self.assertEqual(self.to_date(history['house_passage_result_at']), "2010-03-21 22:48")
        self.assertEqual(history['senate_cloture_result'], 'pass')
        self.assertEqual(self.to_date(history['senate_cloture_result_at']), "2009-12-23")
        self.assertEqual(history['senate_passage_result'], 'pass')
        self.assertEqual(self.to_date(history['senate_passage_result_at']), "2009-12-24")
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], True)
        self.assertEqual(self.to_date(history["enacted_at"]), "2010-03-23")

    # s1-113 was introduced and went nowhere
    def test_introduced_bill(self):
        utils.fetch_committee_names(113, {'test': True})

        history = fixtures.bill("s1-113")['history']

        self.assertEqual(history['active'], False)
        self.assertTrue(not history.has_key('house_passage_result'))
        self.assertTrue(not history.has_key('house_passage_result_at'))
        self.assertTrue(not history.has_key('senate_cloture_result'))
        self.assertTrue(not history.has_key('senate_cloture_result_at'))
        self.assertTrue(not history.has_key('senate_passage_result'))
        self.assertTrue(not history.has_key('senate_passage_result_at'))
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], False)

    # s227-113 was introduced, read, and passed by unanimous consent without a referral,
    # then (at fixture-time) sat at the House
    def test_immediately_passed_bill(self):
        utils.fetch_committee_names(113, {'test': True})

        history = fixtures.bill("s227-113")['history']

        self.assertEqual(history['active'], True)
        self.assertEqual(self.to_date(history['active_at']), "2013-02-04")
        self.assertTrue(not history.has_key('house_passage_result'))
        self.assertTrue(not history.has_key('house_passage_result_at'))
        self.assertTrue(not history.has_key('senate_cloture_result'))
        self.assertTrue(not history.has_key('senate_cloture_result_at'))
        self.assertEqual(history['senate_passage_result'], 'pass')
        self.assertEqual(self.to_date(history['senate_passage_result_at']), "2013-02-04")
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], False)

    # sres5-113 was introduced, then 3 weeks later voted upon and failed on a voice vote
    def test_senate_resolution_failed_voice(self):
        utils.fetch_committee_names(113, {'test': True})

        history = fixtures.bill("sres5-113")['history']

        self.assertEqual(history['active'], True)
        self.assertEqual(self.to_date(history['active_at']), "2013-01-24")
        self.assertTrue(not history.has_key('house_passage_result'))
        self.assertTrue(not history.has_key('house_passage_result_at'))
        self.assertTrue(not history.has_key('senate_cloture_result'))
        self.assertTrue(not history.has_key('senate_cloture_result_at'))
        self.assertEqual(history['senate_passage_result'], 'fail')
        self.assertEqual(self.to_date(history['senate_passage_result_at']), "2013-01-24")
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], False)

    # sres4-113 was introduced, went nowhere (at fixture-time)
    def test_senate_resolution_went_nowhere(self):
        utils.fetch_committee_names(113, {'test': True})

        history = fixtures.bill("sres4-113")['history']

        self.assertEqual(history['active'], False)
        self.assertTrue(not history.has_key('house_passage_result'))
        self.assertTrue(not history.has_key('house_passage_result_at'))
        self.assertTrue(not history.has_key('senate_cloture_result'))
        self.assertTrue(not history.has_key('senate_cloture_result_at'))
        self.assertTrue(not history.has_key('senate_passage_result'))
        self.assertTrue(not history.has_key('senate_passage_result_at'))
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], False)

    # s1-111 was introduced, reported, went nowhere
    def test_senate_bill_reported_nowhere(self):
        utils.fetch_committee_names(111, {'test': True})

        history = fixtures.bill("s1-111")['history']

        self.assertEqual(history['active'], False)
        self.assertTrue(not history.has_key('house_passage_result'))
        self.assertTrue(not history.has_key('house_passage_result_at'))
        self.assertTrue(not history.has_key('senate_cloture_result'))
        self.assertTrue(not history.has_key('senate_cloture_result_at'))
        self.assertTrue(not history.has_key('senate_passage_result'))
        self.assertTrue(not history.has_key('senate_passage_result_at'))
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], False)

    def test_introductory_remarks_are_still_inactive(self):
        utils.fetch_committee_names(113, {'test': True})

        history = fixtures.bill("hr718-113")['history']

        self.assertEqual(history['active'], False)
        self.assertTrue(not history.has_key('house_passage_result'))
        self.assertTrue(not history.has_key('house_passage_result_at'))
        self.assertTrue(not history.has_key('senate_cloture_result'))
        self.assertTrue(not history.has_key('senate_cloture_result_at'))
        self.assertTrue(not history.has_key('senate_passage_result'))
        self.assertTrue(not history.has_key('senate_passage_result_at'))
        self.assertEqual(history['vetoed'], False)
        self.assertEqual(history['awaiting_signature'], False)
        self.assertEqual(history['enacted'], False)

    def to_date(self, time):
        if isinstance(time, str):
            return time
        else:
            return datetime.datetime.strftime(time, "%Y-%m-%d %H:%M")
