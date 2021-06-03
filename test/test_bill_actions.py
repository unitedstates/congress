import unittest
import bill_info

# parsing various kinds of action text to extract metadata and establish state


def parse_bill_action(line, state, bill_id, title):
    return bill_info.parse_bill_action({"text": line}, state, bill_id, title)


class BillActions(unittest.TestCase):

    def test_veto(self):
        bill_id = "hjres64-111"
        title = "Making further continuing appropriations for fiscal year 2010, and for other purposes."
        state = "PASSED:BILL"
        line = "Vetoed by President."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vetoed")
        self.assertEqual(new_state, "PROV_KILL:VETO")

    def test_pocket_veto(self):
        bill_id = "hr2415-106"
        title = "United Nations Reform Act of 1999"
        state = "PASSED:BILL"
        line = "Pocket Vetoed by President."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vetoed")
        self.assertEqual(new_action['pocket'], "1")
        self.assertEqual(new_state, "VETOED:POCKET")

    def test_reported_from_committee(self):
        bill_id = "s968-112"
        title = "A bill to prevent online threats to economic creativity and theft of intellectual property, and for other purposes."
        state = "REFERRED"
        line = "Committee on the Judiciary. Ordered to be reported with an amendment in the nature of a substitute favorably."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], 'calendar')
        # self.assertEqual(new_action['committee'], "Committee on the Judiciary")
        self.assertEqual(new_state, "REPORTED")

    def test_added_to_calendar(self):
        bill_id = "s968-112"
        title = "A bill to prevent online threats to economic creativity and theft of intellectual property, and for other purposes."
        state = "REPORTED"
        line = "Placed on Senate Legislative Calendar under General Orders. Calendar No. 70."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], 'calendar')
        self.assertEqual(new_action['calendar'], "Senate Legislative")
        self.assertEqual(new_action['under'], "General Orders")
        self.assertEqual(new_action['number'], "70")
        self.assertEqual(new_state, None)

    def test_enacted_as_public_law(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "ENACTED:SIGNED"
        line = "Became Public Law No: 111-148."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "enacted")
        self.assertEqual(new_action['congress'], "111")
        self.assertEqual(new_action['number'], "148")
        self.assertEqual(new_action['law'], "public")

    def test_cleared_for_whitehouse(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASSED:BILL"
        line = "Cleared for White House."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        # should not be marked as presented to president, since it hasn't been yet
        # self.assertEqual(new_action['type'], 'action')

    def test_presented_to_president(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASSED:BILL"
        line = "Presented to President."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], 'topresident')

    def test_signed_by_president(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASSED:BILL"
        line = "Signed by President."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], 'signed')

    # voting tests

    def test_vote_normal_roll(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "INTRODUCED"
        line = "On motion to suspend the rules and pass the bill Agreed to by the Yeas and Nays: (2/3 required): 416 - 0 (Roll no. 768)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action['how'], "roll")
        self.assertEqual(new_action['result'], "pass")
        self.assertEqual(new_action['roll'], "768")

        self.assertEqual(new_state, "PASS_OVER:HOUSE")

    def test_vote_normal_roll_second(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASS_OVER:HOUSE"
        line = "Passed Senate with an amendment and an amendment to the Title by Yea-Nay Vote. 60 - 39. Record Vote Number: 396."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote2")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action['how'], "roll")
        self.assertEqual(new_action['result'], "pass")
        self.assertEqual(new_action['roll'], "396")

        self.assertEqual(new_state, "PASS_BACK:SENATE")

    def test_cloture_vote_verbose(self):
        bill_id = "s1982-113"
        title = "Comprehensive Veterans Health and Benefits and Military Retirement Pay Restoration Act of 2014"
        line = "Cloture motion on the motion to proceed to the measure invoked in Senate by Yea-Nay Vote. 99 - 0. Record Vote Number: 44."
        state = "REPORTED"

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], "vote-aux")
        self.assertEqual(new_action['vote_type'], "cloture")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action['how'], "roll")
        self.assertEqual(new_action['result'], "pass")
        self.assertEqual(new_action['roll'], "44")

        self.assertEqual(new_state, None)

    def test_vote_roll_pingpong(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASS_BACK:SENATE"
        line = "On motion that the House agree to the Senate amendments Agreed to by recorded vote: 219 - 212 (Roll no. 165)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['roll'], "165")
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "pingpong")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action['how'], "roll")
        self.assertEqual(new_action['result'], "pass")

    def test_vote_cloture(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASS_OVER:HOUSE"  # should not change
        line = "Cloture on the motion to proceed to the bill invoked in Senate by Yea-Nay Vote. 60 - 39. Record Vote Number: 353."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['roll'], "353")
        self.assertEqual(new_action['type'], "vote-aux")
        self.assertEqual(new_action['vote_type'], "cloture")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action['how'], "roll")
        self.assertEqual(new_action['result'], "pass")

        self.assertEqual(new_state, None)  # unchanged

    def test_vote_cloture_2(self):
        bill_id = "hr3590-111"
        title = "An act entitled The Patient Protection and Affordable Care Act."
        state = "PASS_OVER:HOUSE"  # should not change
        line = "Cloture invoked in Senate by Yea-Nay Vote. 60 - 39. Record Vote Number: 395."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['roll'], "395")
        self.assertEqual(new_action['type'], "vote-aux")
        self.assertEqual(new_action['vote_type'], "cloture")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action['how'], "roll")
        self.assertEqual(new_action['result'], "pass")

        self.assertEqual(new_state, None)  # unchanged

    # not sure whether to include votes that are on process, not passage or cloture

    # def test_vote_process_voice_senate(self):
    #   bill_id = "hr3590-111"
    #   title = "An act entitled The Patient Protection and Affordable Care Act."
    # state = "PASS_OVER:HOUSE" # should not change
    #   line = "Motion to proceed to consideration of measure agreed to in Senate by Unanimous Consent."

    #   new_action, new_state = parse_bill_action(line, state, bill_id, title)

    #   self.assertEqual(new_action['type'], 'vote')
    #   self.assertEqual(new_action['vote_type'], 'other')
    #   self.assertEqual(new_action['how'], 'Unanimous Consent')
    #   self.assertEqual(new_action['where'], 's')
    #   self.assertEqual(new_action['result'], 'pass')
    #   self.assertEqual(new_state, None)

    # def test_vote_commit_roll_failure(self):
    #   bill_id = "hr3590-111"
    #   title = "An act entitled The Patient Protection and Affordable Care Act."
    # state = "PASS_OVER:HOUSE" # should not change
    #   line = "Motion by Senator McCain to commit to Senate Committee on Finance under the order of 12/2/2009, not having achieved 60 votes in the affirmative, the motion was rejected in Senate by Yea-Nay Vote. 42 - 58. Record Vote Number: 358."

    #   new_action, new_state = parse_bill_action(line, state, bill_id, title)

    #   self.assertEqual(new_action['type'], 'vote')
    #   self.assertEqual(new_action['vote_type'], 'other')
    #   self.assertEqual(new_action['how'], 'roll')
    #   self.assertEqual(new_action['where'], 's')
    #   self.assertEqual(new_action['result'], 'fail')
    #   self.assertEqual(new_action['roll'], "358")
    #   self.assertEqual(new_state, None)

    # def test_vote_motion_conference(self):
    #   bill_id = "hr3630-112"
    #   title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
    #   state = "PASS_BACK:SENATE"
    #   line = "On motion that the House disagree to the Senate amendments, and request a conference Agreed to by the Yeas and Nays: 229 - 193 (Roll no. 946)."

    #   new_action, new_state = parse_bill_action(line, state, bill_id, title)

    # self.assertEqual(new_action['type'], 'vote')
    # self.assertEqual(new_action['vote_type'], 'other')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 'h')
    # self.assertEqual(new_action['result'], 'pass')
    # self.assertEqual(new_action['roll'], "946")
    #   self.assertEqual(new_state, None)

    # def test_vote_motion_instruct_conferees(self):
    #   bill_id = "hr3630-112"
    #   title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
    #   state = "PASS_BACK:SENATE"
    #   line = "On motion that the House instruct conferees Agreed to by the Yeas and Nays: 397 - 16 (Roll no. 9)."

    #   new_action, new_state = parse_bill_action(line, state, bill_id, title)

    # self.assertEqual(new_action['type'], 'vote')
    # self.assertEqual(new_action['vote_type'], 'other')
    # self.assertEqual(new_action['how'], 'roll')
    # self.assertEqual(new_action['where'], 'h')
    # self.assertEqual(new_action['result'], 'pass')
    # self.assertEqual(new_action['roll'], "9")
    #   self.assertEqual(new_state, None)

    def test_vote_conference_report_house_pass(self):
        bill_id = "hr3630-112"
        title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
        state = "PASS_BACK:SENATE"
        line = "On agreeing to the conference report Agreed to by the Yeas and Nays: 293 - 132 (Roll no. 72)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], 'vote')
        self.assertEqual(new_action['vote_type'], 'conference')
        self.assertEqual(new_action['how'], 'roll')
        self.assertEqual(new_action['where'], 'h')
        self.assertEqual(new_action['result'], 'pass')
        self.assertEqual(new_action['roll'], "72")
        self.assertEqual(new_state, 'CONFERENCE:PASSED:HOUSE')

    def test_vote_conference_report_senate_pass(self):
        bill_id = "hr3630-112"
        title = "A bill to extend the payroll tax holiday, unemployment compensation, Medicare physician payment, provide for the consideration of the Keystone XL pipeline, and for other purposes."
        state = "CONFERENCE:PASSED:HOUSE"
        line = "Senate agreed to conference report by Yea-Nay Vote. 60 - 36. Record Vote Number: 22."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], 'vote')
        self.assertEqual(new_action['vote_type'], 'conference')
        self.assertEqual(new_action['how'], 'roll')
        self.assertEqual(new_action['where'], 's')
        self.assertEqual(new_action['result'], 'pass')
        self.assertEqual(new_action['roll'], "22")
        self.assertEqual(new_state, 'PASSED:BILL')

    def test_vote_veto_override_fail(self):
        bill_id = "hjres64-111"
        title = "Making further continuing appropriations for fiscal year 2010, and for other purposes."
        state = "PROV_KILL:VETO"
        line = "On passage, the objections of the President to the contrary notwithstanding Failed by the Yeas and Nays: (2/3 required): 143 - 245, 1 Present (Roll no. 2).On passage, the objections of the President to the contrary notwithstanding Failed by the Yeas and Nays: (2/3 required): 143 - 245, 1 Present (Roll no. 2)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "override")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action["result"], "fail")
        self.assertEqual(new_action["how"], "roll")
        self.assertEqual(new_action["roll"], "2")
        self.assertEqual(new_state, "VETOED:OVERRIDE_FAIL_ORIGINATING:HOUSE")

    def test_veto_override_success_once(self):
        bill_id = "hr6331-110"
        title = "Medicare Improvements for Patients and Providers Act of 2008"
        state = "PROV_KILL:VETO"
        line = "Two-thirds of the Members present having voted in the affirmative the bill is passed, Passed by the Yeas and Nays: (2/3 required): 383 - 41 (Roll no. 491)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "override")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "roll")
        self.assertEqual(new_action["roll"], "491")
        self.assertEqual(new_state, "VETOED:OVERRIDE_PASS_OVER:HOUSE")

    def test_veto_override_success_twice(self):
        bill_id = "hr6331-110"
        title = "Medicare Improvements for Patients and Providers Act of 2008"
        state = "VETOED:OVERRIDE_PASS_OVER:HOUSE"
        line = "Passed Senate over veto by Yea-Nay Vote. 70 - 26. Record Vote Number: 177."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "override")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "roll")
        self.assertEqual(new_action["roll"], "177")
        # self.assertEqual(new_state, "VETOED:OVERRIDE_COMPLETE:SENATE")

    # Fictional bill, no constitutional amendment passed by both Houses
    # in the THOMAS era (1973-present).
    # The 26th was passed by Congress in 1971, 27th passed by Congress in 1789.
    # The line here is taken from hjres10-109, when the House passed a
    # flag burning amendment. (A separate version later failed the Senate by one vote.)
    def test_passed_constitutional_amendment(self):
        bill_id = "sjres64-1000"
        title = "Proposing an amendment to the Constitution of the United States authorizing the Congress to prohibit the physical desecration of the flag of the United States."
        state = "PASS_OVER:SENATE"
        line = "On passage Passed by the Yeas and Nays: (2/3 required): 286 - 130 (Roll no. 296)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote2")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "roll")
        self.assertEqual(new_action["roll"], "296")
        self.assertEqual(new_state, "PASSED:CONSTAMEND")

    def test_passed_concurrent_resolution(self):
        bill_id = "hconres74-112"
        title = "Providing for a joint session of Congress to receive a message from the President."
        state = "PASS_OVER:HOUSE"
        line = "Received in the Senate, considered, and agreed to without amendment by Unanimous Consent."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote2")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "by Unanimous Consent")
        self.assertEqual(new_state, "PASSED:CONCURRENTRES")

    def test_passed_simple_resolution_house(self):
        bill_id = "hres9-112"
        title = "Instructing certain committees to report legislation replacing the job-killing health care law."
        state = "REPORTED"
        line = "On agreeing to the resolution, as amended Agreed to by the Yeas and Nays: 253 - 175 (Roll no. 16)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "roll")
        self.assertEqual(new_action['roll'], "16")
        self.assertEqual(new_state, "PASSED:SIMPLERES")

    def test_passed_simple_resolution_senate(self):
        bill_id = "sres484-112"
        title = "A resolution designating June 7, 2012, as \"National Hunger Awareness Day\"."
        state = "REPORTED"
        line = "Submitted in the Senate, considered, and agreed to without amendment and with a preamble by Unanimous Consent."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "by Unanimous Consent")
        self.assertEqual(new_state, "PASSED:SIMPLERES")

    def test_failed_simple_resolution_senate(self):
        bill_id = "sres5-113"
        title = "A resolution amending the Standing Rules of the Senate to provide for cloture to be invoked with less than a three-fifths majority after additional debate."
        state = "INTRODUCED"
        line = "Disagreed to in Senate by Voice Vote."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote")
        self.assertEqual(new_action['where'], "s")
        self.assertEqual(new_action["result"], "fail")
        self.assertEqual(new_action["how"], "by Voice Vote")
        self.assertEqual(new_state, "FAIL:ORIGINATING:SENATE")

    def test_failed_suspension_vote(self):
        bill_id = "hr1954-112"
        title = "To implement the President's request to increase the statutory limit on the public debt."
        state = "REFERRED"
        line = "On motion to suspend the rules and pass the bill Failed by the Yeas and Nays: (2/3 required): 97 - 318, 7 Present (Roll no. 379)."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action["result"], "fail")
        self.assertEqual(new_action["how"], "roll")
        self.assertEqual(new_action['roll'], "379")
        self.assertEqual(new_state, "PROV_KILL:SUSPENSIONFAILED")

    def test_passed_by_special_rule(self):
        bill_id = "hres240-109"
        title = "Amending the Rules of the House of Representatives to reinstate certain provisions of the rules relating to procedures of the Committee on Standards of Official Conduct to the form in which those provisions existed at the close of the 108th Congress."
        state = "INTRODUCED"
        line = "Passed House pursuant to H. Res. 241."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)
        self.assertEqual(new_action['type'], "vote")
        self.assertEqual(new_action['vote_type'], "vote")
        self.assertEqual(new_action['where'], "h")
        self.assertEqual(new_action["result"], "pass")
        self.assertEqual(new_action["how"], "by special rule")
        self.assertEqual(new_state, "PASSED:SIMPLERES")

        self.assertEqual(new_action['bill_ids'], ["hres241-109"])

    def test_referral_committee(self):
        bill_id = "hr547-113"
        title = "To provide for the establishment of a border protection strategy for the international land borders of the United States, to address the ecological and environmental impacts of border security infrastructure, measures, and activities along the international land borders of the United States, and for other purposes."
        state = "INTRODUCED"
        line = "Referred to the Committee on Homeland Security, and in addition to the Committees on Armed Services, Agriculture, and Natural Resources, for a period to be subsequently determined by the Speaker, in each case for consideration of such provisions as fall within the jurisdiction of the committee concerned."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], "referral")
        self.assertEqual(new_state, "REFERRED")

    def test_referral_subcommittee(self):
        bill_id = "hr547-113"
        title = "To provide for the establishment of a border protection strategy for the international land borders of the United States, to address the ecological and environmental impacts of border security infrastructure, measures, and activities along the international land borders of the United States, and for other purposes."
        state = "INTRODUCED"
        line = "Referred to the Subcommittee Indian and Alaska Native Affairs."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], "referral")
        self.assertEqual(new_state, "REFERRED")

    def test_hearings_held(self):
        bill_id = "s54-113"
        title = "A bill to increase public safety by punishing and deterring firearms trafficking."
        state = "REFERRED"
        line = "Committee on the Judiciary Subcommittee on the Constitution, Civil Rights and Human Rights. Hearings held."

        new_action, new_state = parse_bill_action(line, state, bill_id, title)

        self.assertEqual(new_action['type'], "hearings")
        # self.assertEqual(new_action['committees'], "Committee on the Judiciary Subcommittee on the Constitution, Civil Rights and Human Rights")
        self.assertEqual(new_state, None)  # did not change state
