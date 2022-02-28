# -*- coding: utf-8 -*-
"""
A module that monkey-patches the output_bill method to push the bill identifier
onto a task queue after the data file has been written to disk. To use this
module, invoke the bills scraper with the --patch option like so:

  usc-run bills --patch=contrib.beanstalkd

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
from congress.tasks import bills, amendment_info, vote_info


__all__ = [
    'patch',
    'process_bill_wrapper',
    'process_amendment_wrapper',
    'output_vote_wrapper'
]


_Connection = None
_Config = None


def init_guard(reconnect=False):
    global _Config, _Connection
    if _Config is None:
        with open('config.yml', 'r') as conffile:
            config = yaml.load(conffile, yaml.SafeLoader)
            assert 'beanstalk' in config
            assert 'connection' in config['beanstalk']
            assert 'host' in config['beanstalk']['connection']
            assert 'port' in config['beanstalk']['connection']
            assert 'tubes' in config['beanstalk']
            assert 'bills' in config['beanstalk']['tubes']
            assert 'amendments' in config['beanstalk']['tubes']
            assert 'votes' in config['beanstalk']['tubes']
            tube_names = list(config['beanstalk']['tubes'].values())
            assert max(Counter(tube_names).values()) == 1, 'Must use unique beanstalk tube names.'
            _Config = config['beanstalk']
    if _Connection is None or reconnect is True:
        conn = beanstalkc.Connection(**_Config['connection'])
        assert conn is not None
        _Connection = conn
    return (_Connection, _Config)


def process_bill_wrapper(process_bill):
    @wraps(process_bill)
    def _process_bill(bill, options, *args, **kwargs):
        orig_result = process_bill(bill, options, *args, **kwargs)

        (conn, config) = init_guard()
        for _ in range(2):
            try:
                conn.use(config['tubes']['bills'])
                conn.put(bill)
                logging.warn("Queued {} to beanstalkd.".format(bill))
                break
            except beanstalkc.SocketError:
                logging.warn("Lost connection to beanstalkd. Attempting to reconnect.")
                (conn, config) = init_guard(reconnect=True)
            except Exception as e:
                logging.warn("Ignored exception while queueing bill to beanstalkd: {0} {1}".format(str(type(e)), str(e)))
                traceback.print_exc()
                break

        return orig_result

    return _process_bill


def process_amendment_wrapper(process_amendment):
    @wraps(process_amendment)
    def _process_amendment(amdt_dict, bill_id, options, *args, **kwargs):
        orig_result = process_amendment(amdt_dict, bill_id, options, *args, **kwargs)
        amdt = amendment_info.build_amendment_id(amdt_dict['type'].lower(), amdt_dict['number'], amdt_dict['congress'])

        (conn, config) = init_guard()
        for _ in range(2):
            try:
                conn.use(config['tubes']['amendments'])
                conn.put(str(amdt))
                logging.warn("Queued {} to beanstalkd.".format(amdt))
                break
            except beanstalkc.SocketError:
                logging.warn("Lost connection to beanstalkd. Attempting to reconnect.")
                (conn, config) = init_guard(reconnect=True)
            except Exception as e:
                logging.warn("Ignored exception while queueing amendment to beanstalkd: {0} {1}".format(str(type(e)), str(e)))
                traceback.print_exc()
                break

        return orig_result

    return _process_amendment


def output_vote_wrapper(output_vote):
    @wraps(output_vote)
    def _output_vote(vote, options, *args, **kwargs):
        orig_result = output_vote(vote, options, *args, **kwargs)

        (conn, config) = init_guard()
        for _ in range(2):
            try:
                conn.use(config['tubes']['votes'])
                conn.put(vote['vote_id'])
                logging.warn('Queued {} to beanstalkd.'.format(vote['vote_id']))
                break
            except beanstalkc.SocketError:
                logging.warn('Lost connection to beanstalkd. Attempting to reconnect.')
                (conn, config) = init_guard(reconnect=True)
            except Exception as e:
                logging.warn('Ignored exception while queueing vote to beanstalkd: {0} {1}'.format(str(type(e)), str(e)))
                traceback.print_exc()
                break

        return orig_result

    return _output_vote


def patch(task_name):
    bills.process_bill = process_bill_wrapper(bills.process_bill)
    amendment_info.process_amendment = process_amendment_wrapper(amendment_info.process_amendment)
    vote_info.output_vote = output_vote_wrapper(vote_info.output_vote)


# Avoid scraping if the beanstalk config is invalid.
try:
    init_guard()
except AssertionError:
    print(__doc__)
    sys.exit(1)
