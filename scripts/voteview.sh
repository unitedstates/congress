export UPDATE_CONGRESS_LEGISLATORS=NO
for congress in {1..100}; do
	./run voteview --congress=$congress --govtrack $@
done
./run voteview --govtrack --congress=101 --session=1989 --chamber=h $@

