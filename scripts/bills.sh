#!/bin/sh
# Refresh the bulk data collection.
usc-run govinfo --bulkdata=BILLSTATUS

# Turn into JSON and GovTrack-XML.
usc-run bills --govtrack $@
