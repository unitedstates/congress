## unitedstates/congress

Public domain code that collects data about the bills, amendments, roll call votes, and other core data about the U.S. Congress.

Includes:

* A data importing script for the [official bulk bill status data](https://github.com/usgpo/bill-status) from Congress, the official source of information on the life and times of legislation.

* Scrapers for House and Senate roll call votes.

* A document fetcher for GovInfo.gov, which holds bill text, bill status, and other official documents.

* A defunct THOMAS scraper for presidential nominations in Congress.

Read about the contents and schema in the [documentation](https://github.com/unitedstates/congress/wiki) in the github project wiki.

For background on how this repository came to be, see [Eric's blog post](https://sunlightfoundation.com/blog/2013/08/20/a-modern-approach-to-open-data/).


### Setting Up

This project is tested using Python 2.7.

**System dependencies**

On Ubuntu, you'll need `wget`, `pip`, and some support packages:

```bash
sudo apt-get install git python-dev libxml2-dev libxslt1-dev libz-dev python-pip
```

On OS X, you'll need developer tools installed ([XCode](https://developer.apple.com/xcode/)), and `wget`.

```bash
brew install wget
```

**Python dependencies**

It's recommended you use a `virtualenv` (virtual environment) for development. The easiest way is install `virtualenv` and `virtualenvwrapper`, using `sudo` if necessary:

```bash
sudo pip install virtualenv
sudo pip install virtualenvwrapper
```

Create a virtualenv for this project:

```bash
mkvirtualenv congress
```

And activate it before any development session using:

```bash
workon congress
```

Finally, with your virtual environment activated, install Python packages:

```bash
pip install -r requirements.txt
```

### Collecting the data

The general form to start the scraping process is:

    ./run <data-type> [--force] [other options]

where data-type is one of:

* `bills` (see [Bills](https://github.com/unitedstates/congress/wiki/bills)) and [Amendments](https://github.com/unitedstates/congress/wiki/amendments))
* `votes` (see [Votes](https://github.com/unitedstates/congress/wiki/votes))
* `nominations` (see [Nominations](https://github.com/unitedstates/congress/wiki/nominations))
* `committee_meetings` (see [Committee Meetings](https://github.com/unitedstates/congress/wiki/committee-meetings))
* `govinfo` (see [Bill Text](https://github.com/unitedstates/congress/wiki/bill-text))
* `statutes` (see [Bills](https://github.com/unitedstates/congress/wiki/bills) and [Bill Text](https://github.com/unitedstates/congress/wiki/bill-text))

To get data for bills, resolutions, and amendments, run:

```bash
./run govinfo --bulkdata=BILLSTATUS
./run bills
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

### Who's Using This Data

The [Sunlight Foundation](https://sunlightfoundation.com) and [GovTrack.us](https://www.govtrack.us) are the two principal maintainers of this project.

Both Sunlight and GovTrack operate APIs where you can get much of this data delivered over HTTP:

* [GovTrack.us API](https://www.govtrack.us/developers/api)
* [Sunlight Congress API](https://sunlightlabs.github.io/congress/)

## Public domain

This project is [dedicated to the public domain](LICENSE). As spelled out in [CONTRIBUTING](CONTRIBUTING.md):

> The project is in the public domain within the United States, and copyright and related rights in the work worldwide are waived through the [CC0 1.0 Universal public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).

> All contributions to this project will be released under the CC0 dedication. By submitting a pull request, you are agreeing to comply with this waiver of copyright interest.

[![Build Status](https://travis-ci.org/unitedstates/congress.svg?branch=master)](https://travis-ci.org/unitedstates/congress)
