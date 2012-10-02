Scraping THOMAS.gov
===================

An experimental public domain scraper for the THOMAS legislative information system managed by the Library of Congress.

Currently:

* Fetches and parses HTML for almost all information on bills. (Everything but related committees.)
* Parses the semantics of Congressional action into metadata and vote outcomes.
* Tracks the past and present state of a bill.
* Includes a suite of unit tests for action semantics and state tracking.


Using
-----

It's recommended you first create and activate a virtualenv with:

    virtualenv virt
    source virt/bin/activate

You don't have to call it "virt", but the project's gitignore is set up to ignore it already if you do.

Whether or not you use virtualenv:

    pip install -r requirements.txt

To start grabbing everything:

    ./run bills

You can supply a few kinds of flags. To limit it to 10 House simple resolutions in the 111th congress:

    ./run bills --limit=10 --bill_type=hres --congress=111

To get only a specific bill, pass in the ID for that bill. For example, S. 968 in the 112th congress:

    ./run bills --bill_id=s968-112

The script will cache all downloaded pages, and will not re-fetch them from the network unless a force flag is passed:

    ./run bills --force


Syncing with THOMAS
-------------------

If you are trying to automatically sync bill information on an ongoing basis, it's recommended to do this only once or twice a day, as THOMAS is not updated in real time, and most information is delayed by a day.

To get emailed with errors, copy config.yml.example to config.yml and fill in the SMTP options. The script will automatically use the details when a parsing or execution error occurs.

Pass the --force flag when syncing, to ensure that the newest data is downloaded.


Running Tests
-------------

To run this project's unit tests:

    ./test/run


Bulk Data
---------

The script will cache downloaded pages in a top-level `cache` directory, and output bulk data in a top-level `data` directory.

Two bulk data output files will be generated for each bill: a JSON version (data.json) and an XML version (data.xml). The XML version attempts to maintain backwards compatibility with the XML bulk data that [GovTrack.us](http://govtrack.us) has provided for years.


TODO
----

More data:

* Bills - related committees
* Amendments - everything
* Treaties - everything (may wait until they are in Congress.gov)
* Nominations - everything (may wait until they are in Congress.gov)

And general improvements:

* Hasn't been yet run over THOMAS' entire contents
* Data quality checks
