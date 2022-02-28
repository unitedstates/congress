#!/usr/bin/env python

import sys
import os
import traceback
import pprint as pp
import logging
import importlib

# set global HTTP timeouts to 10 seconds
import socket

def main():
    socket.setdefaulttimeout(10)

    CONGRESS_ROOT = os.path.dirname(os.path.abspath(__file__))

    # name of the task comes first
    task_name = sys.argv[1]

    # parse any command line flags off
    options = {}
    for arg in sys.argv[2:]:
        if arg.startswith("--"):

            if "=" in arg:
                key, value = arg.split('=')
            else:
                key, value = arg, True

            key = key.split("--")[1]
            if value == 'True':
                value = True
            elif value == 'False':
                value = False
            options[key.lower()] = value


    # configure logging
    if options.get('debug', False):
        log_level = "debug"
    else:
        log_level = options.get("log", "warn")

    if log_level not in ["debug", "info", "warn", "error"]:
        print("Invalid log level (specify: debug, info, warn, error).")
        sys.exit(1)

    if options.get('timestamps', False):
        logging.basicConfig(format='%(asctime)s %(message)s', level=log_level.upper())
    else:
        logging.basicConfig(format='%(message)s', level=log_level.upper())


    sys.path.append(os.path.join(CONGRESS_ROOT, "tasks"))
    import utils

    try:
        task_mod = __import__(task_name)

        if 'patch' in options:
            patch_mod = importlib.import_module(options['patch'])
            patch_func = getattr(patch_mod, 'patch', None)
            if patch_func is None:
                logging.error("You specified a --patch argument but the {} module does not contain a 'patch' function.".format(options['patch']))
                sys.exit(1)
            elif not callable(patch_func):
                logging.error("You specified a --patch argument but {}.patch is not callable".format(options['patch']))
                sys.exit(1)
            else:
                patch_mod.patch(task_name)

        task_mod.run(options)
    except Exception as exception:
        utils.admin(exception)

if __name__ == "__main__":
    main()
