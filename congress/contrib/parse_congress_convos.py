from bs4 import BeautifulSoup
import re
from typing import Dict, List


class hearing_parser():
    """
    Used to parse the text of a hearing.

    ...

    Attributes
    ----------
    regex_pattern : str
        a very complex regex pattern which takes into account all
        known ways transcriptors introduce new speakers.

    Methods
    -------
    parse_hearing(content: BeautifulSoup)
        parses the text of a hearing and returns the speakers
        and what they said.
    """

    TITLE_PATTERNS = [
        'chairwoman', 'chairman', 'mr.', 'ms.', 'mrs.',
        'dr.', 'senator', 'general', 'hon.'
    ]

    ONE_OFF = ['the chairwoman', 'the chairman']

    def construct_regex(self):
        pattern = ''
        title_patterns = '|'.join(self.TITLE_PATTERNS)
        enlongated_title = '(?: of \w+)?' # ex: mr. doe of miami
        title_patterns = f'\n\s*((?:{title_patterns}) (\w+){enlongated_title}\.)'
        #TODO what about 2 last names?
        #TODO add one offs
        pattern = title_patterns

        return pattern

    def __init__(self):
        self.regex_pattern = self.construct_regex()

    def save_to_file(self):
        with open(f"hearings/{self.id}.html", "w") as file:
            file.write(str(self.soup))

    def parse_hearing(self, content: BeautifulSoup) -> Dict[str, List[str]]: 
        speakers_and_text = re.split(self.regex_pattern, content.text, flags=re.I)
        speaker_groups = self.group_speakers(speakers_and_text)
        return speaker_groups

    def group_speakers(self, speakers_and_text: List[str]) -> Dict[str, List[str]]:
        speaker_groups = {}

        for speaker_group in [speakers_and_text[x:x+3] for x in range(1, len(speakers_and_text), 3)]:
            speaker_group = [x.lower().strip() for x in speaker_group]
            match, name, text = speaker_group
            # TODO: in 117hhrg47271 they wrote goodpseed instead of goodspeed. 
            # Probably too much of an edge case, but keep it in mind
            speaker_groups[name] = speaker_groups.get(name, []) + [text]

        return speaker_groups


with open(f"hearings/CHRG-117hhrg47271.html", "r") as file:
    parser = hearing_parser()
    content = BeautifulSoup(file.read(), 'html.parser')
    # speakers_and_text = re.split(contruct_regex(), content.text, flags=re.I)
    parser.parse_hearing(content)
    content.text
