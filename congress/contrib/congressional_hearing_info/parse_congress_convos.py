from bs4 import BeautifulSoup
import re
from typing import Dict, List, Set, Tuple
from parse_congress_member_info import CongressMemberInfo
from link_speaker_to_congress_member import LinkSpeakerToCongressMember, SpeakerInfo
import warnings
import requests
from parse_congress_member_info import CongressMemberParser, CongressMemberInfo


class hearing_parser:
    """
    Used to split text of US Gov hearing in to blocks, link each block
    to a speaker, and finally link the speaker to a member of congress
    (if applicable).
    ...
    Attributes
    ----------
    regex_pattern : str
        a very complex regex pattern which takes into account all
        known ways transcriptors introduce new speakers.

    Public Methods
    -------
    parse_hearing(content: BeautifulSoup)
        parses the text of a hearing and returns a set of
        speakers with data on who they are and what they said.
    """

    TITLE_PATTERNS = [
        r"(?:Co-)?[Cc]hair\w*",
        r"Mr.",
        r"Ms.",
        r"Mrs.",
        r"Miss",
        r"Dr.",
        r"Senator",
        r"Hon.",
        r"Secretary",
        r"Sec.",

        r"General",
        r"Colonel",
        r"Admiral",
        r"Major",
        r"Captain",
        r"Commodore",
        r"Lieutenant",
        r"Corporal",
    ]

    ONE_OFF = ["The (?:[C|c]o-)?[C|c]hair\w*\.","\w* ?S(?:TATEMENT|tatement) (?:OF|of) (?:(?P<name>.*?),)?(?:.|\n)*?\n+(?=\n)"]

    def construct_regex(self):
        title_patterns = "|".join(self.TITLE_PATTERNS)
        capital_letter_word = "[A-Z][A-z_\-']*"
        enlongated_title = (
            f"(?: of(?P<state> {capital_letter_word})+)?"  # ex: Mr. Doe of Miami
        )
        name_pattern = f"(?P<title>{title_patterns})(?P<l_name>(?: {capital_letter_word})+){enlongated_title}\."

        one_off_patterns = "|".join(self.ONE_OFF)
        one_off_patterns = f"{one_off_patterns}"

        speaker_pattern = f"\n\s+({name_pattern}|{one_off_patterns})"

        # Each group included in regex (to be used in group_speakers),
        # plus the full match and inbetween text
        self._num_regex_groups = len(re.findall(r"\((?!\?:).*?\)", speaker_pattern)) + 2

        return speaker_pattern

    def __init__(self, all_congress_members: Dict, package_fields: Dict):
        self.regex_pattern = self.construct_regex()
        self.congress_member_parser = CongressMemberParser()
        self.link = LinkSpeakerToCongressMember(all_congress_members)
        self.package_fields = package_fields

    def clean_hearing_text(self, text: str) -> str:
        additional_notes_pattern = r" ?\[.*?\]"
        text_no_notes = re.sub(additional_notes_pattern, "", text)

        contents_pattern = r"C *O *N *T *E *N *T *S(?:[\s\S]{0,1500}?\.\.+ *\d+)+"

        matches = re.findall(contents_pattern, text_no_notes)

        if len(matches) > 1:
            warnings.warn("More than one contents section found")

        if not matches:
            warnings.warn("No contents found")
            return text_no_notes

        new_line_count = matches[0].count("\n")
        if new_line_count > 150:
            warnings.warn(
                f"Content section is suspiciously long, {new_line_count} lines"
            )
            text_no_contents = text_no_notes
        else:
            text_no_contents = re.sub(contents_pattern, "", text_no_notes)

        return text_no_contents

    def group_speakers(self, speakers_and_text: List[str]) -> List[SpeakerInfo]:
        speakers = {}

        sections_of_text = [
            speakers_and_text[x : x + self._num_regex_groups]
            for x in range(1, len(speakers_and_text), self._num_regex_groups)
        ]
        if len(sections_of_text) < 2:
            warnings.warn("probably a bad batch")
            return []
        for speaker_group in sections_of_text:
            speaker_group = [x.lower().strip() if x else x for x in speaker_group]
            match, title, l_name, state, statement_name, statement = speaker_group
            key = SpeakerInfo(
                last_name=l_name or "",
                full_match=match,
                title=title or "",
                state=state,
                statement_name=statement_name,
                statements=[],
            )

            speaker = speakers.setdefault(key, key)
            speaker.statements.append(statement)
        return list(speakers.values())

    def gather_hearing_info(
        self, url: str, hearing_id: str
    ) -> Tuple[List[CongressMemberInfo], Dict]:
        mods = requests.get(url + "/mods", params=self.package_fields)
        mods_soup = BeautifulSoup(mods.content, "xml")
        congress_info = self.congress_member_parser.grab_congress_info(mods_soup)

        summary = requests.get(url + "/summary", params=self.package_fields).json()
        relevant_keys = [
            "dateIssued",
            "documentType",
            "congress",
            "heldDates",
            "session",
            "title",
            "branch",
            "pages",
            "governmentAuthor2",
            "chamber",
            "governmentAuthor1",
            "publisher",
            "suDocClassNumber",
            "lastModified",
            "category",
            "otherIdentifier",
        ]
        sum_filtered = {k: v for k, v in summary.items() if k in relevant_keys}

        return congress_info, sum_filtered

    def parse_hearing(
        self,
        hearing_id: str,
        content: BeautifulSoup,
        url: str,
    ) -> Tuple[List[SpeakerInfo], Dict]:
        print(f"Parsing hearing: {hearing_id}")
        cleaned_text = self.clean_hearing_text(content.get_text())
        # TODO split on section titles like "[Prepared] Statement of ..."
        speakers_and_text = re.split(self.regex_pattern, cleaned_text)
        # TODO: Returned text should not have case modified
        speaker_groups = self.group_speakers(speakers_and_text)
        congress_info, summary = self.gather_hearing_info(url, hearing_id)
        self.link.link_speakers_to_congress_members(
            speaker_groups, speakers_and_text[0], congress_info, hearing_id
        )

        return speaker_groups, summary
