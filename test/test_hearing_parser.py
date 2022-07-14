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
        self.assertTrue(re.match(pattern, '\n the chairman. i call'))
        self.assertTrue(re.match(pattern, '\n   dr. walensky. at'))

        self.assertFalse(re.match(pattern, 'i love the\ngeneral public.'))
        self.assertFalse(re.match(pattern, '\nDr. R. John Hansman Jr., T. Wilson Professor of Aeronautics'))

        self.assertEqual(5, self.parser._num_regex_groups)

    def test_clean_hearing_text(self):
        text_with_directions = """    Mrs. Maloney. Well, what----
    Dr. Walensky [continuing]. at CDC are deeply concerned
        """
        cleaned_text_with_directions = """    Mrs. Maloney. Well, what----
    Dr. Walensky. at CDC are deeply concerned
        """
        self.assertEquals(self.parser.clean_hearing_text(text_with_directions), cleaned_text_with_directions)

    def test_identify_people_present(self):
        with open('test/fixtures/hearing_text/members_section1.txt') as f:
            members_section1 = f.read()
        members1 = self.parser.identify_people_present(members_section1, [])
        self.assertNotEqual(members1, [])

        with open('test/fixtures/hearing_text/members_section2.txt') as f:
            members_section2 = f.read()
        members2 = self.parser.identify_people_present(members_section2, [])
        self.assertNotEqual(members2, [])

        with open('test/fixtures/hearing_text/members_section3.txt') as f:
            members_section3 = f.read()
        members3 = self.parser.identify_people_present(members_section3, [])
        self.assertNotEqual(members3, [])
        

    def test_(self):
        print('setup')

if __name__ == '__main__':
    unittest.main()