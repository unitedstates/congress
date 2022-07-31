from bs4 import BeautifulSoup
import re
from typing import Dict, List, Set
from parse_congress_member_info import CongressMemberInfo
from link_speaker_to_congress_member import LinkSpeakerToCongressMember, SpeakerInfo
import warnings


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
        r"Chair\w*",
        r"Mr.",
        r"Ms.",
        r"Mrs.",
        r"Miss",
        r"Dr.",
        r"Senator",
        r"General",
        r"Hon.",
    ]

    ONE_OFF = ["The [C|c]hair\w*"]

    def construct_regex(self):
        title_patterns = "|".join(self.TITLE_PATTERNS)
        capital_letter_word = "[A-Z][A-z_\-']*"
        enlongated_title = (
            "(?: of(?P<state> {capital_letter_word})+)?"  # ex: mr. doe of miami
        )
        name_pattern = f"(?P<title>{title_patterns})(?P<l_name>(?: {capital_letter_word})+){enlongated_title}"

        one_off_patterns = "|".join(self.ONE_OFF)
        one_off_patterns = f"{one_off_patterns}"

        # TODO what about 2 last names?
        # TODO add one offs
        new_speaker_pattern = f"\n +({name_pattern}|{one_off_patterns})\."

        # Each group included in regex (to be used in group_speakers),
        # plus the full match and inbetween text
        self._num_regex_groups = (
            len(re.findall(r"\((?!\?:).*?\)", new_speaker_pattern)) + 2
        )

        return new_speaker_pattern

    def __init__(self):
        self.regex_pattern = self.construct_regex()

    def clean_hearing_text(self, text: str) -> str:
        additional_notes_pattern = r" ?\[.*?\]"
        # text_to_be_removed = re.findall(additional_notes_pattern, text)
        text_no_notes = re.sub(additional_notes_pattern, "", text)

        contents_pattern = r"C *O *N *T *E *N *T *S[\s\S]*?---+[\s\S]*?---+"

        matches = re.findall(contents_pattern, text_no_notes)

        if len(matches) > 1:
            warnings.warn("More than one contents section found")

        if not matches:
            warnings.warn("No contents found")
            return text_no_notes
        
        new_line_count = matches[0].count("\n")
        if new_line_count > 100:
            warnings.warn(f"Content section is suspiciously long, {new_line_count} lines")
            text_no_contents = text_no_notes
        else:
            text_no_contents = re.sub(contents_pattern, "", text_no_notes)

        return text_no_contents

    def group_speakers(self, speakers_and_text: List[str]) -> Set[SpeakerInfo]:
        speakers = set()
        intro_section = speakers_and_text[0]

        sections_of_text = [
            speakers_and_text[x : x + self._num_regex_groups]
            for x in range(1, len(speakers_and_text), self._num_regex_groups)
        ]
        if len(sections_of_text) < 2:
            warnings.warn("probably a bad batch")
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

            # TODO: improve with stack overflow solution
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
        # TODO: check for repeated congress info 'CHRG-117hhrg45195'
        cleaned_text = self.clean_hearing_text(content.get_text())
        speakers_and_text = re.split(self.regex_pattern, cleaned_text)
        speaker_groups = self.group_speakers(speakers_and_text)

        link = LinkSpeakerToCongressMember(congress_info)
        link.link_speakers_to_congress_members(
            speaker_groups, speakers_and_text[0], congress_info
        )

        return speaker_groups

