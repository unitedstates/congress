import unittest
import bill_info

# parsing various kinds of action text to extract metadata and establish state
# vote parsing is handled in test_bill_timeline_votes.py

class BillTimeline(unittest.TestCase):

  # from hjres64-111
  def test_veto(self):
    bill_type = "hjres"
    title = "Making further continuing appropriations for fiscal year 2010, and for other purposes."
    state = "PASSED:BILL"
    line = "Vetoed by President."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vetoed")
    self.assertEqual(new_state, "PROV_KILL:VETO")

  # from hr2415-106
  def test_pocket_veto(self):
    bill_type = "hr"
    title = "United Nations Reform Act of 1999"
    state = "PASSED:BILL"
    line = "Pocket Vetoed by President."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vetoed")
    self.assertEqual(new_action['pocket'], "1")
    self.assertEqual(new_state, "VETOED:POCKET")

  # from s968-112
  def test_reported_from_committee(self):
    bill_type = "s"
    title = "A bill to prevent online threats to economic creativity and theft of intellectual property, and for other purposes."
    state = "REFERRED"
    line = "Committee on the Judiciary. Ordered to be reported with an amendment in the nature of a substitute favorably."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    # self.assertEqual(new_action['type'], 'reported')
    # self.assertEqual(new_action['committee'], "Committee on the Judiciary")
    self.assertEqual(new_state, "REPORTED")

  # from s968-112
  def test_added_to_calendar(self):
    bill_type = "s"
    title = "A bill to prevent online threats to economic creativity and theft of intellectual property, and for other purposes."
    state = "REPORTED"
    line = "Placed on Senate Legislative Calendar under General Orders. Calendar No. 70."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    self.assertEqual(new_action['type'], 'calendar')
    self.assertEqual(new_action['calendar'], "Senate Legislative")
    self.assertEqual(new_action['under'], "General Orders")
    self.assertEqual(new_action['number'], "70")
    self.assertEqual(new_state, None)

  # from hr3590-111
  def test_enacted_as_public_law(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act." # won't matter
    state = "PASSED:BILL" # won't matter
    line = "Became Public Law No: 111-148."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "enacted")
    # self.assertEqual(new_action['number'], "111-148")
    # self.assertEqual(new_action['law_type'], "public")

  # from hr3590-111
  def test_cleared_for_whitehouse(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act." # won't matter
    state = "PASSED:BILL" # won't matter
    line = "Cleared for White House."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)    
    
    # should not be marked as presented to president, since it hasn't been yet
    # self.assertEqual(new_action['type'], 'action')

  # from hr3590-111
  def test_presented_to_president(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act." # won't matter
    state = "PASSED:BILL" # won't matter
    line = "Presented to President."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)    
    self.assertEqual(new_action['type'], 'topresident')

  # from hr3590-111
  def test_signed_by_president(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act." # won't matter
    state = "PASSED:BILL" # won't matter
    line = "Signed by President."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)    
    self.assertEqual(new_action['type'], 'signed')