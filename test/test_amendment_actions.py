import unittest
from amendment_info import parse_amendment_actions
import datetime

# parsing various kinds of action text to extract metadata and establish state





class AmendmentActions(unittest.TestCase):

	def test_amendment_action_uses_amendments_plural(self):
		action = {
			'text': 'On agreeing to the Poe amendments (A009) Failed by recorded vote: 141 - 279 (Roll no. 164).',
			'type': 'action',
			'references': [],
			'acted_at': datetime.datetime(2005, 6, 17, 11, 16),
		}
		actions = [action]
		parse_amendment_actions(actions)
		action = actions[0]
		self.assertEqual(action['where'], 'h')
		self.assertEqual(action['type'], 'vote')
		self.assertEqual(action['vote_type'], 'vote')
		self.assertEqual(action['result'], 'fail')
		self.assertEqual(action['how'], 'roll')
		self.assertEqual(action['roll'], 164)

	def test_amendment_action_uses_as_modified_instead_of_as_amended(self):
		action = {
			'text': 'On agreeing to the Jackson-Lee (TX) amendment (A015) as modified Agreed to by recorded vote: 233 - 192 (Roll no. 412). (text as modified: CR H6290)',
			'type': 'action',
			'references': [],
			'acted_at': datetime.datetime(2005, 6, 17, 11, 16),
		}
		actions = [action]
		parse_amendment_actions(actions)
		action = actions[0]
		self.assertEqual(action['where'], 'h')
		self.assertEqual(action['type'], 'vote')
		self.assertEqual(action['vote_type'], 'vote')
		self.assertEqual(action['result'], 'pass')
		self.assertEqual(action['how'], 'roll')
		self.assertEqual(action['roll'], 412)

	def test_amendment_action_uses_capital_N_in_no(self):
		action = {
			'text': 'On agreeing to the Capps amendment (A028) Failed by recorded vote: 213 - 219 (Roll No. 129).',
			'type': 'action',
			'references': [],
			'acted_at': datetime.datetime(2005, 6, 17, 11, 16),
		}
		actions = [action]
		parse_amendment_actions(actions)
		action = actions[0]
		self.assertEqual(action['where'], 'h')
		self.assertEqual(action['type'], 'vote')
		self.assertEqual(action['vote_type'], 'vote')
		self.assertEqual(action['result'], 'fail')
		self.assertEqual(action['how'], 'roll')
		self.assertEqual(action['roll'], 129)

