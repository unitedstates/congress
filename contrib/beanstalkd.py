# -*- coding: utf-8 -*-
"""
A module that monkey-patches the output_bill method to push the bill identifier
onto a task queue after the data file has been written to disk. To use this
module, invoke the bills scraper with the --patch option like so:

  ./run bills --patch=contrib.beanstalkd

You must include a 'beakstalk' section in config.yml with this structure
(though the values are up to you):

  beanstalk:
    connection:
      host: 'localhost'
      port: 11300
    tubes:
      bills: 'us_bills'
      amendments: 'us_amendments'
      votes: 'us_votes'
"""

from __future__ import print_function

import sys
import logging
import time
import traceback

from collections import Counter
from functools import wraps

import yaml
import beanstalkc

# The patch module is loaded after the task module is loaded, so all task
# modules are on the import path.
import bill_info


__all__ = ['patch', 'output_bill_wrapper']


_Connection = None
_Config = None


def init_guard(reconnect=False):
    global _Config, _Connection
    if _Config is None:
        with open('config.yml', 'r') as conffile:
            config = yaml.load(conffile)
            assert 'beanstalk' in config
            assert 'connection' in config['beanstalk']
            assert 'host' in config['beanstalk']['connection']
            assert 'port' in config['beanstalk']['connection']
            assert 'tubes' in config['beanstalk']
            assert 'bills' in config['beanstalk']['tubes']
            assert 'amendments' in config['beanstalk']['tubes']
            assert 'votes' in config['beanstalk']['tubes']
            tube_names = config['beanstalk']['tubes'].values()
            assert max(Counter(tube_names).values()) == 1, 'Must use unique beanstalk tube names.'
            _Config = config['beanstalk']
    if _Connection is None or reconnect == True:
        conn = beanstalkc.Connection(**_Config['connection'])
        assert conn is not None
        _Connection = conn
    return (_Connection, _Config)


def output_bill_wrapper(output_bill):
    @wraps(output_bill)
    def _output_bill(bill, options, *args, **kwargs):
        orig_result = output_bill(bill, options, *args, **kwargs)

        (conn, config) = init_guard()
        for _ in range(2):
            try:
                conn.use(config['tubes']['bills'])
                conn.put(bill["bill_id"])
                logging.warn(u"Queued {} to beanstalkd.".format(bill['bill_id']))
                break
            except beanstalkc.SocketError:
                logging.warn(u"Lost connection to beanstalkd. Attempting to reconnect.")
                (conn, config) = init_guard(reconnect=True)
            except Exception as e:
                logging.warn(u"Ignored exception while queueing bill to beanstalkd: {0} {1}".format(unicode(type(e)), unicode(e)))
                traceback.print_exc()
                break

        return orig_result

    return _output_bill


def patch(task_name):
    bill_info.output_bill = output_bill_wrapper(bill_info.output_bill)


# Avoid scraping if the beanstalk config is invalid.
try:
    init_guard()
except AssertionError:
    print(__doc__)
    sys.exit(1)
