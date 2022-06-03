
# TODO: maybe use the util's download command
import requests
import urllib.parse
from datetime import datetime
import re
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from parse_congress_convos import hearing_parser

load_dotenv()

# safe_string = urllib.parse.quote_plus()

api_key = os.getenv('GOV_INFO_API_KEY')
if api_key is None:
    api_key = 'DEMO_KEY'

collection = 'CHRG'

last_date = datetime(year=2022, month=1, day=1).strftime('%Y-%m-%dT%H:%M:%SZ')

url = f'https://api.govinfo.gov/collections/{collection}/{last_date}'

collection_fields = {
    'api_key': api_key,
    'offset': 0,
    'pageSize': 10,
}

r = requests.get(url, params=collection_fields)
if r.status_code != 200:
    print('Error:', r.status_code)
    exit(1)
collections = r.json()
package_fields = {'api_key': api_key}

for collection in collections['packages']:
    url = collection['packageLink']

    # TODO: maybe verify that htm is a format which exists for this package
    url = f"https://api.govinfo.gov/packages/{collection['packageId']}/htm"
    page = requests.get(url, params=package_fields)
    soup = BeautifulSoup(page.content, 'html.parser')
    hearing_parser(collection = collection, soup = soup)
