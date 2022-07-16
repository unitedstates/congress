from bs4 import BeautifulSoup
import re
from typing import Dict, List, Set
from dataclasses import dataclass, field
from parse_congress_member_info import CongressMemberInfo
import warnings


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

@dataclass
class present_representative:
    name: str
    state: str
    additional_info: List[str]


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
        enlongated_title = "(?: of(?P<state> {capital_letter_word})+)?"  # ex: mr. doe of miami
        name_pattern = f"(?P<title>{title_patterns})( {capital_letter_word})+{enlongated_title}"

        one_off_patterns = "|".join(self.ONE_OFF)
        one_off_patterns = f"{one_off_patterns}"

        # TODO what about 2 last names?
        # TODO add one offs
        new_speaker_pattern = f"\n +({name_pattern}|{one_off_patterns})\."

        # Each group included in regex (to be used in group_speakers),
        # plus the full match and inbetween text
        self._num_regex_groups = len(re.findall(r"\((?!\?:).*?\)", new_speaker_pattern)) + 2

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
            text_no_contents = text_no_notes
        elif matches[0].count('\n') > 100:
            warnings.warn("Content section is suspiciously long")
            text_no_contents = text_no_notes
        else:
            text_no_contents = re.sub(contents_pattern, "", text_no_notes)

        return text_no_contents

    def group_speakers(self, speakers_and_text: List[str], present_people) -> Set[SpeakerInfo]:
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

        # TODO
        for speaker in speakers:
            if f" {speaker.last_name}, " in intro_section.lower():
                pass
            else:
                print("no match")

        return speakers

    def parse_hearing(
        self,
        hearing_id: str,
        content: BeautifulSoup,
        congress_info: List[CongressMemberInfo],
    ) -> Dict[str, List[str]]:
        cleaned_text = self.clean_hearing_text(content.get_text())
        speakers_and_text = re.split(self.regex_pattern, cleaned_text)
        present_people = self.identify_people_present(speakers_and_text[0], congress_info)
        speaker_groups = self.group_speakers(speakers_and_text, present_people)
        # chairperson = self.identify_chair(speakers_and_text[0], congress_info, speaker_groups, present_people)
        # self.link_speakers_to_representative(speaker_groups, congress_info, chairperson)
        return speaker_groups

    def split_present_people_section(self, present_section: str) -> List[str]:
        people = re.split(r",\s*", present_section)
        cleaned_people = [re.sub(r"representatives |senators |\.|and ", "", person.strip(), flags=re.I) for person in people]
        return cleaned_people

    def union_members_and_present_people(self, present_section_people: List[str], members_section: List[present_representative]) -> List[present_representative]:
        present_people = []
        for person in present_section_people:
            for member in members_section:
                if person.lower() in member.name.lower():
                    present_people.append(member)
                    continue
        return present_people

    def identify_people_present(self, intro_section: str, congress_info: List[CongressMemberInfo]) -> str:
        """
        Identify the people present at a committee hearing.
        """
        # intro_section look for the last string like "JAMES R. LANGEVIN, Rhode Island, Chairman"
        # Note: the lowercase c, a, and es are for Mc, La, and Des
        # TODO: Lowercase names in 'CHRG-117hhrg47805'
        representative_regex = r"(?P<name>[A-Zceas\- \.'`]+(?:, ?[SJ]r\.)?), ?(?P<state>.*?)(?:,|$)"
        section_regex = r"\n  +.*, ?chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"
    
        members_sections = []
        for section in re.findall(section_regex, intro_section, flags=re.I):
            lines = [line.strip() for line in section.split('\n') if line.strip()]

            if len(lines) <= 2 or 'chair' not in lines[0].lower():
                warnings.warn(f"Section malformed: {lines}")
                continue

            split_columns_lines = [re.split("  +", line) for line in lines]
            if any(len(line) > 2 for line in split_columns_lines):
                warnings.warn(f"More sections expected")

            # Combine members split across multiple lines
            for i, line in enumerate(split_columns_lines):
                for j, title in enumerate(line):
                    if title.lower() == "vacancy":
                        split_columns_lines[i][j] = None
                    elif ',' not in title or not re.match(r"^[A-Zces\- \.'`]+", title):
                        split_columns_lines[i-1][j] += f" {title}"
                        split_columns_lines[i][j] = None
                
            members = []
            # Note: this for loop and the one above could be combined if the loop went through the entries in reverse
            for i, line in enumerate(split_columns_lines):
                for j, title in enumerate(line):
                    if title is None:
                        continue
                    title_split = re.split(representative_regex, title)
                    if len(title_split) != 4:
                        if "Staff" not in title:
                            warnings.warn(f"Title does not match regex: {title}")
                    elif title_split[0] != "":
                        if "Staff" not in title:
                            warnings.warn(f"Title split is unexpected: {title_split}")
                    else:
                        members.append(present_representative(title_split[1], title_split[2], title_split[3].strip()))
                    
            members_sections.append(members)

        present_sections = re.findall(
            r"present: (.*?)(?:\n\n|    |$)", intro_section, flags=re.I | re.DOTALL
        )
        present_section_people = [self.split_present_people_section(present) for present in present_sections]

        if not members_sections:
            warnings.warn("No members sections found")
            return None

        if not present_section_people:
            warnings.warn("No present section people found")
            return members_sections

        members_present = self.union_members_and_present_people(present_section_people[0], members_sections[-1])
        if len(members_present) != len(present_section_people[0]):
            warnings.warn(f"{len(present_section_people[0]) - len(members_present)} present people not found in members section")
        
        # chair_mentions = [line for line in intro_section.splitlines() if "chair" in line.lower()]
        # chairperson = [speaker for speaker in speaker_groups if "chair" in speaker.title]

        return members_present
