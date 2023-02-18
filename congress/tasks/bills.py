import json
import logging
import os
import re
import xmltodict

from congress.tasks import bill_info, amendment_info, govinfo, utils


def run(options):
    bill_id = options.get('bill_id', None)

    processor_func = process_bill

    if options.get("reparse_actions"):
        # Overrid default behavior.
        processor_func = reparse_actions

    if bill_id:
        to_fetch = bill_id.split(",")
    else:
        if options.get("matching_action_regex"):
            options["matching_action_regex"] = re.compile(options["matching_action_regex"])

        to_fetch = get_bills_to_process(options)

        if not to_fetch:
            logging.warn("No bills changed.")
            return None

        limit = options.get('limit', None)
        if limit:
            to_fetch = to_fetch[:int(limit)]

    utils.process_set(to_fetch, processor_func, options)


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

        # If we're reprocessing actions, start with the 93rd Congress.
        # Before that we may have bill data from other sources that don't
        # conform to the usual action parsing logic.
        if options.get("reparse_actions"):
            congresses = filter(lambda c : c >= 93, congresses)
    else:
        congresses = sorted([int(c) for c in options['congress'].split(',')])

    # walk through congresses
    for congress in congresses:
        # turn this back into a string
        congress = str(congress)

        # walk through all bill types in that congress
        # (sort by bill type so that we proceed in a stable order each run)
        path = get_data_path(congress)
        if not os.path.exists(path): continue
        bill_types = [bill_type for bill_type in os.listdir(path) if not bill_type.startswith(".")]

        for bill_type in sorted(bill_types):

            # walk through each bill in that congress and bill type
            # (sort by bill number so that we proceed in a normal order)
            path = get_data_path(congress, bill_type)
            if not os.path.exists(path): continue
            bills = [bill for bill in os.listdir(path) if not bill.startswith(".")]
            for bill_type_and_number in sorted(
                bills,
                key = lambda x : int(x.replace(bill_type, ""))
                ):

                bill_id = bill_type_and_number + "-" + congress

                if options.get("matching_action_regex"):
                    # Include bills that have an action that matches a regular expression.
                    fn = get_data_path(congress, bill_type, bill_type_and_number, "data.json")
                    if os.path.exists(fn):
                        with open(fn) as f:
                            bill = json.load(f)
                            for action in bill['actions']:
                                if action.get('text') and options["matching_action_regex"].search(action['text']):
                                    yield bill_id
                    continue # don't check modification dates

                fn = get_data_path(congress, bill_type, bill_type_and_number, govinfo.FDSYS_BILLSTATUS_FILENAME)
                if os.path.exists(fn):
                    # The GovInfo.gov bulk data file exists. Does our JSON data
                    # file need to be updated?
                    bulkfile_lastmod = utils.read(fn.replace(".xml", "-lastmod.txt"))
                    parse_lastmod = utils.read(get_data_path(congress, bill_type, bill_type_and_number, "data-fromfdsys-lastmod.txt"))
                    if bulkfile_lastmod != parse_lastmod or options.get("force"):
                        yield bill_id

def process_bill(bill_id, options):
    fdsys_xml_path = _path_to_billstatus_file(bill_id)
    logging.info("[%s] Processing %s..." % (bill_id, fdsys_xml_path))

    # Read FDSys bulk data file.
    xml_as_dict = read_fdsys_bulk_bill_status_file(fdsys_xml_path, bill_id)
    bill_data = form_bill_json_dict(xml_as_dict)
    if isinstance(bill_data, str): # Non-error failure
        return {
            "ok": True,
            "saved": False,
            "reason": bill_data,
        }

    # Convert and write out data.json and data.xml.
    utils.write(
        json.dumps(bill_data, indent=2, sort_keys=True),
        os.path.dirname(fdsys_xml_path) + '/data.json',
        {
            "diff": options.get("diff")
        })

    from congress.tasks.bill_info import create_govtrack_xml
    with open(os.path.dirname(fdsys_xml_path) + '/data.xml', 'wb') as xml_file:
        xml_file.write(create_govtrack_xml(bill_data, options))

    if options.get("amendments", True):
        process_amendments(bill_id, xml_as_dict, options)

    # Mark this bulk data file as processed by saving its lastmod
    # file under a new path.
    utils.write(
        utils.read(_path_to_billstatus_file(bill_id).replace(".xml", "-lastmod.txt")),
        os.path.join(os.path.dirname(fdsys_xml_path), "data-fromfdsys-lastmod.txt"),
        {
            "diff": options.get("diff")
        })

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

    from packaging.version import parse as parse_version
    try:
        schema_version = parse_version(xml_as_dict['billStatus']['version'])
    except KeyError: # no 'version' attribute is present before 2022-12-20
        schema_version = parse_version('1.0.0')

    bill_dict = xml_as_dict['billStatus']['bill']
    if schema_version >= parse_version('3.0.0'):
        bill_id = build_bill_id(bill_dict['type'].lower(), bill_dict['number'], bill_dict['congress'])
    else:
        bill_id = build_bill_id(bill_dict['billType'].lower(), bill_dict['billNumber'], bill_dict['congress'])
    titles = bill_info.titles_for(bill_dict['titles']['item'])
    actions = bill_info.actions_for(bill_dict['actions']['item'], bill_id, bill_info.current_title_for(titles, 'official'))
    status, status_date = bill_info.latest_status(actions, bill_dict.get('introducedDate', ''))

    if bill_dict['sponsors'] is None and bill_dict['titles']['item'][0]['title'].startswith("Reserved "):
        logging.info("[%s] Skipping reserved bill number with no sponsor (%s)" % (bill_id, bill_dict['titles']['item'][0]['title']))
        return bill_dict['titles']['item'][0]['title'] # becomes the 'reason'

    if schema_version >= parse_version('3.0.0'):
        by_request = bill_dict['sponsors']['item'][0]['isByRequest'] == 'Y'
    else:
        by_request = bill_dict['sponsors']['item'][0]['byRequestType'] is not None

    billCommittees = bill_dict.get('committees')
    if schema_version < parse_version('3.0.0'):
        billCommittees = (billCommittees or {})['billCommittees']

    if schema_version >= parse_version('3.0.0'):
        legislativeSubjects = bill_dict.get('subjects', {}).get('legislativeSubjects')
    else:
        legislativeSubjects = bill_dict['subjects']['billSubjects']['legislativeSubjects']

    if schema_version >= parse_version('3.0.0'):
        billSummaries = bill_dict.get('summaries', {}).get('summary')
    else:
        billSummaries = bill_dict['summaries']['billSummaries']['item']
    if billSummaries and not isinstance(billSummaries, list): billSummaries = [billSummaries]

    bill_data = {
        'bill_id': bill_id,
        'bill_type': bill_dict.get('type' if schema_version >= parse_version('3.0.0') else 'billType').lower(),
        'number': bill_dict.get('number' if schema_version >= parse_version('3.0.0') else 'billNumber'),
        'congress': bill_dict.get('congress'),

        'url': billstatus_url_for(bill_id),

        'introduced_at': bill_dict.get('introducedDate', ''),
        'by_request': by_request,
        'sponsor': bill_info.sponsor_for(bill_dict['sponsors']['item'][0]),
        'cosponsors': bill_info.cosponsors_for(bill_dict.get('cosponsors')),

        'actions': actions,
        'history': bill_info.history_from_actions(actions),
        'status': status,
        'status_at': status_date,
        'enacted_as': bill_info.slip_law_from(actions),

        'titles': titles,
        'official_title': bill_info.current_title_for(titles, 'official'),
        'short_title': bill_info.current_title_for(titles, 'short'),
        'popular_title': bill_info.current_title_for(titles, 'popular'),

        'summary': bill_info.summary_for(billSummaries),

        # The top term's case has changed with the new bulk data. It's now in
        # Title Case. For backwards compatibility, the top term is run through
        # '.capitalize()' so it matches the old string. TODO: Remove one day?
        'subjects_top_term': _fixup_top_term_case(bill_dict['policyArea']['name']) if bill_dict.get('policyArea') else None,
        'subjects':
            sorted(
                ([_fixup_top_term_case(bill_dict['policyArea']['name'])] if bill_dict.get('policyArea') else []) +
                ([item['name'] for item in legislativeSubjects['item']] if legislativeSubjects else [])
            ),

        'related_bills': bill_info.related_bills_for(bill_dict.get('relatedBills')),
        'committees': bill_info.committees_for(billCommittees),
        'amendments': bill_info.amendments_for(bill_dict.get('amendments')),
        'committee_reports': bill_info.committee_reports_for(bill_dict.get('committeeReports')),

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
    amdt_list = bill_amendments['billStatus']['bill'].get('amendments')
    if amdt_list is None:  # many bills don't have amendments
        return

    for amdt in amdt_list['amendment']:
        amendment_info.process_amendment(amdt, bill_id, options)

def reparse_actions(bill_id, options):
    # Load an existing bill status JSON file.
    data_json_fn = output_for_bill(bill_id, 'json')
    if not os.path.exists(data_json_fn):
        return {
            "ok": True,
            "saved": False,
            "reason": "no file",
        }
    source = utils.read(data_json_fn)
    bill_data = json.loads(source)

    # Munge data.
    from congress.tasks.bill_info import parse_bill_action
    title = bill_info.current_title_for(bill_data['titles'], 'official')
    old_status = "INTRODUCED"
    for action in bill_data['actions']:
      new_action, new_status = parse_bill_action(action, old_status, bill_id, title)
      if new_status:
        old_status = new_status
        action['status'] = new_status
      elif 'status' in action:
        del action['status']
      # clear out deleted keys
      for key in ('vote_type', 'how', 'where', 'result', 'roll', 'suspension', 'calendar', 'under', 'number', 'committee', 'pocket', 'law', 'congress'):
        if key in action and key not in new_action:
          del action[key]
      action.update(new_action)

    status, status_date = bill_info.latest_status(bill_data['actions'], bill_data['introduced_at'])
    bill_data['status'] = status
    bill_data['status_at'] = status_date

    wrote_any = False

    if options.get("diff"):
        confirmer = utils.show_diff_ask_ok
    else:
        # If no --diff is given, just check that
        # the content hasn't changed --- don't bother
        # writing out anything with identical content.
        def confirmer(source, revised, fn):
            return source != revised

    # Write new data.json file.
    revised = json.dumps(bill_data, indent=2, sort_keys=True)
    if confirmer(source, revised, data_json_fn):
      utils.write(revised, data_json_fn)
      wrote_any = True

    # Write new data.xml file.
    from congress.tasks.bill_info import create_govtrack_xml
    data_xml_fn = data_json_fn.replace(".json", ".xml")
    with open(data_xml_fn, 'r') as xml_file:
        source = xml_file.read()
    revised = create_govtrack_xml(bill_data, options)
    if confirmer(source, revised.decode("utf8"), data_xml_fn):
      with open(data_xml_fn, 'wb') as xml_file:
        xml_file.write(revised)
      wrote_any = True

    return {
        "ok": True,
        "saved": wrote_any,
        "reason": "no changes or changes skipped by user",
    }
