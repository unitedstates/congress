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
    bill['bill_id']  = node.xpath('legis-num//text()')[0]
    bill['floor_item_id'] = node.get('id') 
    bill['added_at'] = node.get('add-date')
    bill['published_at'] = node.get('publish-date')
    bill['context']  = node.xpath('floor-text//text()')[0]
    bill['url'] = week_url
    bill['files'] = []
    for file in node.xpath('files/file'):
      file_field = {}
      file_field['url'] = file.get('doc-url')
      file_field['path'] = 'upcoming_bills/%s' % file_field['url'].split('/')[-1]
      file_field['added_at'] = file.get('add-date')
      file_field['published_at'] = file.get('publish-date')
      try:
        utils.download(file_field['url'], file_field['path'], options)
        bill['files'].append(file_field)
      except:
        logging.error("Couldn't download file %s from House floors for day %s" % (file_field['url'], for_the_week))

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

