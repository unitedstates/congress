#!/bin/sh
# Refresh the bulk data collection.
./run fdsys --collection-type=bulk-data --collections=BILLSTATUS

# Turn into JSON and GovTrack-XML.
./run bills --govtrack $@
