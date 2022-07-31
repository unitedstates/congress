import requests
import urllib.parse
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from typing import Dict, List, Set
from parse_congress_convos import hearing_parser
from link_speaker_to_congress_member import SpeakerInfo
from parse_congress_member_info import CongressMemberParser, CongressMemberInfo

class CongressionalHearingsInfo:
    HEARING_COLLECTION_CODE = "CHRG"
    
    def __init__(self, size: int, api_key: str, last_date: datetime = datetime(year=2022, month=1, day=1)):
        last_date_str = last_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"https://api.govinfo.gov/collections/{self.HEARING_COLLECTION_CODE}/{last_date_str}"

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
        self.package_fields = {
            "api_key": api_key,
            "offset": 0,
            "pageSize": 20,
        }
        self.parser = hearing_parser()
        self.congress_member_parser = CongressMemberParser()

        self.gather_all_hearings_texts(collections)

    def gather_all_hearings_texts(self, collections: Dict):
        all_speakers = {}
        all_congress_members = {}
        for collection in collections["packages"]:
            hearing_id = collection['packageId']
            url = f"https://api.govinfo.gov/packages/{hearing_id}"
            congress_info = self.gather_hearing_info(url, hearing_id)
            for member in congress_info:
                id = member.authority_id
                if not id:
                    raise ValueError("No id found for congress member")
                # TODO: what if there is additional info on an existing memeber?
                if id not in all_congress_members.keys():
                    all_congress_members[id] = member
            
            speakers = self.gather_hearing_text(url, hearing_id, congress_info)
            # TODO: add speakers to all speakers
            # for name, words in speakers.items():
            #     cur_words = all_speakers.get(name, {})
            #     cur_words[hearing_id] = words
            #     all_speakers[name] = cur_words

        # TODO: after the whole script has run, you can go back and try and attribute speakers to
        # any of the all_congress_members
        print(f"total len: {len(all_speakers)}")

    def gather_hearing_info(self, url: str, hearing_id: str) -> List[CongressMemberInfo]:
        mods = requests.get(url + "/mods", params=self.package_fields)
        mods_soup = BeautifulSoup(mods.content, "xml")
        congress_info = self.congress_member_parser.grab_congress_info(mods_soup)
        return congress_info

    def gather_hearing_text(self, url: str, hearing_id: str, congress_info: List[CongressMemberInfo]):
        htm = requests.get(url + "/htm", params=self.package_fields)
        htm_soup = BeautifulSoup(htm.content, "html.parser")

        gran = requests.get(
            f"{url}/granules/{hearing_id}/summary", params=self.package_fields
        )
        members = gran.json().get("members", [])

        speakers = self.parser.parse_hearing(hearing_id, htm_soup, congress_info)
        print(len(speakers))
        return speakers


# TODO: search: gun control, topics clarence thomas

if __name__ == "__main__":
    load_dotenv()

    api_key = os.getenv("GOV_INFO_API_KEY")
    if api_key is None:
        api_key = "DEMO_KEY"

    CongressionalHearingsInfo(200, api_key)
