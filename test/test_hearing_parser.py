import unittest
from parse_congress_convos import hearing_parser
from link_speaker_to_congress_member import LinkSpeakerToCongressMember
import re
import copy

class TestHearingParser(unittest.TestCase):
    def setUp(self):
        all_congress_members = {}
        self.hearing_parser = hearing_parser(all_congress_members, {})
        self.link_speaker = LinkSpeakerToCongressMember(all_congress_members)

    def test_regex_pattern(self):
        pattern = self.hearing_parser.regex_pattern
        self.assertTrue(re.match(pattern, '\n Miss Doe. What are you?'))
        self.assertTrue(re.match(pattern, '\n Mr. Van Hollen. Fuck you'))
        self.assertTrue(re.match(pattern, '\n The Chairman. I call'))
        self.assertTrue(re.match(pattern, '\n   Dr. DeSaulnier. At'))
        self.assertTrue(re.match(pattern, '\n   Ms. Sup of New Mexico. What?'))

        self.assertFalse(re.match(pattern, 'I love the\ngeneral public.'))
        self.assertFalse(re.match(pattern, '\nDr. R. John Hansman Jr., T. Wilson Professor of Aeronautics'))


        self.assertEqual(5, self.hearing_parser._num_regex_groups)

    def test_clean_hearing_text(self):
        text_with_directions = """    Mrs. Maloney. Well, what----
    Dr. Walensky [continuing]. at CDC are deeply concerned
        """
        cleaned_text_with_directions = """    Mrs. Maloney. Well, what----
    Dr. Walensky. at CDC are deeply concerned
        """
        self.assertEquals(self.hearing_parser.clean_hearing_text(text_with_directions), cleaned_text_with_directions)

        self.assertEquals(self.hearing_parser.clean_hearing_text('C O N T E N T S\n ---\n Fred... 34'), "")

    def test_identify_people_present(self):
        correct_values = [23, 68, 44, 21, 55]

        for i in range(4):
            with open(f'test/fixtures/hearing_text/members_section{i}.txt') as f:
                members_section = f.read()
            members = self.link_speaker.identify_members(members_section)
            self.assertEqual(len(members[0]), correct_values[i])

    def test_(self):
        print('setup')

if __name__ == '__main__':
    unittest.main()