import unittest
import bill_info

class BillTimeline(unittest.TestCase):

  def test_extract_vote(self):
    state = "INTRODUCED" # ignored
    bill_type = "hr"
    title = "A bill to prevent online threats to economic creativity and theft of intellectual property, and for other purposes."

    line = "On motion to suspend the rules and pass the bill Agreed to by the Yeas and Nays: (2/3 required): 416 - 0 (Roll no. 768)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    
    self.assertEqual(new_action['roll'], "768")
    # self.assertEqual(new_action['how'], "roll")
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote")
    # self.assertEqual(new_action['result'], "pass")

  
  # TODO: these should be run (prefixed with "test_") once the
  # rest of the test suite is filled out and works
  