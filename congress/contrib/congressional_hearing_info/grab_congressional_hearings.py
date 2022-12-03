import requests
from datetime import datetime
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from typing import Dict, List, Tuple
from link_speaker_to_congress_member import SpeakerInfo
from parse_congress_member_info import STATE_INITIALS_MAP
from parse_congress_convos import hearing_parser
from dataclasses import asdict, fields
import pandas as pd
import time
import unicodedata
import click
from congress.tasks import utils

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
        api_key: str,
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
        return "".join(
            c
            for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )

    def _cleanup_values(self, moc: Dict) -> Dict:
        most_recent_term = max(moc["terms"], key=lambda x: x["start"])
        state_initals = most_recent_term["state"]
        most_recent_term["state"] = STATE_INITIALS_MAP[state_initals].lower()
        most_recent_term["state_initials"] = state_initals
        most_recent_term["chamber"] = "S" if most_recent_term["type"] == "sen" else "H"
        moc["most_recent_term"] = most_recent_term
        moc["name"]["first"] = self._strip_accents(moc["name"]["first"])
        moc["name"]["last"] = self._strip_accents(moc["name"]["last"])
        if "official_full" in moc["name"]:
            moc["name"]["official_full"] = self._strip_accents(
                moc["name"]["official_full"]
            )
        else:
            moc["name"][
                "official_full"
            ] = f"{moc['name']['first']} {moc['name']['last']}"

        return moc

    def grab_all_congress_members(self, congress_num: int = 117) -> List:
        utils.require_congress_legislators_repo()

        lookup_legislator_cache = {}
        for moc in utils.yaml_load("congress-legislators/legislators-current.yaml"):
            if not moc["id"]["bioguide"]:
                raise ValueError(
                    f"No bioguide id found for {moc['name']['official_full']}"
                )

            # TODO: handle cases where the person switches party, state, ect.

            lookup_legislator_cache[moc["id"]["bioguide"]] = self._cleanup_values(moc)

        return lookup_legislator_cache

    def gather_all_hearings_texts(self, packages: List) -> Tuple[pd.DataFrame]:
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
                summary["percent_with_info"] = percent_with_info
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

    def gather_hearing_text(
        self, url: str, hearing_id: str
    ) -> Tuple[List[SpeakerInfo], Dict]:
        htm = requests.get(url + "/htm", params=self.package_fields)
        if htm.status_code != 200:
            print(f"Error: {htm.status_code} for hearing {hearing_id}")

            return [], {}
        htm_soup = BeautifulSoup(htm.content, "html.parser")

        speakers, summary = self.parser.parse_hearing(hearing_id, htm_soup, url)
        return speakers, summary


@click.command()
@click.option("--num", default=100, help="number of greetings")
def main(num):
    load_dotenv()

    api_key = os.getenv("GOV_INFO_API_KEY")
    if api_key is None:
        api_key = "DEMO_KEY"

    con_hearings = CongressionalHearingsInfo(api_key)
    con_hearings.run(num, api_key)

    # hearing_id = 'CHRG-117hhrg49438'
    # url = f"https://api.govinfo.gov/packages/{hearing_id}"
    # hearing = con_hearings.gather_hearing_text(url, hearing_id)
    print("done")


if __name__ == "__main__":
    main()
