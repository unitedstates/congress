from bs4 import BeautifulSoup
import re
from typing import Dict, List, Set
from dataclasses import dataclass, field
from parse_congress_member_info import CongressMemberInfo


@dataclass
class SpeakerInfo:
    last_name: str
    full_match: str
    title: str
    state: str
    congress_member_info: CongressMemberInfo = None
    statements: List[str] = field(default_factory=list)

    def __eq__(self, other):
        return (
            self.last_name == other.last_name
            # and self.full_match == other.full_match
            and self.title == other.title
            and self.state == other.state
        )

    def __hash__(self):
        return hash((self.last_name, self.title, self.state))


class hearing_parser:
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
        "chairwoman",
        "chairman",
        "mr.",
        "ms.",
        "mrs.",
        "miss",
        "dr.",
        "senator",
        "general",
        "hon.",
    ]

    ONE_OFF = ["the chairwoman", "the chairman"]

    def construct_regex(self):
        pattern = ""
        title_patterns = "|".join(self.TITLE_PATTERNS)
        enlongated_title = "(?: of (?P<state>\w+))?"  # ex: mr. doe of miami
        title_patterns = f"\n +((?P<title>{title_patterns}) (\w+){enlongated_title} ?\.)"
        # TODO what about 2 last names?
        # TODO add one offs
        pattern = title_patterns

        # Each group included in regex (to be used in group_speakers),
        # plus the full match and inbetween text
        self._num_regex_groups = len(re.findall(r"\((?!\?:).*?\)", pattern)) + 2

        return pattern

    def __init__(self):
        self.regex_pattern = self.construct_regex()

    def clean_hearing_text(self, text: str) -> str:
        additional_notes_pattern = r"\[.*?\]"
        # text_to_be_removed = re.findall(additional_notes_pattern, text)
        cleaned_text = re.sub(additional_notes_pattern, "", text)
        return cleaned_text

    def group_speakers(self, speakers_and_text: List[str], present_people) -> Set[SpeakerInfo]:
        speakers = set()
        intro_section = speakers_and_text[0]

        sections_of_text = [
            speakers_and_text[x : x + self._num_regex_groups]
            for x in range(1, len(speakers_and_text), self._num_regex_groups)
        ]
        if len(sections_of_text) < 2:
            print("probably a bad batch")
            return set()
        for speaker_group in sections_of_text:
            speaker_group = [x.lower().strip() if x else x for x in speaker_group]
            match, title, l_name, state, statement = speaker_group
            new_speaker = SpeakerInfo(
                last_name=l_name,
                full_match=match,
                title=title,
                state=state,
                statements=[statement],
            )

            match = next((x for x in speakers if x == new_speaker), None)
            if match:
                match.statements.append(statement)
            else:
                speakers.add(new_speaker)

        for speaker in speakers:
            if f" {speaker.last_name}, ".upper() in intro_section:
                print("match")
            else:
                print("no match")

            if not present_people:
                if speaker.last_name in '\n'.join(present_people).lower():
                    print('present match')
                else:
                    print('present no match')
                

        return speakers

    def parse_hearing(
        self,
        hearing_id: str,
        content: BeautifulSoup,
        congress_info: List[CongressMemberInfo],
    ) -> Dict[str, List[str]]:
        # TODO: add check to see if the hearing is in a good format to parse

        cleaned_text = self.clean_hearing_text(content.get_text())
        speakers_and_text = re.split(self.regex_pattern, cleaned_text, flags=re.I)
        present_people = re.findall(
            r"present: (.*?)\n    ", speakers_and_text[0], flags=re.I | re.DOTALL
        )
        speaker_groups = self.group_speakers(speakers_and_text, present_people)
        # chairperson = self.identify_chair(speakers_and_text[0], congress_info, speaker_groups, present_people)
        # self.link_speakers_to_representative(speaker_groups, congress_info, chairperson)
        return speaker_groups

    def identify_chair(self, intro_section: str, congress_info: List[CongressMemberInfo], speaker_groups: Set[SpeakerInfo], present_people: List[str]) -> str:
        """
        Given a string, identify the chairperson of the hearing.
        """
        # TODO: finish this
        # intro_section look for the last string like "JAMES R. LANGEVIN, Rhode Island, Chairman"
        # Still WIP "([A-Z \.]+,.*?, Chair\w*)|(?:\n\n)|(?: +-+ +)"

        chair_mentions = [line for line in intro_section.splitlines() if "chair" in line.lower()]
        chairperson = [speaker for speaker in speaker_groups if "chair" in speaker.title]

        return congress_info[0]
 



if __name__ == "__main__":
    with open(f"hearings/CHRG-117hhrg47278.html", "r") as file:
        parser = hearing_parser()
        content = BeautifulSoup(file.read(), "html.parser")
        # speakers_and_text = re.split(contruct_regex(), content.text, flags=re.I)
        parser.parse_hearing('CHRG-117hhrg47278', content, [])
        content.text
