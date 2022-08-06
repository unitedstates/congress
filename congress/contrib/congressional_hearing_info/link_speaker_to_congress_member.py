import warnings
import re
from typing import List, Set
from dataclasses import dataclass, field
from parse_congress_member_info import CongressMemberInfo

@dataclass
class PresentRepresentative:
    name: str
    state: str
    additional_info: List[str]

@dataclass
class SpeakerInfo:
    last_name: str
    full_match: str
    title: str
    state: str
    congress_member_id: str = None
    present_rep: PresentRepresentative = None
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

class LinkSpeakerToCongressMember:
    def __init__(self, congress_info: List[CongressMemberInfo]):
        pass
        # TODO
        # self.congress_info = congress_info
        # run identify funcs


    def link_speaker_info_to_congress_member(
        self, speaker: SpeakerInfo, congress_info: List[CongressMemberInfo]
    ) -> str:
        if not speaker.last_name:
            return None
        matches = [x for x in congress_info if speaker.last_name == x.last_name.lower()]
        if len(matches) == 1:
            return matches[0].authority_id
        return None

    def link_present_rep_to_congress_member(
        self, present_rep: PresentRepresentative, congress_info: List[CongressMemberInfo]) -> str:
        split_name = present_rep.name.lower().split()
        name_matches = [x for x in congress_info if all(word in x.name_parsed.lower().split() for word in split_name)]
        if len(name_matches) == 1:
            return name_matches[0].authority_id

        # TODO: make this better (may not be reliable for franklin 'CHRG-117hhrg47367')
        state_matches = [x for x in congress_info if present_rep.state.lower() in x.state.lower()] # Doesn't work for kansas/arkansas
        new_matches = [x for x in congress_info if present_rep.state.lower() == x.state.lower()]
        # This doesn't work if there is a rep missing from the list
        # if len(state_matches) == 1:
        #     return state_matches[0]
        return None


    def identify_members(
        self, intro_section: str
    ) -> List[List[PresentRepresentative]]:
        # intro_section look for the last string like "JAMES R. LANGEVIN, Rhode Island, Chairman"
        # Note: the lowercase c, a, and es are for Mc, La, and Des
        # TODO: Lowercase names in 'CHRG-117hhrg47805'
        uppercase_name = r"^[A-Zceas\- \.'`]+"
        representative_regex = (
            r"(?P<name>[A-Zceas\- \.'`()]+(?:, ?[SJ][Rr]\.)?), ?(?P<state>.*?)(?:,|$)"
        )

        section_regex = r"\n  +.*, ?\S*chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"

        members_sections = []
        for section in re.findall(section_regex, intro_section, flags=re.I):
            lines = [line.strip() for line in section.split("\n") if line.strip()]

            if len(lines) <= 2 or "chair" not in lines[0].lower():
                warnings.warn(f"Section malformed: {lines}")
                continue

            split_columns_lines = [re.split("  +", line) for line in lines]
            if any(len(line) > 2 for line in split_columns_lines):
                warnings.warn(f"More sections expected")

            # Combine members split across multiple lines
            for i, line in enumerate(split_columns_lines):
                if len(line) > 2:
                    warnings.warn(f"Line malformed: {line}")
                    continue
                for j, title in enumerate(line[:2]):
                    if title.lower() == "vacancy":
                        split_columns_lines[i][j] = None
                    elif "," not in title or not re.match(uppercase_name, title):
                        split_columns_lines[i - 1][j] += f" {title}"
                        split_columns_lines[i][j] = ""

            members = []
            # Note: this for loop and the one above could be combined if the loop went through the entries in reverse
            for i, line in enumerate(split_columns_lines):
                for j, title in enumerate(line):
                    if title is None or title == "":
                        continue
                    title_split = re.split(representative_regex, title)
                    if len(title_split) != 4:
                        if "Staff" not in title:
                            warnings.warn(f"Title does not match regex: {title}")
                    elif title_split[0] != "":
                        if "Staff" not in title:
                            warnings.warn(f"Title split is unexpected: {title_split}")
                    else:
                        members.append(
                            PresentRepresentative(
                                title_split[1], title_split[2], title_split[3].strip()
                            )
                        )

            members_sections.append(members)

        if not members_sections:
            warnings.warn("No members sections found")
            return None
        return members_sections


    def split_present_people_section(self, present_section: str) -> List[str]:
        present_section_one_line = present_section.replace("\n", " ")
        people = re.split(r",\s*", present_section_one_line)
        cleaned_people = [
            re.sub(
                r"representatives |senators |\.|and ", "", person.strip(), flags=re.I
            )
            for person in people
        ]
        return cleaned_people

    def identify_people_present(self, intro_section: str) -> str:
        """
        Identify the people present at a committee hearing.
        """
        present_sections = re.findall(
            r"present: (.*?)(?:\n\n|    |$)", intro_section, flags=re.I | re.DOTALL
        )
        present_section_people = [
            self.split_present_people_section(present) for present in present_sections
        ]

        if not present_section_people:
            warnings.warn("No present section people found")

        return present_section_people

    def union_members_and_present_people(
        self,
        present_section_people: List[str],
        members_section: List[PresentRepresentative],
    ) -> List[PresentRepresentative]:
        # TODO: not currently used
        present_people = []
        for person in present_section_people:
            for member in members_section:
                if person.lower() in member.name.lower():
                    present_people.append(member)
                    continue
        return present_people

    def identify_chair(
        self,
        speaker_groups: Set[SpeakerInfo],
        members_sections: List[List[PresentRepresentative]],
        congress_info: List[CongressMemberInfo],
    ) -> str:
        # TODO: this should return whatever info can be found, not just none if congress info not found
        chair = None
        if members_sections and members_sections[-1]:
            chair = next(
                member
                for member in members_sections[-1]
                if "chair" in member.additional_info.lower()
            )
            if chair:
                return self.link_present_rep_to_congress_member(chair, congress_info)
        if speaker_groups:
            chair = next(
                (speaker
                for speaker in speaker_groups
                if "chair" in speaker.title.lower()), None
            )
            if chair:
                return self.link_speaker_info_to_congress_member(chair, congress_info)
        return chair

    def link_speakers_to_congress_members(
        self,
        speaker_groups: Set[SpeakerInfo],
        intro_section: str,
        congress_info: List[CongressMemberInfo],
    ) -> Set[SpeakerInfo]:
        members_sections = self.identify_members(intro_section)
        present_section_people = self.identify_people_present(intro_section)
        chair_congress_member_id = self.identify_chair(
            speaker_groups, members_sections, congress_info
        )
        intro_lines = intro_section.lower().split("\n")

        for speaker in speaker_groups:
            if "the chair" in speaker.full_match:
                if chair_congress_member_id is None:
                    warnings.warn("No chair found, but chair is needed")
                speaker.congress_member_id = chair_congress_member_id
            # TODO: what if there is a speaker who shares a last name with a representative?
            if not speaker.congress_member_id:
                speaker.congress_member_id = self.link_speaker_info_to_congress_member(speaker, congress_info)

            if not speaker.congress_member_id and members_sections:
                # TODO: What if last name contained in name 'CHRG-117hhrg46926'
                # or if last name matches someone's first name (scott in 'CHRG-117hhrg44801')
                members_match = [
                    x
                    for x in members_sections[-1]
                    if speaker.last_name and speaker.last_name in x.name.lower()
                ]
                if len(members_match) == 1:
                    speaker.present_rep = members_match[0]
                    speaker.congress_member_id = self.link_present_rep_to_congress_member(members_match[0], congress_info)
                elif len(members_match) > 1:
                    # TODO: maybe should look at last names vs first names (scott 'CHRG-117hhrg44799')
                    print(
                        f"Multiple member matches for {speaker.last_name} in members section"
                    )
                else:
                    pass
                    # print(f"No member matches for {speaker.last_name}")
            if not speaker.congress_member_id:
                if (
                    speaker.state
                    or "chair" in speaker.title
                    or "senator" in speaker.title
                ):
                    warnings.warn(f"No match for representative {speaker.last_name}")
                elif (present_section_people and speaker.last_name in present_section_people[0]):
                    warnings.warn(f"No match for representative {speaker.last_name}")
                print(f"No match for {speaker.last_name}")  # scott, 117hhrg47927: johnson, norton, (also present owens), 
