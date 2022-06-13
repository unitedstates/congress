from bs4 import BeautifulSoup
import re
from typing import Dict, List
from dataclasses import dataclass, field

@dataclass
class MemberInfo:
    name: str
    name_parsed: str
    last_name: str
    bioGuideId: str
    authorityId: str
    role: str
    state: str
    statements: List[str] = field(default_factory=list)

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

    def clean_hearing_text(self, text: str) -> str:
        additional_notes_pattern = r'\n*\[.*?\]'
        # text_to_be_removed = re.findall(additional_notes_pattern, text)
        cleaned_text = re.sub(additional_notes_pattern, '\n', text)
        return cleaned_text

    def group_speakers(self, speakers_and_text: List[str]) -> Dict[str, List[str]]:
        speaker_groups = {}

        for speaker_group in [speakers_and_text[x:x+3] for x in range(1, len(speakers_and_text), 3)]:
            speaker_group = [x.lower().strip() for x in speaker_group]
            match, name, text = speaker_group
            # TODO: in 117hhrg47271 they wrote goodpseed instead of goodspeed. 
            # Probably too much of an edge case, but keep it in mind
            speaker_groups[name] = speaker_groups.get(name, []) + [text]

        return speaker_groups

    def link_speaker_to_representative(self, speaker: str) -> List:
        """
        Given a speaker name, return the name of the representative
        """

        return speaker

    def grab_congress_info(self, metadata: BeautifulSoup) -> List[MemberInfo]:
        congress_sections = metadata.find_all('congMember')
        members = []
        if len(congress_sections) == 0:
            # TODO: not sure how to handle this
            print('No congress info found')
            # raise Exception('No congress sections found')
        for congress_member in congress_sections:
            name = congress_member.find('name', {'type': 'authority-fnf'}).text
            name_parsed = congress_member.find('name', {'type': 'parsed'}).text
            name_lnf = congress_member.find('name', {'type': 'authority-lnf'}).text
            last_name = name_lnf.split(',')[0]
            bioGuideId = congress_member.get('bioGuideId')
            authorityId = congress_member['authorityId']
            role = congress_member['role']
            state = congress_member['state']

            member_info = MemberInfo(name = name, name_parsed = name_parsed, last_name = last_name,
                bioGuideId = bioGuideId, authorityId = authorityId, role = role, state = state)
            members.append(member_info)


        return members

    def parse_hearing(self, content: BeautifulSoup, metadata: BeautifulSoup) -> Dict[str, List[str]]:
        # TODO: add check to see if the hearing is in a good format to parse
        # maybe by looking for a `present:` section

        congress_info = self.grab_congress_info(metadata)


        cleaned_text = self.clean_hearing_text(content.get_text())
        speakers_and_text = re.split(self.regex_pattern, cleaned_text, flags=re.I)
        present_people = re.findall(r'present: (.*?)\.', speakers_and_text[0], flags=re.I | re.DOTALL)
        speaker_groups = self.group_speakers(speakers_and_text)
        return speaker_groups

if __name__ == "__main__":
    with open(f"hearings/CHRG-117shrg47360.html", "r") as file:
        parser = hearing_parser()
        content = BeautifulSoup(file.read(), 'html.parser')
        # speakers_and_text = re.split(contruct_regex(), content.text, flags=re.I)
        parser.parse_hearing(content)
        content.text
