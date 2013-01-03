Congress
========

Public domain code that collects core data about the bills and roll call votes in the U.S. Congress.

Includes:

* A scraper for THOMAS.gov, the official source of information on the life and times of legislation in Congress.

* Scrapers for House and Senate roll call votes.

The resulting bulk data is [hosted on Github](https://github.com/unitedstates/congress/downloads), and is updated nightly. Read about the [contents and schema](https://github.com/unitedstates/congress/wiki).


Collecting the data
-------------------

It's recommended you first create and activate a virtualenv with:

    virtualenv virt
    source virt/bin/activate

You don't have to call it "virt", but the project's gitignore is set up to ignore it already if you do.

Whether or not you use virtualenv:

    pip install -r requirements.txt

To start grabbing bills (and resolutions):

    ./run bills

You can supply a few kinds of flags. To limit it to 10 House simple resolutions in the 111th congress:

    ./run bills --limit=10 --bill_type=hres --congress=111

To get only a specific bill, pass in the ID for that bill. For example, S. 968 in the 112th congress:

    ./run bills --bill_id=s968-112

The script will cache all downloaded pages, and will not re-fetch them from the network unless a force flag is passed:

    ./run bills --force

Similar commands are available for roll call votes. Start with:

    ./run votes
    
You can supply a few kinds of flags, such as limit and congress as above. Votes are grouped by the Senate and House into two sessions per Congress, which (in modern times) roughly follow the calendar years. Senate votes are numbered uniquely by session. House vote numbering continues consecutively throughout the Congress. To get votes from 2012, run:

    ./run votes --congress=112 --session=2
    
To get only a specific vote, pass in the ID for the vote. For the Senate vote 50 in the 2nd session of the 112th Congress:

    ./run votes --vote_id=s50-112.2

The script will cache pages and by default resources won't be fetched from the network if a cache exists. Additionally, files won't be written to disk if the output data hasn't changed. Use --fetch to download pages from the network again, and --force to write out all data files even if data hasn't changed. (--force implies --fetch.)
    
Debugging messages are hidden by default. To include them, run with --log=info or --debug. To hide even warnings, run with --log=error.

Keeping data fresh
-------------------

If you are trying to automatically sync bill information on an ongoing basis, it's recommended to do this only once or twice a day, as THOMAS is not updated in real time, and most information is delayed by a day.

To get emailed with errors, copy config.yml.example to config.yml and fill in the SMTP options. The script will automatically use the details when a parsing or execution error occurs.

Pass the --force flag when syncing, to ensure that the newest data is downloaded.


Data Output
-----------

The script will cache downloaded pages in a top-level `cache` directory, and output bulk data in a top-level `data` directory.

Two bulk data output files will be generated for each object: a JSON version (data.json) and an XML version (data.xml). The XML version attempts to maintain backwards compatibility with the XML bulk data that [GovTrack.us](http://govtrack.us) has provided for years. Add the --govtrack flag to get fully backward-compatible output using GovTrack IDs (otherwise the source IDs used for legislators is used).

See the project wiki for documentation on the output format.

The GovTrack-style output will use thomas_id's for people (sponsors etc.). To use GovTrack IDs, first update the submodule:

	git submodule init
	git submodule update

And then add --govtrack to the ./run command line to turn on GovTrack IDs in output. On first load it will be very slow.


Contributing
------------

Pull requests with patches are awesome. Including unit tests is strongly encouraged ([example tests](https://github.com/unitedstates/congress/blob/master/test/test_bill_actions.py)).

The best way to file a bug is to [open a ticket](https://github.com/unitedstates/congress/issues).


Running tests
-------------

To run this project's unit tests:

    ./test/run


TODO
----

* Bill text - figure out version information from GPO (links to full text)
* Amendments - everything
* Treaties - everything (may wait until they are in Congress.gov)
* Nominations - everything (may wait until they are in Congress.gov)

As [Congress.gov](http://beta.congress.gov) starts reaching [data parity](http://beta.congress.gov/help/coverage-dates/) with THOMAS.gov, the scraper will be gradually converted to get different pieces of information from Congress.gov instead of THOMAS.gov, which will be shut down after Congress.gov's 1-year beta period.


Contributors
-----

* [Eric Mill](http://github.com/konklone) - [Sunlight Foundation](http://sunlightfoundation.com)
* [Josh Tauberer](http://github.com/tauberer) - [GovTrack.us](http://govtrack.us)
* [Derek Willis](http://github.com/dwillis)
* [Alex Engler](http://github.com/AlexEngler)