import unittest
from unittest import mock

from congress.tasks import utils, votes


SENATE_MENU = b"""<vote_summary>
<congress>119</congress><session>1</session><congress_year>2025</congress_year>
<votes><vote><vote_number>00001</vote_number></vote><vote><vote_number>00002</vote_number></vote></votes>
</vote_summary>"""


class VoteListings(unittest.TestCase):

    def senate_download_options(self, session_year):
        calls = []

        def download(url, destination, options):
            calls.append(options)
            return SENATE_MENU.replace(b"2025", session_year.encode("ascii"))

        with mock.patch.object(utils, "download", download):
            vote_ids = votes.vote_ids_for_senate("119", session_year, {})
        return vote_ids, calls[0]

    def test_current_session_listing_is_redownloaded(self):
        with mock.patch.object(utils, "current_legislative_year", return_value=2025):
            vote_ids, options = self.senate_download_options("2025")
        self.assertEqual(vote_ids, ["s1-119.2025", "s2-119.2025"])
        self.assertTrue(options.get("force"))
        self.assertTrue(options.get("binary"))

    def test_past_session_listing_uses_cache(self):
        with mock.patch.object(utils, "current_legislative_year", return_value=2026):
            vote_ids, options = self.senate_download_options("2025")
        self.assertEqual(vote_ids, ["s1-119.2025", "s2-119.2025"])
        self.assertFalse(options.get("force", False))

    def test_cache_flag_keeps_listing_offline(self):
        with mock.patch.object(utils, "current_legislative_year", return_value=2025):
            options = votes.listing_options("2025", {"cache": True})
        self.assertEqual(options, {"cache": True})

    def test_listing_options_keeps_other_options(self):
        with mock.patch.object(utils, "current_legislative_year", return_value=2025):
            options = votes.listing_options("2025", {"fast": True})
        self.assertEqual(options, {"fast": True, "force": True})
