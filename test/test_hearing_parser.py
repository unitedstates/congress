import unittest
from parse_congress_convos import hearing_parser
import re
import copy

class TestHearingParser(unittest.TestCase):
    def setUp(self):
        self.parser = hearing_parser()

    def test_regex_pattern(self):
        pattern = self.parser.regex_pattern
        # print(re.match(new_pattern, '\n mr. doe. what are you?', flags=re.I))
        self.assertTrue(re.match(pattern, '\n mr. doe. what are you?'))

if __name__ == '__main__':
    unittest.main()