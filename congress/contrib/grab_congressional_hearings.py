# TODO: maybe use the util's download command
import requests
import urllib.parse
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from parse_congress_convos import hearing_parser
from parse_congress_member_info import CongressMemberParser

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

all_speakers = {}
for collection in collections["packages"]:
    # TODO: maybe verify that htm is a format which exists for this package
    url = f"https://api.govinfo.gov/packages/{collection['packageId']}"

    htm = requests.get(url + "/htm", params=package_fields)
    htm_soup = BeautifulSoup(htm.content, "html.parser")

    mods = requests.get(url + "/mods", params=package_fields)
    mods_soup = BeautifulSoup(mods.content, "xml")
    congress_info = congress_member_parser.grab_congress_info(mods_soup)

    # gran = requests.get(url+'/granules', params=package_fields)
    # gran_0 = gran.json()['granules'][0]
    # gran_id = gran_0['granuleId']

    speakers = parser.parse_hearing(collection["packageId"], htm_soup, congress_info)
    print(len(speakers))
    # for name, words in speakers.items():
    #     cur_words = all_speakers.get(name, {})
    #     cur_words[collection['packageId']] = words
    #     all_speakers[name] = cur_words

print(f"total len: {len(all_speakers)}")
# [speaker for speaker, hearing in all_speakers.items() if len(hearing.keys())>1]
