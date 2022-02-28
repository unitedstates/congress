# Import the Adler & Wilkerson Congressional Bills Project
# data, which covers bills (but not resolutions) in the
# 80th through 92nd Congress,

import csv
import zipfile
import datetime

from congress.tasks import utils


def run(options):
    # Download the TSV file.
    cache_zip_path = "adler-wilkerson-bills.zip"
    utils.download(
        "http://congressionalbills.org/billfiles/bills80-92.zip",
        cache_zip_path,
        utils.merge(options, {'binary': True, 'needs_content': False}))

    # Unzip in memory and process the records.
    zfile = zipfile.ZipFile(utils.cache_dir() + "/" + cache_zip_path)
    csvreader = csv.DictReader(zfile.open("bills80-92.txt"), delimiter="\t")
    for record in csvreader:
        rec = process_bill(record)

        import pprint
        pprint.pprint(rec)


def process_bill(record):
    # Basic info
    congress = int(record["Cong"])
    bill_type = record["BillType"].lower()  # "HR" or "S" only
    if bill_type not in ('hr', 's'):
        raise ValueError(bill_type)
    number = int(record["BillNum"])

    def binary(value):
        if value == 'NULL':
            return None
        return value == '1'

    def nullydate(value):
        if value == 'NULL':
            return None
        raise ValueError(value)  # never occurs -- there are no dates in the dataset!

    # Last status?
    status = "INTRODUCED"
    status_at = nullydate(record['IntrDate'])
    if record['ReportH'] == '1' or record['ReportS'] == '1':
        status = "REPORTED"
    if record['PassH'] == '1' and record['PassS'] == '1':
        status = "PASSED:BILL"
    elif record['PassH'] == '1':
        status = "PASS_OVER:HOUSE"
    elif record['PassS'] == '1':
        status = "PASS_OVER:SENATE"
    if record['PLaw'] == '1':
        if record['Veto'] == '1':
            status = 'ENACTED:VETO_OVERRIDE'
        else:
            status = 'ENACTED:SIGNED'  # could also have been a 10-day rule
        status_at = nullydate(record['PLawDate'])
    else:
        if record['Veto'] == '1':
            status = 'PROV_KILL:VETO'

    # Form data structure
    return {
        'bill_id': "%s%d-%d" % (bill_type, number, congress),
        'bill_type': bill_type,
        'number': number,
        'congress': congress,

        'introduced_at': nullydate(record['IntrDate']),
        'sponsor': int(record['PooleID']) if record['PooleID'] != 'NULL' else None,
        #'cosponsors': ,

        #'actions': ,
        'history': {
            'house_passage_result': "pass" if record['PassH'] == '1' else None,
            'senate_passage_result': "pass" if record['PassS'] == '1' else None,
            'enacted': record['PLaw'] == '1',
            'enacted_at': nullydate(record['PLawDate']),
        },
        'status': status,
        'status_at': status_at,
        'enacted_as': {
            'law_type': "public",
            'congress': congress,
            'number': int(record['PLawNum']),
        } if record['PLaw'] == '1' else None,  # private laws?

        #'titles': ,
        'official_title': record['Title'],
        #'short_title': ,
        #'popular_title': ,

        #'summary': ,
        'subjects_top_term': int(record['Major']),
        'subjects': [int(record['Minor'])],

        #'related_bills': ,
        #'committees': ,
        #'amendments': ,

        # special fields
        'by_request': binary(record['ByReq']),
        'commemerative': binary(record['Commem']),
        'num_cosponsors': int(record['Cosponsr']) if record['Cosponsr'] != 'NULL' else None,
        'private': binary(record['Private']),

        # meta-metadata
        'updated_at': datetime.datetime.now(),
    }
