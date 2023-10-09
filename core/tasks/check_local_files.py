import requests
from utils import getBillParts
from lxml import etree
import re
from collections import defaultdict
import json
import pathlib
import click
from govinfo import mirror_package, mirror_bulkdata_file
from bills import process_bill
# globals
GOVINFO_BASE_URL = "https://www.govinfo.gov/"
COLLECTION_BASE_URL = GOVINFO_BASE_URL + "app/details/"
BULKDATA_BASE_URL = GOVINFO_BASE_URL + "bulkdata/"
COLLECTION_SITEMAPINDEX_PATTERN = GOVINFO_BASE_URL + "sitemap/{collection}_sitemap_index.xml"
BULKDATA_SITEMAPINDEX_PATTERN = GOVINFO_BASE_URL + "sitemap/bulkdata/{collection}/sitemapindex.xml"
FDSYS_BILLSTATUS_FILENAME = "fdsys_billstatus.xml"

ns = {"x": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def get_sitemap_index(collection):

    response = requests.get(BULKDATA_SITEMAPINDEX_PATTERN.format(collection=collection))
    body = response.text
    body = body.encode("utf8")
    try:
        sitemap = etree.fromstring(body)
    except etree.XMLSyntaxError as e:
        raise Exception("XML syntax error in %s: %s" % (response.url, str(e)))
    sitemap_index_items = []
    # Process the entries.
    if sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}sitemapindex":

        # This is a sitemap index. Process the sitemaps listed in this
        # sitemapindex recursively.
        nodes = sitemap.xpath("x:sitemap", namespaces=ns)
        for node in nodes:
            # Get URL and lastmod date of the sitemap.
            url = str(node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(node.xpath("string(x:lastmod)", namespaces=ns))
            node_item = {
                'url': url,
                'lastmod': lastmod,
            }
            sitemap_index_items.append(node_item)
    return sitemap_index_items


def get_bill_status_urls_per_type(sitemap_item: dict):

    response = requests.get(sitemap_item['url'])
    body = response.text
    body = body.encode("utf8")
    try:
        sitemap = etree.fromstring(body)
    except etree.XMLSyntaxError as e:
        raise Exception("XML syntax error in %s: %s" % (response.url, str(e)))

    sitemap_items = {'congress': None, 'billstatuses': [], 'billtype': None, 'total': None}

    if sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":

        nodes = sitemap.xpath("x:url", namespaces=ns)
        for node in nodes:
            url = str(node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(node.xpath("string(x:lastmod)", namespaces=ns))

            # This is a bulk data item. Extract components of the URL.
            m = re.match(BULKDATA_BASE_URL + r"([^/]+)/(.*)", url)
            if not m:
                raise Exception("Unmatched bulk data file URL (%s) at %s.")
            collection = m.group(1)
            item_path = m.group(2)
            local_file_path_template = '{congress}/bills/{billtype}/{billtype}{billnum}/fdsys_billstatus.xml'
            bill_parts = getBillParts(item_path.split('/')[-1].split('-')[-1])
            sitemap_item = {
                'url': url,
                'congress': bill_parts['congress'],
                'billtype': bill_parts['billtype'],
                'billnumber': bill_parts['billnum'],
                'collection': collection,
                'lastmod': lastmod,
                'item_path': item_path,
                'local_filepath': local_file_path_template.format(**bill_parts)
            }
            sitemap_items['congress'] = bill_parts['congress']
            sitemap_items['billstatuses'].append(sitemap_item)
            sitemap_items['billtype'] = bill_parts['billtype']
            sitemap_items['total'] = len(nodes)
            sitemap_items['url'] = response.url
    return sitemap_items


def get_bills_per_type(sitemap_item: dict):
    response = requests.get(sitemap_item['url'])
    body = response.text
    body = body.encode("utf8")
    try:
        sitemap = etree.fromstring(body)
    except etree.XMLSyntaxError as e:
        raise Exception("XML syntax error in %s: %s" % (response.url, str(e)))

    sitemap_items = {'congress': None, 'bills': [], 'billtype': None, 'total': None}

    if sitemap.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
        nodes = sitemap.xpath("x:url", namespaces=ns)
        for node in nodes:
            url = str(node.xpath("string(x:loc)", namespaces=ns))
            lastmod = str(node.xpath("string(x:lastmod)", namespaces=ns))

            # This is a bulk data item. Extract components of the URL.
            m = re.match(BULKDATA_BASE_URL + r"([^/]+)/(.*)", url)
            if not m:
                raise Exception("Unmatched bulk data file URL (%s) at %s.")
            collection = m.group(1)
            item_path = m.group(2)
            local_file_path_template = '{congress}/bills/{billtype}/{billtype}{billnum}/text-versions/{billversion}/document.xml'
            bill_parts = getBillParts(item_path.split('/')[-1].split('-')[-1])
            sitemap_item = {
                'url': url,
                'congress': bill_parts['congress'],
                'billtype': bill_parts['billtype'],
                'billnumber': bill_parts['billnum'],
                'billversion': bill_parts['billversion'],
                'collection': collection,
                'lastmod': lastmod,
                'item_path': item_path,
                'local_filepath': local_file_path_template.format(**bill_parts)
            }
            sitemap_items['congress'] = bill_parts['congress']
            sitemap_items['bills'].append(sitemap_item)
            sitemap_items['billtype'] = bill_parts['billtype']
            sitemap_items['total'] = len(nodes)
            sitemap_items['url'] = response.url
    return sitemap_items


def get_billstatuses_info():
    sitemap_index_items = get_sitemap_index("BILLSTATUS")
    per_congress_bill_status_urls = defaultdict(dict)
    for i in sitemap_index_items:
        result = get_bill_status_urls_per_type(i)
        per_congress_bill_status_urls[result['congress']][result['billtype']] = result
    for congress_num, per_bill_type_stats in per_congress_bill_status_urls.items():
        total_per_congress = 0
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            total_per_congress += bill_type_stats['total']
        per_congress_bill_status_urls[congress_num]['total'] = total_per_congress

    return per_congress_bill_status_urls


def get_bills_info():
    sitemap_index_items = get_sitemap_index("BILLS")
    per_congress_bills_urls = defaultdict(dict)
    for i in sitemap_index_items:
        result = get_bills_per_type(i)
        per_congress_bills_urls[result['congress']][result['billtype']] = result
    for congress_num, per_bill_type_stats in per_congress_bills_urls.items():
        total_per_congress = 0
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            total_per_congress += bill_type_stats['total']
        per_congress_bills_urls[congress_num]['total'] = total_per_congress
    return per_congress_bills_urls


def save_info_file(filename: str, data: dict):
    import json
    with open(filename, 'w') as outfile:
        json.dump(data, outfile)


def save_bill_statuses_info():
    bill_statuses_info = get_billstatuses_info()
    save_info_file('bill_statuses_info.json', bill_statuses_info)


def save_bills_info():
    bills_info = get_bills_info()
    save_info_file('bills_info.json', bills_info)


def read_info_file(filename: str):
    if not pathlib.Path(filename).exists():
        logger.error(f'File "{filename}" does not exist.')
        return
    with open(filename) as json_file:
        data = json.load(json_file)
    return data


def check_file_system_for_missing_bill_statuses(bill_statuses_info: dict):
    local_prefix = '/bills_data/data'
    missing_bill_statuses = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for congress_num, per_bill_type_stats in bill_statuses_info.items():
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if bill_type == 'total':
                missing_bill_statuses[congress_num]['total'] = bill_type_stats
                continue
            for bill_status in bill_type_stats['billstatuses']:
                local_filepath = pathlib.Path(f'{local_prefix}/{bill_status["local_filepath"]}')
                if not local_filepath.exists():
                    missing_bill_statuses[bill_status['congress']][bill_status['billtype']]['billstatuses'].append(bill_status)
    for congress_num, per_bill_type_stats in missing_bill_statuses.items():
        total_per_congress = 0
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if bill_type == 'total':
                continue
            total_per_congress += len(bill_type_stats['billstatuses'])
        missing_bill_statuses[congress_num]['total_missing'] = total_per_congress
    return missing_bill_statuses


def check_file_system_for_missing_bill_statuses_data_json_files(bill_statuses_info: dict):
    local_prefix = '/bills_data/data'
    missing_bill_statuses = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for congress_num, per_bill_type_stats in bill_statuses_info.items():
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if bill_type == 'total':
                missing_bill_statuses[congress_num]['total'] = bill_type_stats
                continue
            for bill_status in bill_type_stats['billstatuses']:
                data_json_filepath = bill_status["local_filepath"].replace('fdsys_billstatus.xml', 'data.json')
                local_filepath = pathlib.Path(f'{local_prefix}/{data_json_filepath}')
                if not local_filepath.exists():
                    missing_bill_statuses[bill_status['congress']][bill_status['billtype']]['billstatuses'].append(bill_status)
    for congress_num, per_bill_type_stats in missing_bill_statuses.items():
        total_per_congress = 0
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if bill_type == 'total':
                continue
            total_per_congress += len(bill_type_stats['billstatuses'])
        missing_bill_statuses[congress_num]['total_missing'] = total_per_congress
    return missing_bill_statuses


def check_file_system_for_missing_bills(bills_info: dict):
    local_prefix = '/bills_data/data'
    missing_bills = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for congress_num, per_bill_type_stats in bills_info.items():
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if bill_type == 'total':
                missing_bills[congress_num]['total'] = bill_type_stats
                continue
            for bill in bill_type_stats['bills']:
                local_filepath = pathlib.Path(f'{local_prefix}/{bill["local_filepath"]}')
                if not local_filepath.exists():
                    missing_bills[bill['congress']][bill['billtype']]['bills'].append(bill)
    for congress_num, per_bill_type_stats in missing_bills.items():
        total_per_congress = 0
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if bill_type == 'total':
                continue
            total_per_congress += len(bill_type_stats['bills'])
        missing_bills[congress_num]['total_missing'] = total_per_congress
    return missing_bills


def download_bills(data: dict):
    downloaded_bills = []
    for congress_num, per_bill_type_stats in data.items():
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if isinstance(bill_type_stats, int):
                continue
            missing_bills = bill_type_stats['bills']
            for bill in missing_bills:
                bill_id = f'{bill["congress"]}{bill["billtype"]}{bill["billnumber"]}{bill["billversion"]}'
                collection = 'BILLS'
                lastmod = bill['lastmod']
                lastmod_cache = {}
                options = {'collections': 'BILLS', 'extract': 'xml,pdf', 'force': True}
                downloaded_package_info = mirror_package(
                    collection=collection,
                    package_name=bill_id,
                    lastmod=lastmod,
                    lastmod_cache=lastmod_cache,
                    options=options,
                )
                if not downloaded_package_info:
                    logger.error(f'Failed to download bill: "{bill_id}".')
                    continue
                downloaded_bills.extend(downloaded_package_info)
    return downloaded_bills


def download_bill_statuses(data: dict):
    downloaded_bill_statuses = []
    for congress_num, per_bill_type_stats in data.items():
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if isinstance(bill_type_stats, int):
                continue
            missing_bill_statuses = bill_type_stats['billstatuses']
            for bill_status in missing_bill_statuses:
                bill_id = f'{bill_status["congress"]}{bill_status["billtype"]}{bill_status["billnumber"]}'
                collection = 'BILLSTATUS'
                lastmod = bill_status['lastmod']
                # lastmod_cache = {}
                options = {'collections': 'BILLSTATUS', 'force': True}
                downloaded_package_info = mirror_bulkdata_file(
                    collection=collection,
                    url=bill_status['url'],
                    item_path=bill_status['item_path'],
                    lastmod=lastmod,
                    options=options,
                )
                # collection, url, item_path, lastmod, options
                # ['BILLSTATUS', 'https://www.govinfo.gov/bulkdata/BILLSTATUS/113/s/BILLSTATUS-113s1422.xml', '113/s/BILLSTATUS-113s1422.xml', '2023-04-11T04:36:01.310Z', {'bulkdata': 'BILLSTATUS'}]
                if not downloaded_package_info:
                    logger.error(f'Failed to download bill status: "{bill_id}".')
                    continue
                downloaded_bill_statuses.extend(downloaded_package_info)
    return downloaded_bill_statuses


def create_bill_statuses_json_files(data: json):
    created_bill_statuses_data_json_files = []
    for congress_num, per_bill_type_stats in data.items():
        for bill_type, bill_type_stats in per_bill_type_stats.items():
            if isinstance(bill_type_stats, int):
                continue
            missing_bill_statuses = bill_type_stats['billstatuses']
            for bill_status in missing_bill_statuses:
                bill_id = f'{bill_status["billtype"]}{bill_status["billnumber"]}-{bill_status["congress"]}'
                options = {'collections': 'BILLS'}
                status = process_bill(
                    bill_id=bill_id,
                    options=options,
                )
                if not status:
                    logger.error(f'Failed to create bill status data.json file: "{bill_id}".')
                    continue
                if status['saved']:
                    created_bill_statuses_data_json_files.append(bill_status['url'])
    return created_bill_statuses_data_json_files


@click.command()
@click.option(
    '-sbs',
    '--skip-save-bill-statuses-info',
    'skip_save_bill_statuses_info',
    required=False,
    default=False,
    is_flag=True,
    help='Boolean flag to skip saving bill statuses info .json file.',
)
@click.option(
    '-sb',
    '--skip-save-bills-info',
    'skip_save_bills_info',
    required=False,
    default=False,
    is_flag=True,
    help='Boolean flag to skip saving bills info .json file.',
)
@click.option(
    '-ssbsi',
    '--skip-show-bill-statuses-info',
    'skip_show_bill_statuses_info',
    required=False,
    default=False,
    is_flag=True,
    help='Boolean flag to skip showing bill statuses info from .json file.',
)
@click.option(
    '-ssbi',
    '--skip-show-bills-info',
    'skip_show_bills_info',
    required=False,
    default=False,
    is_flag=True,
    help='Boolean flag to skip showing bills info from .json file.',
)
@click.option(
    '-sdmbs',
    '--skip-download-missing-bill-statuses',
    'skip_download_missing_bill_statuses',
    required=False,
    default=False,
    is_flag=True,
    help='Boolean flag to skip re downloading missing bill statuses from .json file.',
)
@click.option(
    '-sdmsb',
    '--skip-download-missing-bills',
    'skip_download_missing_bills',
    required=False,
    default=False,
    is_flag=True,
    help='Boolean flag to skip downloading missing bills from .json file.',
)
def main(
    skip_save_bill_statuses_info: bool,
    skip_save_bills_info: bool,
    skip_show_bill_statuses_info: bool,
    skip_show_bills_info: bool,
    skip_download_missing_bill_statuses: bool,
    skip_download_missing_bills: bool,
) -> None:
    logger.info('Starting checking local file system for missing bill data.')

    if skip_save_bill_statuses_info:
        logger.info('Skipping bill statuses info .json file creation.')
    else:
        logger.info('Saving bill statuses info .json file.')
        save_bill_statuses_info()

    if skip_save_bills_info:
        logger.info('Skipping bills info .json file creation.')
    else:
        logger.info('Saving bills info .json file.')
        save_bills_info()

    if skip_show_bill_statuses_info:
        logger.info('Skipping showing bill statuses info from .json file.')
    else:
        logger.info('Showing bill statuses info from .json file.')
        bill_statuses_info = read_info_file('bill_statuses_info.json')
        if not bill_statuses_info:
            logger.warning(
                'No bill statuses info .json file found, try running the script without "--skip-save-bill-statuses-info" flag to save .json file.'
            )
            return
        total_bill_statuses_across_congresses = sum({k: v['total'] for k, v in bill_statuses_info.items()}.values())
        logger.info(f'bill_statuses_info.json have total: "{total_bill_statuses_across_congresses}" bill statuses.')
        missing_bill_statuses = check_file_system_for_missing_bill_statuses(bill_statuses_info)

        total_missing_bill_statuses_across_congresses = sum({k: v['total_missing'] for k, v in missing_bill_statuses.items()}.values())
        logger.info(f'local file system missing total: "{total_missing_bill_statuses_across_congresses}" bill statuses.')

        for congress_num, per_bill_type_stats in missing_bill_statuses.items():
            logger.info(f'Congress: "{congress_num}" has total: "{per_bill_type_stats["total"]}" bill statuses and missing: "{per_bill_type_stats["total_missing"]}" bill statuses.')

        missing_bill_statuses_data_json_files = check_file_system_for_missing_bill_statuses_data_json_files(bill_statuses_info)
        total_missing_bill_statuses_across_congresses = sum({k: v['total_missing'] for k, v in missing_bill_statuses_data_json_files.items()}.values())
        logger.info(f'local file system missing total: "{total_missing_bill_statuses_across_congresses}" data.json files.')

        for congress_num, per_bill_type_stats in missing_bill_statuses_data_json_files.items():
            logger.info(f'Congress: "{congress_num}" has total: "{per_bill_type_stats["total"]}" bill statuses and missing: "{per_bill_type_stats["total_missing"]}" bill statuses data.json files.')

    if skip_show_bills_info:
        logger.info('Skipping showing bills info from .json file.')
    else:
        bills_info = read_info_file('bills_info.json')
        if not bills_info:
            logger.warning(
                'No bills info .json file found, try running the script without "--skip-save-bills-info" flag to save .json file.'
            )
            return
        total_bills_across_congresses = sum({k: v['total'] for k, v in bills_info.items()}.values())
        logger.info(f'bills_info.json have total: "{total_bills_across_congresses}" bills.')
        missing_bills = check_file_system_for_missing_bills(bills_info)
        for congress_num, per_bill_type_stats in missing_bills.items():
            logger.info(f'Congress: "{congress_num}" has total: "{per_bill_type_stats["total"]}" bills and missing: "{per_bill_type_stats["total_missing"]}" bills.')

    if skip_download_missing_bill_statuses:
        logger.info('Skipping downloading missing bill statuses from .json file.')
    else:
        bill_statuses_info = read_info_file('bill_statuses_info.json')
        if not bill_statuses_info:
            logger.warning(
                'No bill statuses info .json file found, try running the script without "--skip-save-bill-statuses-info" flag to save .json file.'
            )
            return
        missing_bill_statuses = check_file_system_for_missing_bill_statuses(bill_statuses_info)
        downloaded_bill_statuses = download_bill_statuses(missing_bill_statuses)
        for bill_status in downloaded_bill_statuses:
            logger.info(f'Downloaded bill status: "{bill_status}".')

        missing_bill_statuses_data_json_files = check_file_system_for_missing_bill_statuses_data_json_files(
            bill_statuses_info
        )
        created_bill_statuses_data_json_files = create_bill_statuses_json_files(missing_bill_statuses_data_json_files)
        for bill_status in created_bill_statuses_data_json_files:
            logger.info(f'Created bill status data.json files: "{bill_status}".')

    if skip_download_missing_bills:
        logger.info('Skipping downloading missing bills from .json file.')
    else:
        bills_info = read_info_file('bills_info.json')
        if not bills_info:
            logger.warning(
                'No bills info .json file found, try running the script without "--skip-save-bills-info" flag to save .json file.'
            )
            return
        missing_bills = check_file_system_for_missing_bills(bills_info)
        downloaded_bills = download_bills(missing_bills)
        for bill in downloaded_bills:
            logger.info(f'Downloaded bill: "{bill}"')
        logger.info(f'Total missing bills: "{len(missing_bills)}".')
        logger.info(f'Total downloaded bills: "{len(downloaded_bills)}".')


if __name__ == "__main__":

    from congress.utils.logs.log import project_logger as logger

    main()
