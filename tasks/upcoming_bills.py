import utils
import logging
import sys
from datetime import date, datetime, time
from dateutil.relativedelta import relativedelta
from dateutil.relativedelta import MO
import lxml, json

#Scraping http://docs.house.gov/floor/

# For any week http://docs.house.gov/floor/Download.aspx?file=/billsthisweek/20131021/20131021.xml
base_url = 'http://docs.house.gov/floor/Download.aspx?file=/billsthisweek/'

def run(options):

  for_the_week = get_monday_week(options.get('for_the_week', None)) #yyyymmdd

  logging.info('Scraping upcoming bills from docs.house.gov/floor for the week %s.' % for_the_week)
  
  # Parse the content into upcoming_bills
  upcoming_bills = fetch_bills_week(for_the_week, options)

  # Write the json to data folder
  output_file = utils.data_dir() + "/upcoming_bills_%s.json" % for_the_week
  utils.write(json.dumps(upcoming_bills, sort_keys=True, indent=2, default=utils.format_datetime), output_file)

def fetch_bills_week(for_the_week, options):
  
  week_url = base_url + '%s/%s.xml' % (for_the_week, for_the_week)
  upcoming_bills = [] 

  body = utils.download(week_url, 'upcoming_bills/%s.xml' % for_the_week, options)

  dom = lxml.etree.fromstring(body)

  congress_num = dom.xpath('//floorschedule')[0].get('congress-num')

  for node in dom.xpath('//floorschedule/category/floor-items/floor-item'):
    bill = {}
    bill['congress'] = congress_num
    bill['bill_id'] = node.xpath('legis-num//text()')[0]
    bill['context'] = node.xpath('floor-text//text()')[0]
    bill['url'] = week_url
    bill['files'] = []
    for file in node.xpath('files/file'):
      file_url = file.get('doc-url')
      file_destination = 'upcoming_bills/%s' % file_url.split('/')[-1]
      try:
        utils.download(file_url, file_destination, options)
        bill['files'].append(file_url)
      except:
        logging.error("Couldn't download file %s from House floors for day %s" % (file_url, for_the_week))

    bill['chamber'] = 'house'
    bill['source_type'] = 'house_floor_weekly'
    bill['legislative_day'] = for_the_week[0:4] + '-' + for_the_week[4:6] + '-' + for_the_week[6:] #'2013-01-21'
    bill['range'] = 'week'
    upcoming_bills.append(bill)

  return upcoming_bills

def get_monday_week(day_to_get_bills):
  if day_to_get_bills is None:
    formatted_day  = date.today()
  else:
    formatted_day = datetime.datetime.strptime(day_to_get_bills, '%Y%m%d').date()
  return (formatted_day + relativedelta(weekday=MO(-1))).strftime('%Y%m%d')

