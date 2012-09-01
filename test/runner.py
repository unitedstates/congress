#!/usr/bin/env python

import sys
import unittest
sys.path.append("tasks") # allow test classes to easily load tasks
import bill_info

tests = unittest.TestLoader().discover("test")
unittest.TextTestRunner().run(tests)