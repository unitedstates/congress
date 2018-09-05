#!/bin/sh
# Refresh the bulk data collection.
./run govinfo --bulkdata=BILLSTATUS

# Turn into JSON and GovTrack-XML.
./run bills --govtrack $@
