import warnings
import re
from typing import List, Set, Dict
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
            and self.title == other.title
            and self.state == other.state
        )

    def __hash__(self):
        return hash((self.last_name, self.title, self.state))

class LinkSpeakerToCongressMember:
    def __init__(self, all_congress_members: Dict):
        self.all_congress_members = all_congress_members


    def link_speaker_to_all_congress_members(
        self, speaker: SpeakerInfo
    ) -> str:
        # TODO: maybe also indicate off of present section
        # Chair doesn't always mean representative: CHRG-116shrg41431
        rep_titles = ['senator', 'chair']
        # TODO: figure out if hon should be on this list
        # in 'CHRG-117hhrg47768', it should be

        if speaker.state or any(rep_title in speaker.title for rep_title in rep_titles):
            filtered_members = [member for member in self.all_congress_members.values() if member["last_name"].lower() == speaker.last_name]
            old = len(filtered_members)
            if "senator" in speaker.title:
                filtered_members = [member for member in filtered_members if member["chamber"] == "S"]
            if speaker.state:
                filtered_members = [member for member in filtered_members if member["state"] == speaker.state]
            
            new = len(filtered_members)
            if len(filtered_members) == 1:
                return filtered_members[0]["id"]
        
        return None

    def link_speaker_to_present_congress_member(
        self, speaker: SpeakerInfo, congress_info: List[CongressMemberInfo]
    ) -> CongressMemberInfo:
        matches = [x for x in congress_info if speaker.last_name == x.last_name.lower()]
        if len(matches) == 1:
            return matches[0]
        return None

    def link_present_rep_to_all_congress_members(
        self, present_rep: PresentRepresentative) -> str:
        split_name = present_rep.name.lower().split()
        pattern = re.compile('[\W_]+')
        split_name = [re.sub(pattern, '', x) for x in split_name]
        rep_state = present_rep.state.lower()
        filtered_members = []
        for member in self.all_congress_members.values():
            member_name = f'{member["first_name"]} {member["last_name"]}'
            member_state = member["state"]
            split_member_name = member_name.lower().split()
            split_member_last_name = member["last_name"].lower().split()
            if all(word in split_name for word in split_member_last_name) and rep_state == member_state: #TODO: (may not be reliable for franklin 'CHRG-117hhrg47367')
                # Check only last name to avoid issues with nicknames
                filtered_members.append(member)
        if len(filtered_members) == 1:
            return filtered_members[0]["id"]
        if len(filtered_members) > 1:
            # match on the first name as well
            filtered_members = [member for member in filtered_members if all(word in split_name for word in member["first_name"].lower().split())]
            if len(filtered_members) == 1:
                return filtered_members[0]["id"]

        warnings.warn(f"{present_rep.name} has {len(filtered_members)} member matches")
        return None

    def link_speaker_to_present_rep(self, speaker: SpeakerInfo, members_sections: List[List[PresentRepresentative]]) -> PresentRepresentative:
        if not speaker.last_name:
            return None
        split_name = speaker.last_name.split()
        
        members_match = [
            x
            for x in members_sections[-1]
            if all(word in x.name.lower().split() for word in split_name) and 
            (not speaker.state or speaker.state == x.state)
        ]
        if len(members_match) == 1:
            return members_match[0]
        elif len(members_match) > 1:
            # TODO: maybe should look at last names vs first names (scott 'CHRG-117hhrg44799')
            print(
                f"Multiple member matches for {speaker.last_name} in members section"
            )
        return None

    def link_congress_member_to_all_congress_members(self, member: CongressMemberInfo) -> str:
        id_match = next((x for x in self.all_congress_members.values() if x["id"] == member.bio_guide_id), None)
        if id_match:
            return id_match["id"]
        
        # TODO: maybe this is too long of an if an I should use less
        filtered_members = [x for x in self.all_congress_members.values() if x["last_name"] == member.last_name and x["state_initials"] == member.state_initials and x["chamber"] == member.chamber]
        if len(filtered_members) == 1:
            return filtered_members[0]["id"]

        warnings.warn(f"{member.name_parsed} has {len(filtered_members)} member matches")
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

        section_regex = r"\n[\t \r\v]{2,}.*, ?\S*chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"
        old_regex = r"\n[\t \r\v]{2,}.*, ?\S*chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"

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
                        split_columns_lines[i][j] = ""
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
        # TODO: not currently used
        present_sections = re.findall(
            r"present: (.*?)(?:\n\n|    |$)", intro_section, flags=re.I | re.DOTALL
        )
        present_section_people = [
            self.split_present_people_section(present) for present in present_sections
        ]

        return present_section_people

    def identify_chair(
        self,
        speaker_groups: Set[SpeakerInfo],
        members_sections: List[List[PresentRepresentative]],
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
                return self.link_present_rep_to_all_congress_members(chair)
        if speaker_groups:
            chair = next(
                (speaker
                for speaker in speaker_groups
                if "chair" in speaker.title.lower()), None
            )
            if chair:
                return self.link_speaker_to_all_congress_members(chair)
        return chair

    def link_speakers_to_congress_members(
        self,
        speaker_groups: Set[SpeakerInfo],
        intro_section: str,
        congress_info: List[CongressMemberInfo],
        hearing_id: str,
    ) -> Set[SpeakerInfo]:
        self.hearing_id = hearing_id
        members_sections = self.identify_members(intro_section)
        present_section_people = self.identify_people_present(intro_section)
        chair_congress_member_id = self.identify_chair(
            speaker_groups, members_sections
        )

        # This code executes the flow outlined in "./Link Speaker Flow V2.png"
        for speaker in speaker_groups:
            if "the chair" in speaker.full_match:
                if chair_congress_member_id is None:
                    warnings.warn("No chair found, but chair is needed")
                speaker.congress_member_id = chair_congress_member_id
            else:
                speaker.congress_member_id = self.link_speaker_to_all_congress_members(speaker)

            
            if not speaker.congress_member_id and members_sections:
                # TODO: What if last name contained in name 'CHRG-117hhrg46926'
                # or if last name matches someone's first name (scott in 'CHRG-117hhrg44801')
                present_rep = self.link_speaker_to_present_rep(speaker, members_sections)
                if present_rep:
                    speaker.congress_member_id = self.link_present_rep_to_all_congress_members(present_rep)
            if not speaker.congress_member_id and congress_info:
                congress_member = self.link_speaker_to_present_congress_member(speaker, congress_info)
                if congress_member:
                    speaker.congress_member_id = self.link_congress_member_to_all_congress_members(congress_member)
            
            # TODO:
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
