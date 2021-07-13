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
python3 -m venv congress
source congress/bin/activate
```
Finally, with your virtual environment activated, install Python packages:

```bash
pip3 install -r requirements.txt
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

> AppFooter 
> <!--
   The MIT License
   Copyright (c) 2019- Nordic Institute for Interoperability Solutions (NIIS)
   Copyright (c) 2018 Estonian Information System Authority (RIA),
   Nordic Institute for Interoperability Solutions (NIIS), Population Register Centre (VRK)
   Copyright (c) 2015-2017 Estonian Information System Authority (RIA), Population Register Centre (VRK)

   Permission is hereby granted, free of charge, to any person obtaining a copy
   of this software and associated documentation files (the "Software"), to deal
   in the Software without restriction, including without limitation the rights
   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
   copies of the Software, and to permit persons to whom the Software is
   furnished to do so, subject to the following conditions:

   The above copyright notice and this permission notice shall be included in
   all copies or substantial portions of the Software.

   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
   THE SOFTWARE.
 -->
<template>
  <v-footer class="footer">
    <v-container>
      <v-row>
        <v-col cols="6" sm="3" class="pt-6">
          <v-img
            :src="require('../../assets/xroad7_logo.svg')"
            height="35"
            width="132"
            max-height="35"
            max-width="132"
          ></v-img>
        </v-col>
        <v-col cols="3" class="footer-col pt-5">
          <v-row>
            <v-col>
              <span class="footer-title">{{
                $t('footer.software.title')
              }}</span>
            </v-col>
          </v-row>
          <v-row>
            <v-col class="py-0">
              {{ $t('footer.software.versionPrefix') }}&nbsp;
              <span data-test="app-footer-server-version">{{
                securityServerVersion.info || ''
              }}</span>
            </v-col>
          </v-row>
          <v-row>
            <v-col>
              <a
                rel="noopener"
                class="footer-link"
                target="_blank"
                href="https://x-road.global/feedback"
              >
                {{ $t('footer.software.feedback') }}
              </a>
            </v-col>
          </v-row>
        </v-col>
        <v-col class="footer-col pt-5">
          <v-row>
            <v-col>
              <span class="footer-title">{{
                $t('footer.copyright.title')
              }}</span>
            </v-col>
          </v-row>
          <v-row>
            <v-col class="py-0">
              <a
                rel="noopener"
                class="footer-link"
                href="https://niis.org/"
                target="_blank"
              >
                {{ $t('footer.copyright.company') }}
              </a>
            </v-col>
          </v-row>
          <v-row>
            <v-col>
              <a
                rel="noopener"
                class="footer-link"
                href="https://x-road.global/xroad-licence-info"
                target="_blank"
              >
                {{ $t('footer.copyright.licenceInfo') }}
              </a>
            </v-col>
          </v-row>
        </v-col>
      </v-row>
    </v-container>
  </v-footer>
</template>

<script lang="ts">
import Vue from 'vue';
import { mapGetters } from 'vuex';

export default Vue.extend({
  name: 'AppFooter',
  computed: {
    ...mapGetters(['securityServerVersion']),
  },
});
</script>

<style lang="scss" scoped>
@import '../../assets/colors';
$text-color: $XRoad-Black100;

.footer {
  background: $XRoad-WarmGrey30;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.footer-title {
  color: $text-color;
  font-size: 0.9rem;
  font-weight: bold;
}

.footer-col {
  color: $text-color;
  font-size: 0.875rem;
}

.footer-link {
  color: $XRoad-Purple100;
}
</style>
