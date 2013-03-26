import json, re
import utils
import logging


'''
the goal here is to convert the natural language of the amendment into code
that can operate on the json-ized legislation, which is represented as a
dictionary of page numbers containing a dictionary of line numbers and text.

Fortunately, we are dealing with a small vocabulary that doesn't require
tremendous NLP chops.
'''

#certain amendment structures are so common that it's wisest -- that is, easiest -- to define explicitly
prefabs = [
    ("(On page (\d+), lines? (\d+), ([a-z]+) the amount by \$([\d,]+)\.)", ["verbatim", "page", "line", "action", "content"]),
    ("(On page (\d+), (.*?)lines? (\d+)(.*?)(?:\.|;))", ["verbatim", "page", "action", "line", "content"]),
    ("(At the (end) of (.*?), ([a-z]+) the following:?(.*))", ["verbatim", "direction", "location", "action", "content"]),
    ("(At the (appropriate place),? ([a-z]+) the following:?(.*))", ["verbatim", "location", "action", "content"])
]

#a list of verbs that will translate to functions
actions = ["strike", "insert", "delete", "increase", "decrease"]

#indications of where to insert of remove text relative to the point of entry
directions = ["after", "at the end"]

def parse_amendment_text(amendment, bill):
  if amendment["info"]["amends"]["document_type"] != "bill":
    logging.info("amendment %s does not amend the bill itself." % amendment["info"]["amendment_id"])
    return amendment

  amendment["text"] = re.sub("\s+", " ", amendment["text"], re.S)
  
  # parse the intention of the amendment
  amendment["commands"] = []
  commands = []
  #print bill["roadmap"]

  #check for prefab patterns
  for prefab in prefabs:
      temp = re.findall(prefab[0], amendment["text"], re.I | re.S)
      if temp:
          for match in temp:
              command = dict([(x[1], match[x[0]]) for x in enumerate(prefab[1])])
              commands.append(command)
              #remove the matched command to prevent double counting
              amendment["text"] = amendment["text"].replace(command["verbatim"], "")


  # for amendments that reference a place in the legislation instead of line number, resolve to location
  for command in commands:
      if len(command["verbatim"]) > 1000:
        command["verbatim"] = "<em>Text of amendment too long (" + str(len(command["verbatim"].split(" "))) + " words).</em>"
      if "line" in command and "page" in command:
          amendment["commands"].append(command)
      elif "location" in command:
          command["location"] = command["location"].strip().upper()
          if command["location"] in bill["roadmap"]:
              command["page"] = bill["roadmap"][command["location"]][0]
              command["line"] = bill["roadmap"][command["location"]][1]
              amendment["commands"].append(command)
          else:
              print "Couldn't find %s" % command["location"]
              
  return amendment
