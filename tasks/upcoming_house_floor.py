import utils
import logging
import sys
from datetime import date, datetime
import time
from dateutil.relativedelta import relativedelta
from dateutil.relativedelta import MO
import lxml, json

# Parsing data from the House' upcoming floor feed, at
# http://docs.house.gov/floor/
#
# This contains data on what bills and draft bills are coming up
# on the floor of the House. It can also contain links to committee
# reports associated with those bills.
#
# This script will transform the data in the provided XML feed to JSON,
# and download associated documents to disk.
#
# TODO:
#   * Detect and extract any XML files attached to PDFs.
#   * parsing out metadata from any provided XML documents.
#
# options:
#   week_of: the date of a Monday of a week to look for. defaults to current week.

def run(options):
  # accepts yyyymmdd format
  for_the_week = get_monday_of_week(options.get('week_of', None))

  logging.warn('Scraping upcoming bills from docs.house.gov/floor for the week of %s.\n' % for_the_week)
  upcoming_bills = fetch_bills_week(for_the_week, options)

  output_file = "%s/upcoming_house_floor/%s.json" % (utils.data_dir(), for_the_week)
  output = json.dumps(upcoming_bills, sort_keys=True, indent=2, default=utils.format_datetime)
  utils.write(output, output_file)

  logging.warn("\nFound %i bills for the week of %s, written to %s" % (len(upcoming_bills), for_the_week, output_file))

# For any week, e.g. http://docs.house.gov/floor/Download.aspx?file=/billsthisweek/20131021/20131021.xml
def fetch_bills_week(for_the_week, options):
  base_url = 'http://docs.house.gov/floor/Download.aspx?file=/billsthisweek/'
  week_url = base_url + '%s/%s.xml' % (for_the_week, for_the_week)

  body = utils.download(week_url, 'upcoming_house_floor/%s.xml' % for_the_week, options)
  dom = lxml.etree.fromstring(body)


  # always present, the congress this is taking place in
  congress = int(dom.xpath('//floorschedule')[0].get('congress-num'))

  # week of this day, e.g. '2013-01-21'
  legislative_day = for_the_week[0:4] + '-' + for_the_week[4:6] + '-' + for_the_week[6:]


  upcoming_bills = []

  for node in dom.xpath('//floorschedule/category/floor-items/floor-item'):
    bill_number = node.xpath('legis-num//text()')[0]
    description  = node.xpath('floor-text//text()')[0]

    if not bill_number:
      logging.warn("Skipping item, not a bill: %s" % description)
      continue

    logging.warn("[%s]" % bill_number)

    # todo: establish most recent date from a combo of added, published, updates
    date = date_for(node.get('publish-date'))

    # all items will have this
    bill = {
      'congress': congress,
      'description': description,
      'floor_item_id': node.get('id'),
      'published_at': date_for(node.get('publish-date')),
      'added_at': date_for(node.get('add-date')),
    }

    # treat drafts and numbered bills a bit differently
    if "_" in bill_number:
      draft_bill_id = draft_bill_id_for(bill_number, date, congress)
      bill['item_type'] = 'draft_bill'
      bill['draft_bill_id'] = draft_bill_id

    else:
      bill_id = bill_id_for(bill_number, congress)
      bill['item_type'] = 'bill'
      bill['bill_id'] = bill_id

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

    upcoming_bills.append(bill)

  return upcoming_bills


def get_monday_of_week(day_to_get_bills):
  if day_to_get_bills is None:
    formatted_day  = date.today()
  else:
    formatted_day = datetime.datetime.strptime(day_to_get_bills, '%Y%m%d').date()

  return (formatted_day + relativedelta(weekday=MO(-1))).strftime('%Y%m%d')

def bill_id_for(bill_number, congress):
  number = bill_number.replace('.', '').replace(' ' , '').lower()
  return "%s-%i" % (number, congress)

def draft_bill_id_for(bill_number, published_at, congress):
  number = bill_number.replace('.', '').replace(' ' , '').replace('_', '').lower()
  epoch = time.mktime(published_at.timetuple())
  return "%s%i-%i" % (number, epoch, congress)

def date_for(timestamp):
  return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%f")