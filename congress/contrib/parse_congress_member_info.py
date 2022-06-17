from bs4 import BeautifulSoup
from typing import List
from dataclasses import dataclass


@dataclass
class CongressMemberInfo:
    last_name: str
    name: str
    name_parsed: str
    bio_guide_id: str
    authority_id: str
    role: str
    state: str
    party: str
    chamber: str
    gpoId: str


class CongressMemberParser:
    def link_speaker_to_representative(self, speaker: str) -> List:
        """
        Given a speaker name or title (ie. chairman), return the name of the representative
        """

        return speaker

    def grab_congress_info(self, metadata: BeautifulSoup) -> List[CongressMemberInfo]:
        congress_sections = metadata.find_all("congMember")
        members = []
        if len(congress_sections) == 0:
            # TODO: not sure how to handle this
            print("No congress info found")
            return []
            # raise Exception('No congress sections found')
        for congress_member in congress_sections:
            try:
                name = congress_member.find("name", {"type": "authority-fnf"}).text
                name_parsed = congress_member.find("name", {"type": "parsed"}).text
                name_lnf = congress_member.find("name", {"type": "authority-lnf"}).text
                last_name = name_lnf.split(",")[0]
            except AttributeError:
                # TODO: not sure how to handle this
                print("One or more name fields are missing")
                continue
            bioGuideId = congress_member.get("bioGuideId")
            authorityId = congress_member["authorityId"]
            role = congress_member["role"]
            state = congress_member["state"]
            party = congress_member["party"]
            chamber = congress_member["chamber"]
            gpoId = congress_member.get("gpoId")

            member_info = CongressMemberInfo(
                name=name,
                name_parsed=name_parsed,
                last_name=last_name,
                bio_guide_id=bioGuideId,
                authority_id=authorityId,
                role=role,
                state=state,
                party=party,
                chamber=chamber,
                gpoId=gpoId,
            )
            members.append(member_info)

        return members
