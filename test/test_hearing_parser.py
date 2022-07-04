import unittest
from parse_congress_convos import hearing_parser
import re
import copy

class TestHearingParser(unittest.TestCase):
    def setUp(self):
        self.parser = hearing_parser()

    def test_regex_pattern(self):
        pattern = self.parser.regex_pattern
        self.assertTrue(re.match(pattern, '\n mr. doe. what are you?'))
        self.assertTrue(re.match(pattern, '\n miss piper. fuck you'))
        # self.assertTrue(re.match(pattern, '\n the chairman. i call'))
        self.assertTrue(re.match(pattern, '\n   dr. walensky . at'))

        self.assertFalse(re.match(pattern, 'i love the\ngeneral public.'))
        self.assertFalse(re.match(pattern, '\nDr. R. John Hansman Jr., T. Wilson Professor of Aeronautics'))

    def test_clean_hearing_text(self):
        text_with_directions = """    Mrs. Maloney. Well, what----
    Dr. Walensky [continuing]. at CDC are deeply concerned
        """
        cleaned_text_with_directions = """    Mrs. Maloney. Well, what----
    Dr. Walensky . at CDC are deeply concerned
        """
        self.assertEquals(self.parser.clean_hearing_text(text_with_directions), cleaned_text_with_directions)

    def test_(self):
        print('setup')

if __name__ == '__main__':
    unittest.main()