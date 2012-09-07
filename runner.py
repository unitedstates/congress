#!/usr/bin/env python

import sys
import os
import traceback
import pprint as pp


# set global HTTP timeouts to 10 seconds
import socket
socket.setdefaulttimeout(10)


# name of the task comes first
task_name = sys.argv[1]

# parse any command line flags off
options = {}
args = sys.argv[2:]
for arg in args:
  key, value = arg.split('=')
  if key and value:
    if value == 'True': value = True
    elif value == 'False': value = False
    options[key.lower()] = value


# depends on tasks/[task_name].py being present relative to this directory
sys.path.append("tasks")
import utils

try:
  __import__(task_name).run(options)
except Exception as exception:
  utils.admin(exception)