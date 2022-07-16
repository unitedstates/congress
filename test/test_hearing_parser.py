import unittest
from parse_congress_convos import hearing_parser
import re
import copy

class TestHearingParser(unittest.TestCase):
    def setUp(self):
        self.parser = hearing_parser()

    def test_regex_pattern(self):
        pattern = self.parser.regex_pattern
        self.assertTrue(re.match(pattern, '\n Miss Doe. What are you?'))
        self.assertTrue(re.match(pattern, '\n Mr. Van Hollen. Fuck you'))
        self.assertTrue(re.match(pattern, '\n The Chairman. I call'))
        self.assertTrue(re.match(pattern, '\n   Dr. DeSaulnier. At'))
        self.assertTrue(re.match(pattern, '\n   Ms. Sup of New Mexico. What?'))
        
        self.assertEquals(re.match(pattern, '  Ms. Stapf. Certainly, that is my observation. '))

        self.assertFalse(re.match(pattern, 'I love the\ngeneral public.'))
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

        self.assertEquals(self.parser.clean_hearing_text('C O N T E N T S\n ---\n people or whatnot \n ---'), "")

    def test_identify_people_present(self):
        with open('test/fixtures/hearing_text/members_section1.txt') as f:
            members_section1 = f.read()
        members1 = self.parser.identify_people_present(members_section1, [])
        self.assertEqual(len(members1[0]), 68)

        with open('test/fixtures/hearing_text/members_section2.txt') as f:
            members_section2 = f.read()
        members2 = self.parser.identify_people_present(members_section2, [])
        self.assertEqual(len(members2[0]), 44)

        with open('test/fixtures/hearing_text/members_section3.txt') as f:
            members_section3 = f.read()
        members3 = self.parser.identify_people_present(members_section3, [])
        self.assertEqual(len(members3[0]), 19)
        

    def test_(self):
        print('setup')

if __name__ == '__main__':
    unittest.main()