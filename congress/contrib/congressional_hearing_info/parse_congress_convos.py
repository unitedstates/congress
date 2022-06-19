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
            and self.full_match == other.full_match
            and self.title == other.title
            and self.state == other.state
        )

    def __hash__(self):
        return hash((self.last_name, self.full_match, self.title, self.state))


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
        title_patterns = f"\n\s+((?P<title>{title_patterns}) (\w+){enlongated_title}\.)"
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
        additional_notes_pattern = r"\n*\[.*?\]"
        # text_to_be_removed = re.findall(additional_notes_pattern, text)
        cleaned_text = re.sub(additional_notes_pattern, "\n", text)
        return cleaned_text

    def group_speakers(self, speakers_and_text: List[str]) -> Set[SpeakerInfo]:
        speakers = set()

        for speaker_group in [
            speakers_and_text[x : x + self._num_regex_groups]
            for x in range(1, len(speakers_and_text), self._num_regex_groups)
        ]:
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

        return speakers

    def parse_hearing(
        self,
        hearing_id: str,
        content: BeautifulSoup,
        congress_info: List[CongressMemberInfo],
    ) -> Dict[str, List[str]]:
        # TODO: add check to see if the hearing is in a good format to parse
        # maybe by looking for a `present:` section

        cleaned_text = self.clean_hearing_text(content.get_text())
        speakers_and_text = re.split(self.regex_pattern, cleaned_text, flags=re.I)
        present_people = re.findall(
            r"present: (.*?)\n    ", speakers_and_text[0], flags=re.I | re.DOTALL
        )
        speaker_groups = self.group_speakers(speakers_and_text)
        chairperson = self.identify_chair(speakers_and_text[0], congress_info, speaker_groups, present_people)
        self.link_speaker_to_representative(speaker_groups, congress_info, chairperson)
        return speaker_groups

    def identify_chair(self, intro_section: str, congress_info: List[CongressMemberInfo], speaker_groups: Set[SpeakerInfo], present_people: List[str]) -> str:
        """
        Given a string, identify the chairperson of the hearing.
        """

        chair_mentions = [line for line in intro_section.splitlines() if "chair" in line.lower()]
        chairperson = [speaker for speaker in speaker_groups if "chair" in speaker.title]
        
        return congress_info[0]

    def link_speaker_to_representative(
        self, speaker: SpeakerInfo, congress_info: List[CongressMemberInfo], chairperson: CongressMemberInfo
    ) -> List:
        """
        Given a speaker name or title (ie. chairman), return the name of the representative
        """

        return speaker


if __name__ == "__main__":
    with open(f"hearings/CHRG-117hhrg47278.html", "r") as file:
        parser = hearing_parser()
        content = BeautifulSoup(file.read(), "html.parser")
        # speakers_and_text = re.split(contruct_regex(), content.text, flags=re.I)
        parser.parse_hearing('CHRG-117hhrg47278', content, [])
        content.text
