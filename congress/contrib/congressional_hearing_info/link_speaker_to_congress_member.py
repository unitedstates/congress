import warnings
import re
from typing import List, Set, Dict
from dataclasses import dataclass, field
from parse_congress_member_info import CongressMemberInfo, STATE_INITIALS_MAP

STATES_LIST = list(map(lambda x: x.lower(), STATE_INITIALS_MAP.values()))

# Right now there is only one rep with the same name as a state
STATES_LIST_WITHOUT_NAMES = [s for s in STATES_LIST if s not in ["Virginia"]]


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

    def link_speaker_to_all_congress_members(self, speaker: SpeakerInfo) -> str:
        if speaker.state or speaker.title == "senator" or "chair" in speaker.title:
            filtered_members = [
                member
                for member in self.all_congress_members.values()
                if member["name"]["last"].lower() == speaker.last_name
            ]
            if "senator" in speaker.title:
                filtered_members = [
                    member
                    for member in filtered_members
                    if member["most_recent_term"]["type"] == "sen"
                ]
            if speaker.state:
                filtered_members = [
                    member
                    for member in filtered_members
                    if member["most_recent_term"]["state"] == speaker.state
                ]

            if len(filtered_members) == 1:
                return filtered_members[0]["id"]["bioguide"]

        return None

    def link_speaker_to_present_congress_member(
        self, speaker: SpeakerInfo, congress_info: List[CongressMemberInfo]
    ) -> CongressMemberInfo:
        matches = [x for x in congress_info if speaker.last_name == x.last_name.lower()]
        if len(matches) == 1:
            return matches[0]
        return None

    def link_present_rep_to_all_congress_members(
        self, present_rep: PresentRepresentative
    ) -> str:
        split_name = present_rep.name.lower().split()
        pattern = re.compile("[\W_]+")
        split_name = [re.sub(pattern, "", x) for x in split_name]
        rep_state = present_rep.state.lower()
        filtered_members = []
        for member in self.all_congress_members.values():
            member_state = member["most_recent_term"]["state"]
            split_member_last_name = member["name"]["last"].lower().split()
            split_member_last_name = [
                re.sub(pattern, "", x) for x in split_member_last_name
            ]
            if (
                all(word in split_name for word in split_member_last_name)
                and rep_state == member_state
            ):
                # Check only last name to avoid issues with nicknames
                filtered_members.append(member)
        if len(filtered_members) == 1:
            return filtered_members[0]["id"]["bioguide"]
        if len(filtered_members) > 1:
            # match on the first name as well if last name isn't enough
            filtered_members = [
                member
                for member in filtered_members
                if all(
                    word in split_name
                    for word in [
                        re.sub(pattern, "", x)
                        for x in member["name"]["first"].lower().split()
                    ]
                )
            ]
            if len(filtered_members) == 1:
                return filtered_members[0]["id"]["bioguide"]

        warnings.warn(f"{present_rep.name} has {len(filtered_members)} member matches")
        return None

    def link_speaker_to_present_rep(
        self, speaker: SpeakerInfo, members_sections: List[List[PresentRepresentative]]
    ) -> PresentRepresentative:
        if not speaker.last_name:
            return None
        split_name = speaker.last_name.split()

        members_match = [
            x
            for x in members_sections[-1]
            if all(word in x.name.lower().split() for word in split_name)
            and (not speaker.state or speaker.state == x.state)
        ]
        if len(members_match) == 1:
            return members_match[0]
        elif len(members_match) > 1:
            members_match = [
                x for x in members_match if x.name.lower().endswith(speaker.last_name)
            ]
            if len(members_match) == 1:
                return members_match[0]
            print(f"Multiple member matches for {speaker.last_name} in members section")
        return None

    def link_congress_member_to_all_congress_members(
        self, member: CongressMemberInfo
    ) -> str:
        id_match = next(
            (
                x["id"]["bioguide"]
                for x in self.all_congress_members.values()
                if x["id"]["bioguide"] == member.bio_guide_id
            ),
            None,
        )
        if id_match:
            return id_match

        filtered_members = [
            x
            for x in self.all_congress_members.values()
            if x["name"]["last"] == member.last_name
            and x["most_recent_term"]["state_initials"] == member.state_initials
            and x["most_recent_term"]["chamber"] == member.chamber
        ]
        if len(filtered_members) == 1:
            return filtered_members[0]["id"]["bioguide"]

        warnings.warn(
            f"{member.name_parsed} has {len(filtered_members)} member matches"
        )
        return None

    def identify_members(self, intro_section: str) -> List[List[PresentRepresentative]]:
        # intro_section look for the last string like "JAMES R. LANGEVIN, Rhode Island, Chairman"
        suffixes_regex = r"(?:, ?[SJ n][Rr]\.)?(?:, ?M\.D\.)?"
        representative_regex = (
            f"(?P<name>[A-z\- \.'`()]+{suffixes_regex}), ?(?P<state>.*?)(?:,|$)"
        )

        section_regex = r"\n[\t \r\v]{2,}.*(?:, ?|\n[\t \r\v]{2,})\S*chair\w* *\n(?:.*\n)?[\s\S]+?(?:\n *\n|--)"
        members_sections = []
        for section in re.findall(section_regex, intro_section, flags=re.I):
            lines = [line.strip() for line in section.split("\n") if line.strip()]

            if len(lines) <= 2 or "chair" not in lines[0].lower():
                print(f"Section malformed: {lines[0]}")

            split_columns_lines = [re.split("(?:  +| *\t+ *)", line) for line in lines]
            if any(len(line) > 2 for line in split_columns_lines):
                print(f"More sections than expected")

            # Combine members split across multiple lines
            for i, line in enumerate(split_columns_lines):
                if len(line) > 2:
                    print(f"Line malformed: {line}")
                    continue
                for j, title in enumerate(line[:2]):
                    if title.lower() == "vacancy":
                        split_columns_lines[i][j] = ""
                    elif (
                        "," not in title
                        or title.split(",")[0].lower() in STATES_LIST_WITHOUT_NAMES
                    ):
                        try:
                            split_columns_lines[i - 1][j] += f" {title}"
                        except IndexError as e:
                            print(f"Index error for {split_columns_lines[i]}")
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
                            print(f"Title does not match regex: {title}")
                    elif title_split[0] != "":
                        if "Staff" not in title:
                            print(f"Title split is unexpected: {title_split}")
                    else:
                        if title_split[2].lower() not in STATES_LIST:
                            state_section = title_split[2].split()
                            for i in range(1, len(state_section)):
                                if " ".join(state_section[0:i]).lower() in STATES_LIST:
                                    title_split[2] = " ".join(state_section[0:i])
                                    title_split[3] = " ".join(state_section[2:])

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
        Identify the people present at a committee hearing. Some hearings
        make this easy by creating a section which starts with "present:".
        This check is just for warnings and doesn't affect speaker output.
        """
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
        if members_sections and members_sections[-1]:
            chair = next(
                (
                    member
                    for member in members_sections[-1]
                    if "chair" in member.additional_info.lower()
                    or "chair" in member.state
                ),
                None,
            )
            if chair:
                chair_id = self.link_present_rep_to_all_congress_members(chair)
                if chair_id:
                    return chair_id
        if speaker_groups:
            chair = next(
                (
                    speaker
                    for speaker in speaker_groups
                    if "chair" in speaker.title.lower()
                ),
                None,
            )
            if chair:
                return self.link_speaker_to_all_congress_members(chair)
        return None

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
        chair_congress_member_id = self.identify_chair(speaker_groups, members_sections)

        # This code executes the flow outlined in "link_speaker_flow_v2.png"
        for speaker in speaker_groups:
            if "the chair" in speaker.full_match:
                if chair_congress_member_id is None:
                    warnings.warn("No chair found, but chair is needed")
                speaker.congress_member_id = chair_congress_member_id
            else:
                speaker.congress_member_id = self.link_speaker_to_all_congress_members(
                    speaker
                )

            if not speaker.congress_member_id and members_sections:
                present_rep = self.link_speaker_to_present_rep(
                    speaker, members_sections
                )
                if present_rep:
                    speaker.present_rep = present_rep
                    speaker.congress_member_id = (
                        self.link_present_rep_to_all_congress_members(present_rep)
                    )
            if not speaker.congress_member_id and congress_info:
                congress_member = self.link_speaker_to_present_congress_member(
                    speaker, congress_info
                )
                if congress_member:
                    speaker.congress_member_id = (
                        self.link_congress_member_to_all_congress_members(
                            congress_member
                        )
                    )
