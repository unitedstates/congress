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
        title_patterns = "|".join(self.TITLE_PATTERNS)
        enlongated_title = "(?: of (?P<state>\w+))?"  # ex: mr. doe of miami
        title_patterns = f"(?P<title>{title_patterns}) (\w+){enlongated_title}"

        one_off_patterns = "|".join(self.ONE_OFF)
        one_off_patterns = f"{one_off_patterns}"

        # TODO what about 2 last names?
        # TODO add one offs
        new_speaker_pattern = f"\n +({title_patterns}|{one_off_patterns})\."

        # Each group included in regex (to be used in group_speakers),
        # plus the full match and inbetween text
        self._num_regex_groups = len(re.findall(r"\((?!\?:).*?\)", new_speaker_pattern)) + 2

        return new_speaker_pattern

    def __init__(self):
        self.regex_pattern = self.construct_regex()

    def clean_hearing_text(self, text: str) -> str:
        additional_notes_pattern = r" ?\[.*?\]"
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
        Given a string, identify the chairperson of the hearing.
        """
        # intro_section look for the last string like "JAMES R. LANGEVIN, Rhode Island, Chairman"
        # Note: the lowercase c, a, and e are for Mc, La, and Des
        # TODO: regex for names continuing on the next line
        # representative_regex = r"((?P<name>[A-Zces\- \.'`]+)(?:, ?[SJ]r\.)?, ?(?P<state>\w+ ?\w*)(?:  |\n|,|  ?\())"
        representative_regex = r"(?P<name>[A-Zceas\- \.'`]+(?:, ?[SJ]r\.)?), ?(?P<state>.*),? *(.*)"
        chair_regex = r"((?P<name>[A-Zces\- \.'`]+)(?:, ?[SJ]r\.)?, ?(?P<state>\w+ ?\w*),\s*Chair\w*)"
        # section_regex = r"(?:sub)?committee on .*\n\n?.*, ?chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"
        section_regex = r"\n  +.*, ?chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"

        # Confirm that there is an equal number of member sections
        # to committee sections
        committee_count = 0
    
        members_sections = []
        for section in re.findall(section_regex, intro_section, flags=re.I):
            lines = [line.strip() for line in section.split('\n') if line.strip()]

            # Confirm section is correct
            # if len(lines) <= 2 or 'committee' not in lines[0].lower() or 'chair' not in lines[1].lower():
            if len(lines) <= 2 or 'chair' not in lines[0].lower():
                warnings.warn(f"Section malformed: {lines}")
                continue
            # if len(lines) <= 2 or 'committee' not in lines[0].lower() or 'chair' not in lines[1].lower():
            #     warnings.warn(f"Section malformed: {lines}")
            #     continue

            split_columns_lines = [re.split("  +", line) for line in lines[1:]]
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
                    if len(title_split) != 5:
                        warnings.warn(f"Title does not match regex: {title}")
                    elif not title_split[0] == "" and title_split[4] == "":
                        warnings.warn(f"Title split is unexpected: {title_split}")
                    else:
                        members.append(present_representative(title_split[0], title_split[1], title_split[2:]))
                    
            members_sections.append(members)



        # for section in re.split(section_regex, intro_section, flags=re.I):
        #     if re.findall(r"  +(?:sub)?committee on", section, flags=re.I):
        #         committee_count += 1
            
        #     # Check if this is a members section
        #     chair_match = re.findall(chair_regex, section)
        #     if chair_match:
        #         if len(chair_match) > 1:
        #             warnings.warn("More than one chairperson found")
        #         chair_name = chair_match[0][1].strip()

        #         representatives_raw = re.findall(representative_regex, section)
        #         members = []
        #         for rep in representatives_raw:
        #             name = rep[1].strip()
        #             chair = True if name == chair_name else False
        #             state = rep[2].strip()
        #             if name == chair_name:
        #                 continue
        #             members.append(present_representative(name, state, chair))
        #         members_sections.append(members)

        # if committee_count != len(members_sections):
        #     warnings.warn(f"{committee_count} committee sections found, but {len(members_sections)} present members sections found")


        present_sections = re.findall(
            r"present: (.*?)\n(?:\n|    )", intro_section, flags=re.I | re.DOTALL
        )
        present_section_people = [self.split_present_people_section(present) for present in present_sections]

        if not members_sections:
            warnings.warn("No members sections found")
            return None

        if not present_section_people:
            warnings.warn("No present section people found")
            return members_sections

        # TODO: union the present sections with members_sections and if the len is less than present warn
        members_present = self.union_members_and_present_people(present_section_people[0], members_sections[-1])
        if len(members_present) != len(present_section_people[0]):
            warnings.warn(f"{len(present_section_people[0]) - len(members_present)} present people not found in members section")
        # members_names = [member.name.lower() for member in members_sections[0]]
        # for present_section in present_section_people:
        #     for present_person in present_section:
        #         match = [name for name in members_names if present_person.lower() in name]
        #         if not match:
        #             warnings.warn(f"{present_person} not found in members section")

        chair_mentions = [line for line in intro_section.splitlines() if "chair" in line.lower()]
        # chairperson = [speaker for speaker in speaker_groups if "chair" in speaker.title]

        return members_present
 



if __name__ == "__main__":
    with open(f"hearings/CHRG-117hhrg47278.html", "r") as file:
        parser = hearing_parser()
        content = BeautifulSoup(file.read(), "html.parser")
        # speakers_and_text = re.split(contruct_regex(), content.text, flags=re.I)
        parser.parse_hearing('CHRG-117hhrg47278', content, [])
        content.text
