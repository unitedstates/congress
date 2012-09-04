Scraping THOMAS.gov
===================

An experimental public domain scraper for the THOMAS legislative information system managed by the Library of Congress.

Currently: fetches some basic information on bills.


Using
-----

It's recommended you first create and activate a virtualenv with:

    virtualenv virt
    source virt/bin/activate

You don't have to call it "virt", but the project's gitignore is set up to ignore it already if you do.

Whether or not you use virtualenv:

    pip install -r requirements.txt

To start grabbing everything:

    python runner.py bills

You can supply a few kinds of flags. To limit it to 10 House simple resolutions in the 111th congress:

    python runner.py bills limit=10 bill_type=hres congress=111

To get only a specific bill, pass in the ID for that bill. For example, S. 968 in the 112th congress:

    python runner.py bills bill_id=s968-112

The script will cache all downloaded pages, and will not re-fetch them from the network unless a force flag is passed:

    python runner.py bills force=True


Running Tests
-------------

To run this project's unit tests:

    python test/runner.py


Bulk Data
---------

The script will cache downloaded pages in a top-level `cache` directory, and output bulk data in a top-level `data` directory.

Two bulk data output files will be generated for each bill: a JSON version (data.json) and an XML version (data.xml). The XML version attempts to maintain backwards compatibility with the XML bulk data that [GovTrack.us](http://govtrack.us) has provided for years.


TODO
----

Just about everything. More data:

* Complete bill information
* Amendment information
* Name normalization of members of Congress
* Name normalization for Congressional committees and subcommittees

And general improvements:

* Some basic unit testing for various situations and corner cases
* Hasn't been yet run over THOMAS' entire contents
* Data quality checks
* Use a proper command line flag parser, and syntax
