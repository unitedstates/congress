import pprint

def log(object):
  if isinstance(object, str):
    print object
  else:
    pprint.pprint(object)