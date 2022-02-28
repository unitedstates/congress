for congress in {1..100}; do
	usc-run voteview --congress=$congress --govtrack $@

    # After the first run, no need to update legislator info.
    export UPDATE_CONGRESS_LEGISLATORS=NO
done
usc-run voteview --govtrack --congress=101 --session=1989 --chamber=h $@

