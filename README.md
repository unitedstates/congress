Congress
========

Public domain code that collects data about the bills, amendments, roll call votes, and other core data about the U.S. Congress.

Includes:

* A scraper for THOMAS.gov, the official source of information on the life and times of legislation in Congress.

* Scrapers for House and Senate roll call votes.

* A scraper for GPO FDSys, the official repository for most legislative documents.

Read about the [contents and schema](https://github.com/unitedstates/congress/wiki).


Setting Up
----------

It's recommended you first create and activate a virtualenv with:

    virtualenv virt
    source virt/bin/activate

You don't have to call it "virt", but the project's gitignore is set up to ignore it already if you do.

Whether or not you use virtualenv:

    pip install -r requirements.txt

Collecting the data
-------------------

The general form to start the scraping process is:

    ./run <data-type> [--force] [--fast] [other options]
    
where data-type is one of:

    * bills
    * amendments
    * votes
    * fdsys

To scrape bills and resolutions from THOMAS run:

    ./run bills

The bills script will output bulk data into a top-level `data` directory, then organized by Congress number, bill type, and bill number. Two data output files will be generated for each bill: a JSON version (data.json) and an XML version (data.xml).

Scraping bills
--------------

You can supply a few kinds of flags when scraping bills and resolutions. To limit it to 10 House simple resolutions in the 111th Congress:

    ./run bills --limit=10 --bill_type=hres --congress=111

To get only a specific bill, pass in the ID for that bill. For example, S. 968 in the 112th congress:

    ./run bills --bill_id=s968-112

Scraping amendments
-------------------

You can supply a few kinds of flags when scraping amendments, similar to the options for bills. To limit to 10 House amendments in the 111th Congress:

    ./run amendments --limit=10 --amendment_type=hamdt --congress=111

To get only a specific amendment:

    ./run amendments --amendment_id=samdt5-112

Scraping votes
--------------

Similar commands are available for roll call votes. Start with:

    ./run votes
    
You can supply a few kinds of flags, such as limit and congress as above. Votes are grouped by the Senate and House into two sessions per Congress, which (in modern times) roughly follow the calendar years. Senate votes are numbered uniquely by session. House vote numbering continues consecutively throughout the Congress. To get votes from 2012, run:

    ./run votes --congress=112 --session=2012
    
To get only a specific vote, pass in the ID for the vote. For the Senate vote 50 in the 2nd session of the 112th Congress:

    ./run votes --vote_id=s50-112.2012

Scraping GPO FDSys and Bill Text
--------------------------------

The scraper for GPO FDSys provides infrastructure for other tasks, such as fetching bill text. FDSys is organized by collection (bills, committee reports, etc.) and year. 

To download all bill text, run:

	./run fdsys --collections=BILLS --congress=112 --store=pdf,mods,xml,text
	
Bill text is stored in a text-versions directory within each bill directory, e.g.:

	data/112/bills/hr/hr68/text-versions/ih/document.pdf
	data/112/bills/hr/hr68/text-versions/ih/mods.xml
	data/112/bills/hr/hr68/text-versions/ih/document.xml
	data/112/bills/hr/hr68/text-versions/ih/document.html (original HTML wrapper around plain text)
	data/112/bills/hr/hr68/text-versions/ih/document.txt (UTF-8 encoded)
	
The subdirectory name indicates the bill text version code assigned by GPO (ih, enr, etc.). The mods.xml file has metadata from GPO.

Running the command again will smartly update changed files by scanning through FDSys's sitemaps.

A separate task called bill_versions will extract some common metadata into handy JSON (using the same status codes as above).

	./run bill_versions --congress=112
	data/112/bills/hjres/hjres6/text-versions/ih.json

Use this JSON file to determine which is the most recent text version if you want to find the most recent text of a bill.

Back on the fdsys scraper, the stored files for other collections (besides bills) are organized in a more generic way: in data/fdsys/COLLECTION/YEAR/PKGID. The PKGID is the package identifier for the file on FDSys. For instance:

	./run fdsys --collections=STATUTE --year=1982 --store=mods
	data/fdsys/STATUTE/1982/STATUTE-96/mods.xml

The collections argument can take a comma-separated list of collections. To get a list of collection names, use:

	./run fdsys --list-collections
	
All arguments are optional. Without --store, the script just updates a local copy of the sitemap files in cache/fdsys/sitemap/YEAR/COLLECTION.xml. Use --cached to force the use of cached files and not hit the network. Use --force to download all files anew.
   
Options
-------

The script will cache all downloaded pages, and it will not re-fetch them from the network unless a force flag is passed:

    ./run bills --force

The --force flag applies to all data types. If you are trying to automatically sync bill information on an ongoing basis, it's recommended to do this only once or twice a day, as THOMAS is not updated in real time, and most information is delayed by a day.

Since the --force flag forces a download and parse of every object, the --fast flag will attempt to process only objects that are believed to have changed. Always use --fast with --force.

    ./run bills --force --fast

For bills and amendments, the --fast flag will only download bills that appear to have new activity based on whether the bill's search result listing on pages like http://thomas.loc.gov/cgi-bin/bdquery/d?d113:0:./list/bss/d113HR.lst: have changed. This doesn't detect all changes to a bill, but it results in a much faster scrape by not having to fetch the pages for every bill.

For votes, the --fast flag will have the scraper download only votes taken in the last three days, which is the time during which most vote changes and corrections are posted.
    
Debugging messages are hidden by default. To include them, run with --log=info or --debug. To hide even warnings, run with --log=error.

To get emailed with errors, copy config.yml.example to config.yml and fill in the SMTP options. The script will automatically use the details when a parsing or execution error occurs.


Data Output
-----------

The script will cache downloaded pages in a top-level `cache` directory, and output bulk data in a top-level `data` directory.

Two bulk data output files will be generated for each object: a JSON version (data.json) and an XML version (data.xml). The XML version attempts to maintain backwards compatibility with the XML bulk data that [GovTrack.us](http://govtrack.us) has provided for years. Add the --govtrack flag to get fully backward-compatible output using GovTrack IDs (otherwise the source IDs used for legislators is used).

See the project wiki for documentation on the output format.

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

* Treaties - everything (may wait until they are in Congress.gov)
* Nominations - everything (may wait until they are in Congress.gov)

As [Congress.gov](http://beta.congress.gov) starts reaching [data parity](http://beta.congress.gov/help/coverage-dates/) with THOMAS.gov, the scraper will be gradually converted to get different pieces of information from Congress.gov instead of THOMAS.gov, which will be shut down after Congress.gov's 1-year beta period.


Contributors
-----

* [Eric Mill](http://github.com/konklone) - [Sunlight Foundation](http://sunlightfoundation.com)
* [Josh Tauberer](http://github.com/tauberer) - [GovTrack.us](http://govtrack.us)
* [Derek Willis](http://github.com/dwillis)
* [Alex Engler](http://github.com/AlexEngler)

Who's Using This Data
---------------------

Here are the ones we know about:

* [GovTrack.us](http://govtrack.us) 
* [Sunlight Congress API](http://sunlightlabs.github.com/congress/)
* [Scout](https://scout.sunlightfoundation.com/)
