import unittest
import bill_info

class BillTimeline(unittest.TestCase):

  def test_extract_vote(self):
    state = "INTRODUCED" # ignored
    line = "On motion to suspend the rules and pass the bill Agreed to by the Yeas and Nays: (2/3 required): 416 - 0 (Roll no. 768)."
    bill_type = "hr"
    title = "A bill to prevent online threats to economic creativity and theft of intellectual property, and for other purposes."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    
    self.assertEqual(new_action['roll'], "768")