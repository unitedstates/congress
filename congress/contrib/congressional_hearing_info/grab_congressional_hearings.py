import requests
import urllib.parse
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from typing import Dict, List
from link_speaker_to_congress_member import SpeakerInfo
from parse_congress_convos import hearing_parser
from parse_congress_member_info import CongressMemberParser, CongressMemberInfo
from dataclasses import asdict, fields
import pandas as pd
import pyarrow

class CongressionalHearingsInfo:
    HEARING_COLLECTION_CODE = "CHRG"
    
    def __init__(self, size: int, api_key: str, last_date: datetime = datetime(year=2022, month=1, day=1)):
        last_date_str = last_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"https://api.govinfo.gov/collections/{self.HEARING_COLLECTION_CODE}/{last_date_str}"

        collection_fields = {
            "api_key": api_key,
            "offset": 0,
            "pageSize": size,
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

        speakers_df, statements_df, congress_members_df = self.gather_all_hearings_texts(collections)
        speakers_df.to_pickle("speakers.pkl")
        statements_df.to_pickle("statements.pkl")
        congress_members_df.to_pickle("congress_members.pkl")


    def gather_all_hearings_texts(self, collections: Dict):
        speakers_df = pd.DataFrame(columns=["hearing_id", "id"]+[field.name for field in fields(SpeakerInfo) if field.name != "statements"])
        speakers_df.set_index(["hearing_id", "id"], inplace=True)

        all_statements = []
        # statements_df = pd.DataFrame(columns=["hearing_id", "speaker_id", "statement"])
        congress_members_df = pd.DataFrame(columns=[field.name for field in fields(CongressMemberInfo)])
        len_all_speakers = 0
        for collection in collections["packages"]:
            hearing_id = collection['packageId']
            url = f"https://api.govinfo.gov/packages/{hearing_id}"
            congress_info = self.gather_hearing_info(url, hearing_id)
            for member in congress_info:
                id = member.authority_id
                if not id:
                    raise ValueError("No id found for congress member")
                
                # TODO: what if there is additional info on an existing memeber?
                # Only set new congress member info if it is not already set
                try:
                    congress_members_df.loc[id]
                except KeyError:
                    congress_members_df.loc[id] = asdict(member)
            
            speakers = self.gather_hearing_text(url, hearing_id, congress_info)
            # TODO: add speakers to all speakers
            len_all_speakers += len(speakers)
            for speaker in speakers:
                speakers_df.loc[(hearing_id, speaker.__hash__()), :] = {k: v for k, v in asdict(speaker).items() if k != "statements"}
                statements = [{"hearing_id": hearing_id, "speaker_id": speaker.__hash__(), "statement": statement} for statement in speaker.statements]
                all_statements.extend(statements)

            if len_all_speakers != len(speakers_df):
                raise ValueError("Speakers not added to all speakers")

        # TODO: after the whole script has run, you can go back and try and attribute speakers to
        # any of the all_congress_members
        statements_df = pd.DataFrame(all_statements)
        return (speakers_df, statements_df, congress_members_df)

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
        percent_with_info = len([x for x in speakers if x.congress_member_id])/len(speakers) if len(speakers) != 0 else 0.0
        print(f"Percent speakers with congress info {percent_with_info:.2f}")
        return speakers


# TODO: search: gun control, topics clarence thomas
# climate change

if __name__ == "__main__":
    load_dotenv()

    api_key = os.getenv("GOV_INFO_API_KEY")
    if api_key is None:
        api_key = "DEMO_KEY"

    CongressionalHearingsInfo(50, api_key)
