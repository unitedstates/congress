import requests
from datetime import datetime
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from typing import Dict, List
from link_speaker_to_congress_member import SpeakerInfo
from parse_congress_member_info import STATE_INITIALS_MAP
from parse_congress_convos import hearing_parser
from dataclasses import asdict, fields
import pandas as pd
import time
import unicodedata

# TODO: write more tests covering complex funcs

class CongressionalHearingsInfo:
    HEARING_COLLECTION_CODE = "CHRG"

    def __init__(self, api_key: str):
        self.package_fields = {
            "api_key": api_key,
            "offset": 0,
            "pageSize": 20,
        }
        self.congress_members = self.grab_all_congress_members()
        self.parser = hearing_parser(self.congress_members, self.package_fields)


    def run(
        self,
        size: int,
        last_date: datetime = datetime(year=2020, month=1, day=1),
    ):
        last_date_str = last_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"https://api.govinfo.gov/collections/{self.HEARING_COLLECTION_CODE}/{last_date_str}"

        packages = []
        for offset in range(0, size, 100):
            collection_fields = {
                "api_key": api_key,
                "offset": offset,
                "pageSize": min(100, size - offset),
            }
            r = requests.get(url, params=collection_fields)
            if r.status_code != 200:
                print("Error when calling govinfo", r.status_code)
                exit(1)
            packages.extend(r.json()["packages"])

        print(f"parsing {len(packages)} packages")
        (
            speakers_df,
            statements_df,
            summary_df,
        ) = self.gather_all_hearings_texts(packages)
        speakers_df.to_parquet("speakers.parquet")
        statements_df.to_parquet("statements.parquet")
        summary_df.to_parquet("summary.parquet")
        congress_members_df = pd.DataFrame(self.congress_members.values())
        congress_members_df.to_parquet("congress_members.parquet")

    def _strip_accents(self, s):
        """Needed because the htm text for there hearings doesn't use accents"""
        if not s:
            return s
        return ''.join(c for c in unicodedata.normalize('NFD', s)
                        if unicodedata.category(c) != 'Mn')

    def _add_extra_info(self, congress_members: List[Dict], chamber: str) -> None:
        for member in congress_members:
            state_initals = member["state"]
            member["state"] = STATE_INITIALS_MAP[state_initals].lower()
            member["state_initials"] = state_initals
            member["chamber"] = chamber
            member["first_name"] = self._strip_accents(member["first_name"])
            member["middle_name"] = self._strip_accents(member["middle_name"])
            member["last_name"] = self._strip_accents(member["last_name"])

    def grab_all_congress_members(self, congress_num: int = 117) -> List:
        api_key = os.getenv("PROPUBLICA_API_KEY")
        if not api_key:
            raise ValueError(
                "PROPUBLICA_API_KEY env var required for this code. Checkout https://projects.propublica.org/api-docs/congress-api/"
            )

        header = {"X-API-Key": api_key}
        response = requests.get(
            f"https://api.propublica.org/congress/v1/{congress_num}/senate/members.json",
            headers=header,
        )
        senate_members = response.json()["results"][0]["members"]
        self._add_extra_info(senate_members, "S")
        response = requests.get(
            f"https://api.propublica.org/congress/v1/{congress_num}/house/members.json",
            headers=header,
        )
        house_members = response.json()["results"][0]["members"]
        self._add_extra_info(house_members, "H")

        return {x["id"]: x for x in senate_members + house_members}

    def gather_all_hearings_texts(self, packages: List):
        speakers_df = pd.DataFrame(
            columns=["hearing_id", "id"]
            + [
                field.name
                for field in fields(SpeakerInfo)
                if field.name != "statements"
            ]
        )
        speakers_df.set_index(["hearing_id", "id"], inplace=True)

        all_statements = []
        all_summaries = {}
        len_all_speakers = 0
        for collection in packages:
            time.sleep(0.25)
            hearing_id = collection["packageId"]
            url = f"https://api.govinfo.gov/packages/{hearing_id}"

            try:
                speakers, summary = self.gather_hearing_text(url, hearing_id)
            except Exception as e:
                print(f"Uncaught exception for {hearing_id}\n{e}")
                speakers = []
            if len(speakers) != 0:
                percent_with_info = len(
                    [x for x in speakers if x.congress_member_id]
                ) / len(speakers)
                summary['percent_with_info'] = percent_with_info
                all_summaries[hearing_id] = summary
                print(f"Percent speakers with congress info {percent_with_info:.2f}")
            len_all_speakers += len(speakers)
            for speaker in speakers:
                speakers_df.loc[(hearing_id, speaker.__hash__()), :] = {
                    k: v for k, v in asdict(speaker).items() if k != "statements"
                }
                statements = [
                    {
                        "hearing_id": hearing_id,
                        "speaker_id": speaker.__hash__(),
                        "statement": statement,
                    }
                    for statement in speaker.statements
                ]
                all_statements.extend(statements)

        statements_df = pd.DataFrame(all_statements)
        summaries_df = pd.DataFrame(all_summaries).T
        return (speakers_df, statements_df, summaries_df)

    def gather_hearing_text(self, url: str, hearing_id: str):
        htm = requests.get(url + "/htm", params=self.package_fields)
        if htm.status_code != 200:
            print(f"Error: {htm.status_code} for hearing {hearing_id}")

            return []
        htm_soup = BeautifulSoup(htm.content, "html.parser")

        speakers, summary = self.parser.parse_hearing(hearing_id, htm_soup, url)
        return speakers, summary

if __name__ == "__main__":
    load_dotenv()

    api_key = os.getenv("GOV_INFO_API_KEY")
    if api_key is None:
        api_key = "DEMO_KEY"

    con_hearings = CongressionalHearingsInfo(api_key)
    con_hearings.run(250)

    # hearing_id = 'CHRG-114hhrg94749'
    # url = f"https://api.govinfo.gov/packages/{hearing_id}"
    # con_hearings.gather_hearing_text(url, hearing_id)
