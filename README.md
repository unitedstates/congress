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

You can supply a few kinds of flags. To limit it to 10 House simple resolutions in the 111th session:

    python runner.py bills limit=10 bill_type=hres session=111

To get only a specific bill, pass in the ID for that bill. For example, S. 968 in the 112th session:

    python runner.py bills bill_id=s968-112

The script will cache all downloaded pages, and will not re-fetch them from the network unless a force flag is passed:

    python runner.py bills bill_id=s968-112 force=True


Bulk Data
---------

The script will cache downloaded pages in a top-level `cache` directory, and output bulk data in a top-level `data` directory.

Two bulk data output files will be generated, a JSON version and an XML version. The XML version attempts to maintain backwards compatibility with the XML bulk data that [GovTrack.us](http://govtrack.us) has provided for years.


TODO
----

Just about everything:

* Complete bill information
* Amendment information
* Name normalization of members of Congress
* Name normalization for Congressional committees and subcommittees
* Some basic unit testing for various situations and corner cases
* Hasn't been yet run over THOMAS' entire contents
* Data quality checks