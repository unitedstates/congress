#!/bin/sh
# Refresh the bulk data collection.
./run fdsys --bulkdata=True --collections=BILLSTATUS

# Turn into JSON and GovTrack-XML.
./run bills --govtrack $@
