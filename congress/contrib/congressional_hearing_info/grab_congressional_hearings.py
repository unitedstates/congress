# TODO: maybe use the util's download command
import requests
import urllib.parse
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from typing import Dict, List, Set
from parse_congress_convos import hearing_parser, SpeakerInfo
from parse_congress_member_info import CongressMemberParser, CongressMemberInfo

load_dotenv()

# safe_string = urllib.parse.quote_plus()

api_key = os.getenv("GOV_INFO_API_KEY")
if api_key is None:
    api_key = "DEMO_KEY"

collection = "CHRG"

last_date = datetime(year=2022, month=1, day=1).strftime("%Y-%m-%dT%H:%M:%SZ")

url = f"https://api.govinfo.gov/collections/{collection}/{last_date}"

collection_fields = {
    "api_key": api_key,
    "offset": 0,
    "pageSize": 50,
}

r = requests.get(url, params=collection_fields)
if r.status_code != 200:
    print("Error:", r.status_code)
    exit(1)
collections = r.json()
package_fields = {
    "api_key": api_key,
    "offset": 0,
    "pageSize": 50,
}
parser = hearing_parser()
congress_member_parser = CongressMemberParser()


def link_speakers_to_representative(
    speakers: Set[SpeakerInfo], congress_info: List[CongressMemberInfo]
):
    """
    Given a set of speakers, link them to their representative.
    """
    print(set([speaker.title for speaker in speakers]))
    for speaker in speakers:
        narrowed_congress_info = congress_info

        # Filter by state
        if speaker.state:
            narrowed_congress_info = [i for i in narrowed_congress_info if i.state == speaker.state or i.state_initials == speaker.state]
            if len(narrowed_congress_info) == 0:
                raise ValueError(f"Could not find representative for state {speaker.state}")
        
        # Filter by name
        narrowed_congress_info = [i for i in narrowed_congress_info if i.last_name.lower() == speaker.last_name.lower()]

        # TODO: what if a witness is named the same as a congress member?
        # TODO: or if two congress members have the same name?
        if len(narrowed_congress_info) == 1:
            speaker.congress_member_info = narrowed_congress_info[0]
        elif speaker.title == "senator" or "chair" in speaker.title:
            raise ValueError(f"Could not find representative for speaker {speaker.last_name}")
    

all_speakers = {}
all_congress_members = {}
for collection in collections["packages"]:
    # TODO: maybe verify that htm is a format which exists for this package
    url = f"https://api.govinfo.gov/packages/{collection['packageId']}"

    htm = requests.get(url + "/htm", params=package_fields)
    htm_soup = BeautifulSoup(htm.content, "html.parser")

    mods = requests.get(url + "/mods", params=package_fields)
    mods_soup = BeautifulSoup(mods.content, "xml")
    congress_info = congress_member_parser.grab_congress_info(mods_soup)
    for member in congress_info:
        all_congress_members[member.bio_guide_id] = member

    gran = requests.get(f"{url}/granules/{collection['packageId']}/summary", params=package_fields)
    # members = gran.json()["granules"]["members"]
    members = gran.json().get('members', [])
    
    # TODO: where are the witnesses? they are in the detailsLink
    # gran_0 = gran.json()['granules'][0]
    # gran_id = gran_0['granuleId']

    speakers = parser.parse_hearing(collection["packageId"], htm_soup, congress_info)
    print(len(speakers))
    # for name, words in speakers.items():
    #     cur_words = all_speakers.get(name, {})
    #     cur_words[collection['packageId']] = words
    #     all_speakers[name] = cur_words

link_speakers_to_representative(all_speakers, list(all_congress_members.values()))
print(f"total len: {len(all_speakers)}")
# [speaker for speaker, hearing in all_speakers.items() if len(hearing.keys())>1]
