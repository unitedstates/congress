from bs4 import BeautifulSoup
from typing import List
from dataclasses import dataclass
import requests
import os
from dotenv import load_dotenv


@dataclass
class CongressMemberInfo:
    last_name: str
    name: str
    name_parsed: str
    bio_guide_id: str
    authority_id: str
    role: str
    state_initials: str
    state: str
    party: str
    chamber: str
    gpoId: str


STATE_INITIALS_MAP = {
    "AK": "Alaska",
    "AL": "Alabama",
    "AR": "Arkansas",
    "AS": "American Samoa",
    "AZ": "Arizona",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DC": "District of Columbia",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "GU": "Guam",
    "HI": "Hawaii",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "MA": "Massachusetts",
    "MD": "Maryland",
    "ME": "Maine",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MO": "Missouri",
    "MP": "Northern Mariana Islands",
    "MS": "Mississippi",
    "MT": "Montana",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "NE": "Nebraska",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NV": "Nevada",
    "NY": "New York",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "PR": "Puerto Rico",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "TT": "Trust Territories",
    "UT": "Utah",
    "VA": "Virginia",
    "VI": "Virgin Islands",
    "VT": "Vermont",
    "WA": "Washington",
    "WI": "Wisconsin",
    "WV": "West Virginia",
    "WY": "Wyoming",
}


class CongressMemberParser:
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
            state_initials = congress_member["state"]
            state = STATE_INITIALS_MAP[state_initials.upper()].lower()
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
                state_initials=state_initials,
                state=state,
                party=party,
                chamber=chamber,
                gpoId=gpoId,
            )
            members.append(member_info)

        return members
