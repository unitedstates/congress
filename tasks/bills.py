import json
import logging
import os
import re
import xmltodict

import bill_info
import amendment_info
import govinfo
import utils


def run(options):
    bill_id = options.get('bill_id', None)

    if bill_id:
        bill_type, number, congress = utils.split_bill_id(bill_id)
        to_fetch = [bill_id]
    else:
        to_fetch = get_bills_to_process(options)

        if not to_fetch:
            logging.warn("No bills changed.")
            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    utils.process_set(to_fetch, process_bill, options)


def get_bills_to_process(options):
    # Return a generator over bill_ids that need to be processed.
    # Every time we process a bill we copy the fdsys_billstatus-lastmod.txt
    # file to data-fromfdsys-lastmod.txt, next to data.json. This way we
    # know when the GovInfo (formerly FDSys) XML file has changed.

    def get_data_path(*args):
        # Utility function to generate a part of the path
        # to data/{congress}/bills/{billtype}/{billtypenumber}
        # given as many path elements as are provided. args
        # is a list of zero or more of congress, billtype,
        # and billtypenumber (in order).
        args = list(args)
        if len(args) > 0:
            args.insert(1, "bills")
        return os.path.join(utils.data_dir(), *args)

    if not options.get('congress'):
        # Get a list of all congress directories on disk.
        # Filter out non-integer directory names, then sort on the
        # integer.
        def filter_ints(seq):
            for s in seq:
                try:
                    yield int(s)
                except:
                    # Not an integer.
                    continue
        congresses = sorted(filter_ints(os.listdir(get_data_path())))
    else:
        congresses = sorted([int(c) for c in options['congress'].split(',')])

    # walk through congresses
    for congress in congresses:
        # turn this back into a string
        congress = str(congress)

        # walk through all bill types in that congress
        # (sort by bill type so that we proceed in a stable order each run)

        bill_types = [bill_type for bill_type in os.listdir(get_data_path(congress)) if not bill_type.startswith(".")]

        for bill_type in sorted(bill_types):

            # walk through each bill in that congress and bill type
            # (sort by bill number so that we proceed in a normal order)

            bills = [bill for bill in os.listdir(get_data_path(congress, bill_type)) if not bill.startswith(".")]
            for bill_type_and_number in sorted(
                bills,
                key = lambda x : int(x.replace(bill_type, ""))
                ):

                fn = get_data_path(congress, bill_type, bill_type_and_number, govinfo.FDSYS_BILLSTATUS_FILENAME)
                if os.path.exists(fn):
                    # The GovInfo.gov bulk data file exists. Does our JSON data
                    # file need to be updated?
                    bulkfile_lastmod = utils.read(fn.replace(".xml", "-lastmod.txt"))
                    parse_lastmod = utils.read(get_data_path(congress, bill_type, bill_type_and_number, "data-fromfdsys-lastmod.txt"))
                    if bulkfile_lastmod != parse_lastmod or options.get("force"):
                        bill_id = bill_type_and_number + "-" + congress
                        yield bill_id

def process_bill(bill_id, options):
    fdsys_xml_path = _path_to_billstatus_file(bill_id)
    logging.info("[%s] Processing %s..." % (bill_id, fdsys_xml_path))

    # Read FDSys bulk data file.
    xml_as_dict = read_fdsys_bulk_bill_status_file(fdsys_xml_path, bill_id)
    bill_data = form_bill_json_dict(xml_as_dict)

    # Convert and write out data.json and data.xml.
    utils.write(
        unicode(json.dumps(bill_data, indent=2, sort_keys=True)),
        os.path.dirname(fdsys_xml_path) + '/data.json')

    from bill_info import create_govtrack_xml
    with open(os.path.dirname(fdsys_xml_path) + '/data.xml', 'wb') as xml_file:
        xml_file.write(create_govtrack_xml(bill_data, options))

    if options.get("amendments", True):
        process_amendments(bill_id, xml_as_dict, options)

    # Mark this bulk data file as processed by saving its lastmod
    # file under a new path.
    utils.write(
        utils.read(_path_to_billstatus_file(bill_id).replace(".xml", "-lastmod.txt")),
        os.path.join(os.path.dirname(fdsys_xml_path), "data-fromfdsys-lastmod.txt"))

    return {
        "ok": True,
        "saved": True,
    }

def _path_to_billstatus_file(bill_id):
    return output_for_bill(bill_id, govinfo.FDSYS_BILLSTATUS_FILENAME, is_data_dot=False)

def read_fdsys_bulk_bill_status_file(fn, bill_id):
    fdsys_billstatus = utils.read(fn)
    return xmltodict.parse(fdsys_billstatus, force_list=('item', 'amendment', 'committeeReport', 'link'))

def form_bill_json_dict(xml_as_dict):
    """
    Handles converting a government bulk XML file to legacy dictionary form.

    @param bill_id: id of the bill in format [type][number]-[congress] e.x. s934-113
    @type bill_id: str
    @return: dictionary of bill attributes
    @rtype: dict
    """

    bill_dict = xml_as_dict['billStatus']['bill']
    bill_id = build_bill_id(bill_dict['billType'].lower(), bill_dict['billNumber'], bill_dict['congress'])
    titles = bill_info.titles_for(bill_dict['titles']['item'])
    actions = bill_info.actions_for(bill_dict['actions']['item'], bill_id, bill_info.current_title_for(titles, 'official'))
    status, status_date = bill_info.latest_status(actions, bill_dict.get('introducedDate', ''))

    bill_data = {
        'bill_id': bill_id,
        'bill_type': bill_dict.get('billType').lower(),
        'number': bill_dict.get('billNumber'),
        'congress': bill_dict.get('congress'),

        'url': billstatus_url_for(bill_id),

        'introduced_at': bill_dict.get('introducedDate', ''),
        'by_request': bill_dict['sponsors']['item'][0]['byRequestType']     is not None,
        'sponsor': bill_info.sponsor_for(bill_dict['sponsors']['item'][0]),
        'cosponsors': bill_info.cosponsors_for(bill_dict['cosponsors']),

        'actions': actions,
        'history': bill_info.history_from_actions(actions),
        'status': status,
        'status_at': status_date,
        'enacted_as': bill_info.slip_law_from(actions),

        'titles': titles,
        'official_title': bill_info.current_title_for(titles, 'official'),
        'short_title': bill_info.current_title_for(titles, 'short'),
        'popular_title': bill_info.current_title_for(titles, 'popular'),

        'summary': bill_info.summary_for(bill_dict['summaries']['billSummaries']),

        # The top term's case has changed with the new bulk data. It's now in
        # Title Case. For backwards compatibility, the top term is run through
        # '.capitalize()' so it matches the old string. TODO: Remove one day?
        'subjects_top_term': _fixup_top_term_case(bill_dict['policyArea']['name']) if bill_dict['policyArea'] else None,
        'subjects':
            sorted(
                ([_fixup_top_term_case(bill_dict['policyArea']['name'])] if bill_dict['policyArea'] else []) +
                ([item['name'] for item in bill_dict['subjects']['billSubjects']['legislativeSubjects']['item']] if bill_dict['subjects']['billSubjects']['legislativeSubjects'] else [])
            ),

        'related_bills': bill_info.related_bills_for(bill_dict['relatedBills']),
        'committees': bill_info.committees_for(bill_dict['committees']['billCommittees']),
        'amendments': bill_info.amendments_for(bill_dict['amendments']),
        'committee_reports': bill_info.committee_reports_for(bill_dict['committeeReports']),

        'updated_at': bill_dict.get('updateDate', ''),
    }

    return bill_data

def _fixup_top_term_case(term):
    if term in ("Native Americans",):
        return term
    return term.capitalize()

def build_bill_id(bill_type, bill_number, congress):
    return "%s%s-%s" % (bill_type, bill_number, congress)

def billstatus_url_for(bill_id):
    bill_type, bill_number, congress = utils.split_bill_id(bill_id)
    return govinfo.BULKDATA_BASE_URL + 'BILLSTATUS/{0}/{1}/BILLSTATUS-{0}{1}{2}.xml'.format(congress, bill_type, bill_number)

def output_for_bill(bill_id, format, is_data_dot=True):
    bill_type, number, congress = utils.split_bill_id(bill_id)
    if is_data_dot:
        fn = "data.%s" % format
    else:
        fn = format
    return "%s/%s/bills/%s/%s%s/%s" % (utils.data_dir(), congress, bill_type, bill_type, number, fn)

def process_amendments(bill_id, bill_amendments, options):
    amdt_list = bill_amendments['billStatus']['bill']['amendments']
    if amdt_list is None:  # many bills don't have amendments
        return

    for amdt in amdt_list['amendment']:
        amendment_info.process_amendment(amdt, bill_id, options)

