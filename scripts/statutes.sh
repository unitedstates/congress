#!/bin/sh
usc-run govinfo --collections=STATUTE --extract=mods,pdf
usc-run statutes --volumes=65-86 --govtrack # bill status
usc-run statutes --volumes=65-106 --textversions --extracttext # bill text
