# Needs to match
# two words, begining of paragraph, followed by period
# Chairman, Chairwoman, Mr. Mrs. Ms. Ms. Mrs. Mr. Dr., Senator, General,
# The Chairman., The CHAIRWOMAN.
#  
# Mr. Garcia of Illinois.
# What if the person has two last names?

# there is a section at the top with those present

# some prepared statements start with the person's name, some dont
# prepared statement by senator james inhofe
# [The prepared statement of Mr. Smith follows:]
# Prepared Statement by Brad Smith


class hearing_parser():
    def __init__(self, collection, soup):
        self.id = collection.get('packageId')
        self.title = collection.get('title')
        self.soup = soup
        self.save_to_file()
        self.parse_hearing()

    def save_to_file(self):
        with open(f"hearings/{self.id}.html", "w") as file:
            file.write(str(self.soup))

    def parse_hearing(self):
        print(self.soup.text[:50])

