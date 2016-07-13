import utils
import logging
import sys
import os
from datetime import date, datetime
import time
from dateutil.relativedelta import relativedelta
from dateutil.relativedelta import MO
import lxml
import json
import re

from bs4 import BeautifulSoup

# Parsing data from the House' upcoming floor feed, at
# http://docs.house.gov/floor/
#
# This contains data on what bills and draft bills are coming up
# on the floor of the House.
#
# This script will transform the data in the provided XML feed to JSON,
# and download associated documents to disk.
#
# TODO:
#   * Detect and extract any XML files attached to PDFs.
#   * parsing out metadata from any provided XML documents.
#   * handle 'subitems' (e.g. House committee reports)
#
# options:
#   week_of: the date of a Monday of a week to look for. defaults to current week.


def run(options):
    # accepts yyyymmdd format
    given_week = options.get('week_of', None)
    if given_week is None:
        for_the_week = get_latest_monday(options)
    else:
        for_the_week = get_monday_of_week(given_week)

    logging.warn('Scraping upcoming bills from docs.house.gov/floor for the week of %s.\n' % for_the_week)
    house_floor = fetch_floor_week(for_the_week, options)

    output_file = "%s/upcoming_house_floor/%s.json" % (utils.data_dir(), for_the_week)
    output = json.dumps(house_floor, sort_keys=True, indent=2, default=utils.format_datetime)
    utils.write(output, output_file)

    logging.warn("\nFound %i bills for the week of %s, written to %s" % (len(house_floor['upcoming']), for_the_week, output_file))


# For any week, e.g. http://docs.house.gov/floor/Download.aspx?file=/billsthisweek/20131021/20131021.xml
def fetch_floor_week(for_the_week, options):
    base_url = 'http://docs.house.gov/floor/Download.aspx?file=/billsthisweek/'
    week_url = base_url + '%s/%s.xml' % (for_the_week, for_the_week)

    body = utils.download(week_url, 'upcoming_house_floor/%s.xml' % for_the_week, options)
    dom = lxml.etree.fromstring(body)

    # can download the actual attached files to disk, if asked
    download = options.get("download", False)

    # always present at the feed level
    congress = int(dom.xpath('//floorschedule')[0].get('congress-num'))

    # week of this day, e.g. '2013-01-21'
    legislative_day = for_the_week[0:4] + '-' + for_the_week[4:6] + '-' + for_the_week[6:]

    upcoming = []

    for node in dom.xpath('//floorschedule/category/floor-items/floor-item'):
        bill_number = node.xpath('legis-num//text()')[0]

        # TODO: fetch non-bills too
        if not bill_number:
            logging.warn("Skipping item, not a bill: %s" % description)
            continue

        description = node.xpath('floor-text//text()')[0]

        # how is this bill being considered?
        category = node.iterancestors("category").next().get('type')
        if "suspension" in category:
            consideration = "suspension"
        elif "pursuant" in category:
            consideration = "rule"
        else:
            consideration = "unknown"

        logging.warn("[%s]" % bill_number)

        # todo: establish most recent date from a combo of added, published, updates
        date = date_for(node.get('publish-date'))

        # all items will have this
        bill = {
            'description': description,
            'floor_item_id': node.get('id'),
            'consideration': consideration,
            'published_at': date_for(node.get('publish-date')),
            'added_at': date_for(node.get('add-date')),
        }
        
        # treat drafts and numbered bills a bit differently
        if "_" in bill_number:
            draft_bill_id = draft_bill_id_for(bill_number, date, congress)
            bill['item_type'] = 'draft_bill'
            bill['draft_bill_id'] = draft_bill_id
        else:
            if "Concur in the Senate Amendment to" in bill_number:
                bill['item_type'] = 'senate_amendment'
                bill_number = bill_number.replace('Concur in the Senate Amendment to ', '')
            elif "Concur in the Senate Amendment with an Amendment to" in bill_number:
                bill['item_type'] = 'senate_amendment'
                bill_number = bill_number.replace('Concur in the Senate Amendment with an Amendment to ', '')
            elif "senate amendment to the house amendment to" in bill_number.lower():
                bill['item_type'] = 'senate_amendment'
                bill_number = bill_number.lower().replace("senate amendment to the house amendment to ", '')
            elif "senate amendment to " in bill_number.lower():
                bill['item_type'] = 'senate_amendment'
                bill_number = bill_number.lower().replace("senate amendment to ", '')
            elif "house amendment to " in bill_number.lower():
                bill['item_type'] = 'house_amendment'
                bill_number = bill_number.lower().replace("house amendment to ", '')
            elif "Conference report to accompany" in bill_number:
                bill['item_type'] = 'conference_report'
                bill_number = bill_number.replace("Conference report to accompany ", '')
            else:
                bill['item_type'] = 'bill'
        
            bill['bill_id'] = bill_id_for(bill_number.strip(), congress)

        bill['files'] = []
        for file in node.xpath('files/file'):
            file_url = file.get('doc-url')
            filename = file_url.split('/')[-1]
            file_format = file.get('doc-type').lower()

            logging.warn("\t%s file for %s: %s" % (file_format.upper(), bill_number, filename))

            file_field = {
                'url': file_url,
                'format': file_format,
                'added_at': date_for(file.get('add-date')),
                'published_at': date_for(file.get('publish-date'))
            }

            # now try downloading the file to disk and linking it to the data
            try:
                file_path = 'upcoming_house_floor/%s/%s' % (for_the_week, filename)
                utils.download(file_url, file_path, options)
                file_field['path'] = file_path
            except:
                logging.error("Omitting 'path', couldn't download file %s from House floor for the week of %s" % (file_field['url'], for_the_week))

            bill['files'].append(file_field)

        upcoming.append(bill)

    house_floor = {
        'congress': congress,
        'week_of': legislative_day,
        'upcoming': upcoming
    }
    return house_floor


def get_monday_of_week(day_to_get_bills):
    formatted_day = datetime.strptime(day_to_get_bills, '%Y%m%d').date()
    return (formatted_day + relativedelta(weekday=MO(-1))).strftime('%Y%m%d')

# actually go fetch docs.house.gov/floor/ and scrape the download link out of it


def get_latest_monday(options):
    url = "http://docs.house.gov/floor/"
    html = utils.download(url, None, options)
    doc = BeautifulSoup(html)

    links = doc.select("a.downloadXML")
    if len(links) != 1:
        utils.admin("Error finding download link for this week!")
        return None

    link = links[0]
    week = os.path.split(link['href'])[-1].split(".")[0]

    return week


def bill_id_for(bill_number, congress):
    number = bill_number.replace('.', '').replace(' ', '').lower()
    if not re.match(r"^(hr|s|hres|sres|hjres|sjres|hconres|sconres)\d{1,4}$", number): raise ValueError(number)
    return "%s-%i" % (number, congress)


def draft_bill_id_for(bill_number, published_at, congress):
    number = bill_number.replace('.', '').replace(' ', '').replace('_', '').lower()
    epoch = time.mktime(published_at.timetuple())
    return "%s%i-%i" % (number, epoch, congress)


def date_for(timestamp):
    if "." not in timestamp:
        strptime_config = "%Y-%m-%dT%H:%M:%S"
    else:
        strptime_config = "%Y-%m-%dT%H:%M:%S.%f"
    return datetime.strptime(timestamp, strptime_config)
