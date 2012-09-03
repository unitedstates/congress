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

  # from hr3630-112
  def test_vote_motion_conference(self):
    bill_type = "hr"
    title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
    state = "PASS_BACK:SENATE"
    line = "On motion that the House disagree to the Senate amendments, and request a conference Agreed to by the Yeas and Nays: 229 - 193 (Roll no. 946)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    # self.assertEqual(new_action['type'], 'vote')
    # self.assertEqual(new_action['vote_type'], 'other')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 'h')
    # self.assertEqual(new_action['result'], 'pass')
    # self.assertEqual(new_action['roll'], "946")
    self.assertEqual(new_state, None)

  # from hr3630-112
  def test_vote_motion_instruct_conferees(self):
    bill_type = "hr"
    title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
    state = "PASS_BACK:SENATE"
    line = "On motion that the House instruct conferees Agreed to by the Yeas and Nays: 397 - 16 (Roll no. 9)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    # self.assertEqual(new_action['type'], 'vote')
    # self.assertEqual(new_action['vote_type'], 'other')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 'h')
    # self.assertEqual(new_action['result'], 'pass')
    # self.assertEqual(new_action['roll'], "9")
    self.assertEqual(new_state, None)

  # from hr3630-112
  def test_vote_conference_report_house_pass(self):
    bill_type = "hr"
    title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
    state = "PASS_BACK:SENATE"
    line = "On agreeing to the conference report Agreed to by the Yeas and Nays: 293 - 132 (Roll no. 72)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    self.assertEqual(new_action['type'], 'vote')
    self.assertEqual(new_action['vote_type'], 'conference')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 'h')
    # self.assertEqual(new_action['result'], 'pass')
    self.assertEqual(new_action['roll'], "72")
    self.assertEqual(new_state, 'CONFERENCE:PASSED:HOUSE')

  # from hr3630-112
  def test_vote_conference_report_senate_pass(self):
    bill_type = "hr"
    title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
    state = "CONFERENCE:PASSED:HOUSE"
    line = "Senate agreed to conference report by Yea-Nay Vote. 60 - 36. Record Vote Number: 22."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)

    self.assertEqual(new_action['type'], 'vote')
    self.assertEqual(new_action['vote_type'], 'conference')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 's')
    # self.assertEqual(new_action['result'], 'pass')
    self.assertEqual(new_action['roll'], "22")
    self.assertEqual(new_state, 'PASSED:BILL')


  # from hjres64-111
  def test_vote_veto_override_fail(self):
    bill_type = "hjres"
    title = "Making further continuing appropriations for fiscal year 2010, and for other purposes."
    state = "PROV_KILL:VETO"
    line = "On passage, the objections of the President to the contrary notwithstanding Failed by the Yeas and Nays: (2/3 required): 143 - 245, 1 Present (Roll no. 2).On passage, the objections of the President to the contrary notwithstanding Failed by the Yeas and Nays: (2/3 required): 143 - 245, 1 Present (Roll no. 2)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "override")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action["result"], "fail")
    # self.assertEqual(new_action["how"], "roll")
    self.assertEqual(new_action["roll"], "2")
    self.assertEqual(new_state, "VETOED:OVERRIDE_FAIL_ORIGINATING:HOUSE")

  # from hr6331-110
  def test_veto_override_success_once(self):
    bill_type = "hr"
    title = "Medicare Improvements for Patients and Providers Act of 2008"
    state = "PROV_KILL:VETO"
    line = "Two-thirds of the Members present having voted in the affirmative the bill is passed, Passed by the Yeas and Nays: (2/3 required): 383 - 41 (Roll no. 491)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "override")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action["result"], "pass")
    # self.assertEqual(new_action["how"], "roll")
    self.assertEqual(new_action["roll"], "491")
    self.assertEqual(new_state, "VETOED:OVERRIDE_PASS_OVER:HOUSE")

  # from hr6331-110
  def test_veto_override_success_twice(self):
    bill_type = "hr"
    title = "Medicare Improvements for Patients and Providers Act of 2008"
    state = "VETOED:OVERRIDE_PASS_OVER:HOUSE"
    line = "Passed Senate over veto by Yea-Nay Vote. 70 - 26. Record Vote Number: 177."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "override")
    # self.assertEqual(new_action['where'], "s")
    # self.assertEqual(new_action["result"], "pass")
    # self.assertEqual(new_action["how"], "roll")
    self.assertEqual(new_action["roll"], "177")
    # self.assertEqual(new_state, "VETOED:OVERRIDE_COMPLETE:SENATE")

  # Fictional bill, no constitutional amendment passed by both Houses 
  # in the THOMAS era (1973-present).
  # The 26th was passed by Congress in 1971, 27th passed by Congress in 1789.
  # The line here is taken from hjres10-109, when the House passed a 
  # flag burning amendment. (A separate version later failed the Senate by one vote.)
  def test_passed_constitutional_amendment(self):
    bill_type = "sjres"
    title = "Proposing an amendment to the Constitution of the United States authorizing the Congress to prohibit the physical desecration of the flag of the United States."
    state = "PASS_OVER:SENATE"
    line = "On passage Passed by the Yeas and Nays: (2/3 required): 286 - 130 (Roll no. 296)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote2")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action["result"], "pass")
    # self.assertEqual(new_action["how"], "roll")
    self.assertEqual(new_action["roll"], "296")
    self.assertEqual(new_state, "PASSED:CONSTAMEND")
  