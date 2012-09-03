import unittest
import bill_info

# parsing various kinds of action text to extract metadata and establish state
# vote parsing is handled in test_bill_timeline_votes.py

class BillActions(unittest.TestCase):

  # non-voting tests

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
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASSED:BILL"
    line = "Became Public Law No: 111-148."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "enacted")
    # self.assertEqual(new_action['number'], "111-148")
    # self.assertEqual(new_action['law_type'], "public")

  # from hr3590-111
  def test_cleared_for_whitehouse(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASSED:BILL"
    line = "Cleared for White House."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)    
    
    # should not be marked as presented to president, since it hasn't been yet
    # self.assertEqual(new_action['type'], 'action')

  # from hr3590-111
  def test_presented_to_president(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASSED:BILL"
    line = "Presented to President."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)    
    self.assertEqual(new_action['type'], 'topresident')

  # from hr3590-111
  def test_signed_by_president(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASSED:BILL"
    line = "Signed by President."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)    
    self.assertEqual(new_action['type'], 'signed')

  
  # voting tests

  # from hr3590-111
  def test_vote_normal_roll(self):
    bill_type = "hr"
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "INTRODUCED"
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
    title = "An act entitled The Patient Protection and Affordable Care Act."
    state = "PASS_OVER:HOUSE"
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

  # from hconres74-112
  def test_passed_concurrent_resolution(self):
    bill_type = "hconres"
    title = "Providing for a joint session of Congress to receive a message from the President."
    state = "PASS_OVER:HOUSE"
    line = "Received in the Senate, considered, and agreed to without amendment by Unanimous Consent."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote2")
    # self.assertEqual(new_action['where'], "s")
    # self.assertEqual(new_action["result"], "pass")
    # self.assertEqual(new_action["how"], "by Unanimous Consent")
    self.assertEqual(new_state, "PASSED:CONCURRENTRES")

  # from hres9-112
  def test_passed_simple_resolution_house(self):
    bill_type = "hres"
    title = "Instructing certain committees to report legislation replacing the job-killing health care law."
    state = "REPORTED"
    line = "On agreeing to the resolution, as amended Agreed to by the Yeas and Nays: 253 - 175 (Roll no. 16)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action["result"], "pass")
    # self.assertEqual(new_action["how"], "roll")
    self.assertEqual(new_action['roll'], "16")
    self.assertEqual(new_state, "PASSED:SIMPLERES")

  # from sres484-112
  def test_passed_simple_resolution_senate(self):
    bill_type = "sres"
    title = "A resolution designating June 7, 2012, as \"National Hunger Awareness Day\"."
    state = "REPORTED"
    line = "Submitted in the Senate, considered, and agreed to without amendment and with a preamble by Unanimous Consent."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote")
    # self.assertEqual(new_action['where'], "s")
    # self.assertEqual(new_action["result"], "pass")
    # self.assertEqual(new_action["how"], "by Unanimous Consent")
    self.assertEqual(new_state, "PASSED:SIMPLERES")

  # from hr1954-112
  def test_failed_suspension_vote(self):
    bill_type = "hr"
    title = "To implement the President's request to increase the statutory limit on the public debt."
    state = "REFERRED"
    line = "On motion to suspend the rules and pass the bill Failed by the Yeas and Nays: (2/3 required): 97 - 318, 7 Present (Roll no. 379)."

    new_action, new_state = bill_info.parse_bill_action(line, state, bill_type, title)
    self.assertEqual(new_action['type'], "vote")
    self.assertEqual(new_action['vote_type'], "vote")
    # self.assertEqual(new_action['where'], "h")
    # self.assertEqual(new_action["result"], "fail")
    # self.assertEqual(new_action["how"], "roll")
    self.assertEqual(new_action['roll'], "379")
    self.assertEqual(new_state, "PROV_KILL:SUSPENSIONFAILED")