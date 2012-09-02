import unittest
import bill_info

# vote parsing is tricky enough to deserve its own set of tests

class BillTimelineVotes(unittest.TestCase):

  # from hr3590-111
  def test_vote_normal_roll(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act." # won't matter
    state = "INTRODUCED" # won't matter
    line = "On motion to suspend the rules and pass the bill Agreed to by the Yeas and Nays: (2/3 required): 416 - 0 (Roll no. 768)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    
    self.assertEqual(new_action['roll'], "768")
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action['how'], "roll")
    # self.assertEqual(new_action['result'], "pass")

    self.assertEqual(new_state, "PASS_OVER:HOUSE")

  # from hr3590-111
  def test_vote_normal_roll_second(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act." # won't matter
    state = "PASS_OVER:HOUSE" # won't matter
    line = "Passed Senate with an amendment and an amendment to the Title by Yea-Nay Vote. 60 - 39. Record Vote Number: 396."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    
    self.assertEqual(new_action['roll'], "396")
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote2")
    # self.assertEqual(new_action['where'], "s")
    # self.assertEqual(new_action['how'], "roll")
    # self.assertEqual(new_action['result'], "pass")

    self.assertEqual(new_state, "PASS_BACK:SENATE")

  # from hr3590-111
  def test_vote_roll_pingpong(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASS_BACK:SENATE"
    line = "On motion that the House agree to the Senate amendments Agreed to by recorded vote: 219 - 212 (Roll no. 165)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['roll'], "165")
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "pingpong")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action['how'], "roll")
    # self.assertEqual(new_action['result'], "pass")

  # from hr3590-111
  def test_vote_cloture(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASS_OVER:HOUSE" # should not change
    line = "Cloture on the motion to proceed to the bill invoked in Senate by Yea-Nay Vote. 60 - 39. Record Vote Number: 353."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['roll'], "353")
    self.assertEqual(new_action['type'], "vote-aux")
    self.assertEqual(new_action['vote_type'], "cloture")
    # self.assertEqual(new_action['where'], "s")
    # self.assertEqual(new_action['how'], "roll")
    # self.assertEqual(new_action['result'], "pass")

    self.assertEqual(new_state, None) # unchanged

  # from hr3590-111
  def test_vote_cloture_2(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASS_OVER:HOUSE" # should not change
    line = "Cloture invoked in Senate by Yea-Nay Vote. 60 - 39. Record Vote Number: 395."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
  #   self.assertEqual(new_action['roll'], "395")
  #   self.assertEqual(new_action['type'], "vote-aux")
  #   self.assertEqual(new_action['vote_type'], "cloture")
    # self.assertEqual(new_action['where'], "s")
    # self.assertEqual(new_action['how'], "roll")
    # self.assertEqual(new_action['result'], "pass")

    # self.assertEqual(new_state, None) # unchanged

  # from hr3590-111
  def test_vote_process_voice_senate(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASS_OVER:HOUSE" # should not change
    line = "Motion to proceed to consideration of measure agreed to in Senate by Unanimous Consent."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    # self.assertEqual(new_action['type'], 'vote')
    # self.assertEqual(new_action['vote_type'], 'other')
    # self.assertEqual(new_action['how'], 'Unanimous Consent')
    # self.assertEqual(new_action['where'], 's')
    # self.assertEqual(new_action['result'], 'pass')
    self.assertEqual(new_state, None)

  # from hr3590-111
  def test_vote_commit_roll_failure(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASS_OVER:HOUSE" # should not change
    line = "Motion by Senator McCain to commit to Senate Committee on Finance under the order of 12/2/2009, not having achieved 60 votes in the affirmative, the motion was rejected in Senate by Yea-Nay Vote. 42 - 58. Record Vote Number: 358."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    # self.assertEqual(new_action['type'], 'vote')
    # self.assertEqual(new_action['vote_type'], 'other')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 's')
    # self.assertEqual(new_action['result'], 'fail')
    # self.assertEqual(new_action['roll'], "358")
    self.assertEqual(new_state, None)