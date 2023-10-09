## unitedstates/congress

This is a community-run project to develop Python tools to collect data about the bills, amendments, roll call votes, and other core data about the U.S. Congress into simple-to-use structured data files.

The repository is a part of [BillML](https://github.com/dreamproit/BillML) project and full functionality of original repo might not be available.

The tools include:

* Downloading the [official bulk bill status data](https://github.com/usgpo/bill-status) from Congress, the official source of information on the life and times of legislation, and converting the data to an easier-to-use format.

* Scrapers for House and Senate roll call votes.

* A document fetcher for GovInfo.gov, which holds bill text, bill status, and other official documents, and which downloads only newly updated files.

* A defunct THOMAS scraper for presidential nominations in Congress.

Read about the contents and schema in the [documentation](https://github.com/unitedstates/congress/wiki) in the github project wiki.

This repository was originally developed by [GovTrack.us](https://www.govtrack.us) and the Sunlight Foundation in 2013 (see [Eric's blog post](https://sunlightfoundation.com/blog/2013/08/20/a-modern-approach-to-open-data/)) and is currently maintained by GovTrack.us and other contributors. For more information about data in Congress, see the [Congressional Data Coalition](https://congressionaldata.org/).


### Setting Up

This project is tested using Python 3.

**System dependencies**

On Ubuntu, you'll need `wget`, `pip`, and some support packages:

```bash
sudo apt-get install git python3-dev libxml2-dev libxslt1-dev libz-dev python3-pip python3-venv
```

On OS X, you'll need developer tools installed ([XCode](https://developer.apple.com/xcode/)), and `wget`.

```bash
brew install wget
```

**Python dependencies**

It's recommended you use a `virtualenv` (virtual environment) for development. Create a virtualenv for this project:

```bash
python3 -m venv env
source env/bin/activate
```
Finally, with your virtual environment activated, install the package, which
will automatically pull in the Python dependencies:

```bash
pip install .
```

### Collecting the data

The general form to start the scraping process is:

    usc-run <data-type> [--force] [other options]

where data-type is one of:

* `bills` (see [Bills](https://github.com/unitedstates/congress/wiki/bills)) and [Amendments](https://github.com/unitedstates/congress/wiki/amendments))
* `votes` (see [Votes](https://github.com/unitedstates/congress/wiki/votes))
* `nominations` (see [Nominations](https://github.com/unitedstates/congress/wiki/nominations))
* `committee_meetings` (see [Committee Meetings](https://github.com/unitedstates/congress/wiki/committee-meetings))
* `govinfo` (see [Bill Text](https://github.com/unitedstates/congress/wiki/bill-text))
* `statutes` (see [Bills](https://github.com/unitedstates/congress/wiki/bills) and [Bill Text](https://github.com/unitedstates/congress/wiki/bill-text))

To get data for bills, resolutions, and amendments, run:

```bash
usc-run govinfo --bulkdata=BILLSTATUS
usc-run bills
```

The bills script will output bulk data into a top-level `data` directory, then organized by Congress number, bill type, and bill number. Two data output files will be generated for each bill: a JSON version (data.json) and an XML version (data.xml).

### Common options

Debugging messages are hidden by default. To include them, run with --log=info or --debug. To hide even warnings, run with --log=error.

To get emailed with errors, copy config.yml.example to config.yml and fill in the SMTP options. The script will automatically use the details when a parsing or execution error occurs.

The --force flag applies to all data types and supresses use of a cache for network-retreived resources.

### Data Output

The script will cache downloaded pages in a top-level `cache` directory, and output bulk data in a top-level `data` directory.

Two bulk data output files will be generated for each object: a JSON version (data.json) and an XML version (data.xml). The XML version attempts to maintain backwards compatibility with the XML bulk data that [GovTrack.us](https://www.govtrack.us) has provided for years. Add the --govtrack flag to get fully backward-compatible output using GovTrack IDs (otherwise the source IDs used for legislators is used).

See the [project wiki](https://github.com/unitedstates/congress/wiki) for documentation on the output format.

### Contributing

Pull requests with patches are awesome. Unit tests are strongly encouraged ([example tests](https://github.com/unitedstates/congress/blob/master/test/test_bill_actions.py)).

The best way to file a bug is to [open a ticket](https://github.com/unitedstates/congress/issues).


### Running tests

To run this project's unit tests:

```bash
./test/run
```

## Public domain

This project is [dedicated to the public domain](LICENSE). As spelled out in [CONTRIBUTING](CONTRIBUTING.md):

> The project is in the public domain within the United States, and copyright and related rights in the work worldwide are waived through the [CC0 1.0 Universal public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).

> All contributions to this project will be released under the CC0 dedication. By submitting a pull request, you are agreeing to comply with this waiver of copyright interest.

[![Build Status](https://travis-ci.org/unitedstates/congress.svg?branch=master)](https://travis-ci.org/unitedstates/congress)
