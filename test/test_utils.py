import unittest
import bill_info
import requests
import mock
import utils


class UtilsTests(unittest.TestCase):

  def test_timeout(self):
    """
    Ensures that the scrapelib library is properly passed and passes the
    timeout parameter through to the requests library.
    """
    def raise_if_timeout_passed(*args, **kwargs):
        if 'timeout' in kwargs:
            raise requests.Timeout("Mocked timeout")

    with mock.patch('requests.Session.request', raise_if_timeout_passed):
        # This URL will never be accessed -- it just needs to be parseable
        self.assertRaises(requests.Timeout, utils.download, 'http://localhost/', options={'timeout': 1})

