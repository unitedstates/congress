from congress.tasks import utils
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
import subprocess

from bs4 import BeautifulSoup

from congress.tasks.bills import output_for_bill

# Parsing data from the House' upcoming floor feed, at
# https://docs.house.gov/floor/
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
#   download: download associated documents and convert PDFs to text


def run(options):
    # accepts yyyymmdd format
    given_week = options.get('week_of', None)
    if given_week is None:
        for_the_weeks = get_mondays_to_scan(options)
    else:
        for_the_weeks = [get_monday_of_week(given_week)]

    # fetch info
    for for_the_week in for_the_weeks:
        run_for_week(for_the_week, options)

def run_for_week(for_the_week, options):
    logging.info('Scraping upcoming bills from docs.house.gov/floor for the week of %s...' % for_the_week)
    house_floor = fetch_floor_week(for_the_week, options)
    if house_floor is None:
        logging.warn("Nothing posted for the week of %s" % for_the_week)
        return

    output_file = "%s/upcoming_house_floor/%s.json" % (utils.data_dir(), for_the_week)
    output = json.dumps(house_floor, sort_keys=True, indent=2, default=utils.format_datetime)
    utils.write(output, output_file)

    logging.warn("Found %i bills for the week of %s, written to %s" % (len(house_floor['upcoming']), for_the_week, output_file))


# For any week, e.g. https://docs.house.gov/floor/Download.aspx?file=/billsthisweek/20131021/20131021.xml
def fetch_floor_week(for_the_week, options):
    base_url = 'https://docs.house.gov/floor/Download.aspx?file=/billsthisweek/'
    week_url = base_url + '%s/%s.xml' % (for_the_week, for_the_week)

    # Turn on 'force' to re-download the schedules, by default, since the content
    # changes frequently and we're scanning weeks that might have 404'd previously
    # when we looked ahead. We leave 'force' off for downloading the file attachments.
    options2 = dict(options)
    if "force" not in options2:
        options2["force"] = True

    body = utils.download(week_url, 'upcoming_house_floor/%s.xml' % for_the_week, options2)
    if "was not found" in body: return None
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
        category = next(node.iterancestors("category")).get('type')
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
            m = re.match("(Concur(ring)? in )?(?P<type>((the )?(Senate|House) Amendments? (with an amendment )?to )+)(?P<bill>.*)", bill_number, re.I)
            if m:
              amendment_type = m.group("type").split("to")[0]
              if "Senate" in amendment_type and "House" not in amendment_type:
                  bill['item_type'] = 'senate_amendment'
              elif "House" in amendment_type and "Senate" not in amendment_type:
                bill['item_type'] = 'house_amendment'
              else:
                raise ValueError(bill_number)
              bill_number = m.group("bill")

            elif re.match("Conference report to accompany ", bill_number, re.I):
                bill['item_type'] = 'conference_report'
                bill_number = bill_number.lower().replace("conference report to accompany ", '')
            else:
                bill['item_type'] = 'bill'

            # In one case we got "H. Res. 497 (H. Rept. 116-125)".
            # Stop at parens.
            bill_number = re.sub(r"\(.*", "", bill_number)

            try:
                bill['bill_id'] = bill_id_for(bill_number.strip(), congress)
            except ValueError:
                logging.error("Could not parse bill from: %s" % bill_number)
                continue
                

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

            bill['files'].append(file_field)

            # now try downloading the file to disk and linking it to the data
            if not download: continue
            try:
                file_path = 'upcoming_house_floor/%s/%s' % (for_the_week, filename)
                try:
                    os.makedirs(os.path.join(utils.data_dir(), os.path.dirname(file_path)))
                except OSError:
                    pass # directory exists
                options3 = dict(options)
                options3["to_cache"] = False # put in the actual specified directory
                options3["binary"] = True # force binary mode, no file escaping
                utils.download(file_url, os.path.join(utils.data_dir(), file_path), options3)
                file_field['path'] = file_path
            except IOError:
                logging.error("Omitting 'path', couldn't download file %s from House floor for the week of %s" % (file_field['url'], for_the_week))
                continue

            # if it's a PDF, convert to text and extract XML
            if file_format == "pdf" and file_path.endswith(".pdf"):
                # extract text
                text_path = file_path.replace(".pdf", ".txt")
                if subprocess.call(["pdftotext", "-layout",
                    os.path.join(utils.data_dir(), file_path),
                    os.path.join(utils.data_dir(), text_path)],
                    universal_newlines=True) != 0:
                    raise Exception("pdftotext failed on %s" % file_path)
                file_field['text_path'] = text_path

                # extract embedded XML
                for line in subprocess.check_output(["pdfdetach", "-list",
                    os.path.join(utils.data_dir(), file_path)],
                    universal_newlines=True).split("\n"):
                    m = re.match(r"(\d+):\s*(.*)", line)
                    if m:
                        attachment_n, attachment_fn = m.groups()
                        if attachment_fn.endswith(".xml"):
                            text_path = file_path.replace(".pdf", ".xml")
                            subprocess.check_call(["pdfdetach",
                                os.path.join(utils.data_dir(), file_path),
                                "-save", attachment_n, "-o",
                                os.path.join(utils.data_dir(), text_path)],
                                universal_newlines=True)
                            file_field['xml_path'] = text_path

        upcoming.append(bill)

        if "bill_id" in bill:
	        # Save this bill data to the bill's bill text directory.
	        text_data_path = output_for_bill(bill['bill_id'], os.path.join("text-versions", "dhg-" + bill["floor_item_id"] + ".json"), is_data_dot=False)
	        try:
	            os.makedirs(os.path.join(utils.data_dir(), os.path.dirname(text_data_path)))
	        except OSError:
	            pass # directory exists
        	utils.write(json.dumps(bill, sort_keys=True, indent=2, default=utils.format_datetime), text_data_path)


    # Create and return the house floor file data.
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
    # docs.house.gov always links to the most recent week that isn't in the future.
    url = "https://docs.house.gov/floor/"
    html = utils.download(url, None, options)
    doc = BeautifulSoup(html, features="lxml")

    links = doc.select("a.downloadXML")
    if len(links) != 1:
        utils.admin("There is no docs.house.gov download link --- maybe there are no upcoming bills.")
        return None

    link = links[0]
    week = os.path.split(link['href'])[-1].split(".")[0]
    week = datetime.strptime(week, "%Y%m%d").date()

    return week

def get_mondays_to_scan(options):
    # Get the week currently linked on docs.house.gov. If there isn't any (e.g. we are between
    # sessions), just return an empty list of weeks to scan.
    most_recent = get_latest_monday(options)
    if most_recent is None:
        return []

    # Look two weeks into the future too, since when we get to the end of the week the next
    # week's list is sometimes available, and sometimes a week beyond that.
    return [(most_recent + relativedelta(days=7*i)).strftime("%Y%m%d") for i in [0, 1, 2]]


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
