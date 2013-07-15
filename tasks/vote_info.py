import utils
import logging
import re
import json
from lxml import etree
import time, datetime, os, os.path

def fetch_vote(vote_id, options):
  logging.info("\n[%s] Fetching..." % vote_id)
  
  vote_chamber, vote_number, vote_congress, vote_session_year = utils.split_vote_id(vote_id)
  
  if vote_chamber == "h":
    url = "http://clerk.house.gov/evs/%s/roll%03d.xml" % (vote_session_year, int(vote_number))
  else:
    session_num = int(vote_session_year) - utils.get_congress_first_year(int(vote_congress)) + 1
    url = "http://www.senate.gov/legislative/LIS/roll_call_votes/vote%d%d/vote_%d_%d_%05d.xml" % (int(vote_congress), session_num, int(vote_congress), session_num, int(vote_number))
  
  # fetch vote XML page
  body = utils.download(
    url, 
    "%s/votes/%s/%s%s/%s%s.xml" % (vote_congress, vote_session_year, vote_chamber, vote_number, vote_chamber, vote_number),
    utils.merge(options, {'xml': True}),
    )

  if not body:
    return {'saved': False, 'ok': False, 'reason': "failed to download"}

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}

  if "This vote was vacated" in body:
    # Vacated votes: 2011-484, 2012-327, ...
    # Remove file, since it may previously have existed with data.
    for f in (output_for_vote(vote_id, "json"), output_for_vote(vote_id, "xml")):
      if os.path.exists(f):
        os.unlink(f)
    return {'saved': False, 'ok': True, 'reason': "vote was vacated"}

  dom = etree.fromstring(body)

  vote = {
    'vote_id': vote_id,
    'chamber': vote_chamber,
    'congress': int(vote_congress),
    'session': vote_session_year,
    'number': int(vote_number),
    'updated_at': datetime.datetime.fromtimestamp(time.time()),
    'source_url': url,
  }
  
  # do the heavy lifting
  
  if vote_chamber == "h":
    parse_house_vote(dom, vote)
  elif vote_chamber == "s":
    parse_senate_vote(dom, vote)
    
  # output and return
  
  output_vote(vote, options)

  return {'ok': True, 'saved': True}

def output_vote(vote, options):
  logging.info("[%s] Writing to disk..." % vote['vote_id'])
  
  # output JSON - so easy!
  utils.write(
    json.dumps(vote, sort_keys=True, indent=2, default=utils.format_datetime), 
    output_for_vote(vote["vote_id"], "json"),
  )

  # output XML
  root = etree.Element("roll")
  
  root.set("where", "house" if vote['chamber'] == "h" else "senate")
  root.set("session", str(vote["congress"]))
  root.set("year", str(vote["date"].year))
  root.set("roll", str(vote["number"]))
  root.set("datetime", utils.format_datetime(vote['date']))
  
  root.set("updated", utils.format_datetime(vote['updated_at']))
  
  def get_votes(option): return len(vote["votes"].get(option, []))
  root.set("aye", str(get_votes("Yea") + get_votes("Aye")))
  root.set("nay", str(get_votes("Nay") + get_votes("No")))
  root.set("present", str(get_votes("Present")))
  root.set("nv", str(get_votes("Not Voting")))
  
  root.set("source", "house.gov" if vote["chamber"] == "h" else "senate.gov")
  
  utils.make_node(root, "category", vote["category"])
  utils.make_node(root, "type", vote["type"])
  utils.make_node(root, "question", vote["question"])
  utils.make_node(root, "required", vote["requires"])
  utils.make_node(root, "result", vote["result"])
  
  if "bill" in vote:
    govtrack_type_codes = { 'hr': 'h', 's': 's', 'hres': 'hr', 'sres': 'sr', 'hjres': 'hj', 'sjres': 'sj', 'hconres': 'hc', 'sconres': 'sc' }
    utils.make_node(root, "bill", None, session=str(vote["bill"]["congress"]), type=govtrack_type_codes[vote["bill"]["type"]], number=str(vote["bill"]["number"]))
    
  if "amendment" in vote:
    if vote["amendment"]["type"] == "s":
      utils.make_node(root, "amendment", None, ref="regular", number="s" + str(vote["amendment"]["number"]))
    elif vote["amendment"]["type"] == "h-bill":
      utils.make_node(root, "amendment", None, ref="bill-serial", number=str(vote["amendment"]["number"]))
    
  # well-known keys for certain vote types: +/-/P/0
  option_keys = { "Aye": "+", "Yea": "+", "Nay": "-", "No": "-", "Present": "P", "Not Voting": "0" }
  
  # preferred order of output: ayes, nays, present, then not voting, and similarly for guilty/not-guilty
  # and handling other options like people's names for votes for the Speaker.
  option_sort_order = ('Aye', 'Yea', 'Guilty', 'No', 'Nay', 'Not Guilty', 'OTHER', 'Present', 'Not Voting')
  options_list = sorted(vote["votes"].keys(), key = lambda o : option_sort_order.index(o) if o in option_sort_order else option_sort_order.index("OTHER") )
  for option in options_list:
    if option not in option_keys: option_keys[option] = option
    utils.make_node(root, "option", option, key=option_keys[option])
    
  for option in options_list:
    for v in vote["votes"][option]:
      attrs = { "vote": option_keys[option], "value": option }
      if v == "VP":
        attrs["id"] = "0"
        attrs["VP"] = "1"
      elif not options.get("govtrack", False):
        attrs["id"] = str(v["id"])
        attrs["state"] = v["state"]
      else:
        attrs["id"] = str(utils.get_govtrack_person_id("bioguide" if vote["chamber"] == "h" else "lis", v["id"]))
        attrs["state"] = v["state"]
      utils.make_node(root, "voter", None, **attrs)
  
  utils.write(
    etree.tostring(root, pretty_print=True),
    output_for_vote(vote['vote_id'], "xml")
  )

def output_for_vote(vote_id, format):
  vote_chamber, vote_number, vote_congress, vote_session_year = utils.split_vote_id(vote_id)
  return "%s/%s/votes/%s/%s%s/%s" % (utils.data_dir(), vote_congress, vote_session_year, vote_chamber, vote_number, "data.%s" % format)

def parse_senate_vote(dom, vote):
  def parse_date(d):
    return datetime.datetime.strptime(d, "%B %d, %Y, %I:%M %p")

  vote["date"] = parse_date(dom.xpath("string(vote_date)"))
  if len(dom.xpath("modify_date")) > 0: vote["record_modified"] = parse_date(dom.xpath("string(modify_date)")) # some votes like s1-110.2008 don't have a modify_date
  vote["question"] = unicode(dom.xpath("string(vote_question_text)"))
  vote["type"] = unicode(dom.xpath("string(vote_question)"))
  if vote["type"] == "": vote["type"] = vote["question"]
  vote["type"] = normalize_vote_type(vote["type"])
  vote["category"] = get_vote_category(vote["type"])
  vote["subject"] = unicode(dom.xpath("string(vote_title)"))
  vote["requires"] = unicode(dom.xpath("string(majority_requirement)"))
  vote["result_text"] = unicode(dom.xpath("string(vote_result_text)"))
  vote["result"] = unicode(dom.xpath("string(vote_result)"))
  
  bill_types = { "S.": "s", "S.Con.Res.": "sconres", "S.J.Res.": "sjres", "S.Res.": "sres", "H.R.": "hr", "H.Con.Res.": "hconres", "H.J.Res.": "hjres", "H.Res.": "hres" }

  if unicode(dom.xpath("string(document/document_type)")):
    if dom.xpath("string(document/document_type)") == "PN":
      vote["nomination"] = {
        "number": unicode(dom.xpath("string(document/document_number)")),
        "title": unicode(dom.xpath("string(document/document_title)")),
      }
      vote["question"] += ": " + vote["nomination"]["title"]
    elif dom.xpath("string(document/document_type)") == "Treaty Doc.":
      vote["treaty"] = {
        "title": unicode(dom.xpath("string(document/document_title)")),
      }
    else:
      vote["bill"] = {
        "congress": int(dom.xpath("number(document/document_congress|congress)")), # some historical files don't have document/document_congress so take the first of document/document_congress or the top-level congress element as a fall-back
        "type": bill_types[unicode(dom.xpath("string(document/document_type)"))],
        "number": int(dom.xpath("number(document/document_number)")),
        "title": unicode(dom.xpath("string(document/document_title)")),
      }
      
  if unicode(dom.xpath("string(amendment/amendment_number)")):
    m = re.match(r"^S.Amdt. (\d+)", unicode(dom.xpath("string(amendment/amendment_number)")))
    if m:
      vote["amendment"] = {
        "type": "s",
        "number": int(m.group(1)),
        "purpose": unicode(dom.xpath("string(amendment/amendment_purpose)")),
      }
    
    amendment_to = unicode(dom.xpath("string(amendment/amendment_to_document_number)"))
    if "Treaty" in amendment_to:
      treaty, number = amendment_to.split("-")
      vote["treaty"] = {
        "congress": vote["congress"],
        "number": number,
      }
    elif " " in amendment_to:
      bill_type, bill_number = amendment_to.split(" ")
      vote["bill"] = {
        "congress": vote["congress"],
        "type": bill_types[bill_type],
        "number": int(bill_number),
        "title": unicode(dom.xpath("string(amendment/amendment_to_document_short_title)")),
      }
    else:
      # Senate votes:
      # 102nd Congress, 2nd session (1992): 247, 248, 250; 105th Congress, 2nd session (1998): 106 through 116; 108th Congress, 1st session (2003): 41, 42
      logging.warn("Amendment without corresponding bill info in %s " % vote["vote_id"])
    
  # Count up the votes.
  vote["votes"] = { }
  def add_vote(vote_option, voter):
    if vote_option == "Present, Giving Live Pair": vote_option = "Present"
    vote["votes"].setdefault(vote_option, []).append(voter)
  
  # Ensure the options are noted, even if no one votes that way.
  if unicode(dom.xpath("string(vote_question)")) == "Guilty or Not Guilty":
    vote["votes"]['Guilty'] = []
    vote["votes"]['Not Guilty'] = []
  else:
    vote["votes"]['Yea'] = []
    vote["votes"]['Nay'] = []
  vote["votes"]['Present'] = []
  vote["votes"]['Not Voting'] = []
  
  # VP tie-breaker?
  if str(dom.xpath("string(tie_breaker/by_whom)")):
    add_vote(str(dom.xpath("string(tie_breaker/tie_breaker_vote)")), "VP")
    
  for member in dom.xpath("members/member"):
    add_vote(str(member.xpath("string(vote_cast)")), {
        "id": str(member.xpath("string(lis_member_id)")),
        "state": str(member.xpath("string(state)")),
        "party": str(member.xpath("string(party)")),
        "display_name": unicode(member.xpath("string(member_full)")),
        "first_name": str(member.xpath("string(first_name)")),
        "last_name": str(member.xpath("string(last_name)")),
    })
  
def parse_house_vote(dom, vote):
  def parse_date(d):
    d = d.strip()
    if " " in d:
      return datetime.datetime.strptime(d, "%d-%b-%Y %I:%M %p")
    else: # some votes have no times?
      print vote
      return datetime.datetime.strptime(d, "%d-%b-%Y")

  vote["date"] = parse_date(str(dom.xpath("string(vote-metadata/action-date)")) + " " + str(dom.xpath("string(vote-metadata/action-time)")))
  vote["question"] = unicode(dom.xpath("string(vote-metadata/vote-question)"))
  vote["type"] = unicode(dom.xpath("string(vote-metadata/vote-question)"))
  vote["type"] = normalize_vote_type(vote["type"])
  vote["category"] = get_vote_category(vote["question"])
  vote["subject"] = unicode(dom.xpath("string(vote-metadata/vote-desc)"))
  if not vote["subject"]: del vote["subject"]
  
  vote_types = { "YEA-AND-NAY": "1/2", "2/3 YEA-AND-NAY": "2/3", "3/5 YEA-AND-NAY": "3/5", "1/2": "1/2", "2/3" : "2/3", "QUORUM": "QUORUM", "RECORDED VOTE" : "1/2", "2/3 RECORDED VOTE": "2/3", "3/5 RECORDED VOTE": "3/5" }
  vote["requires"] = vote_types.get(str(dom.xpath("string(vote-metadata/vote-type)")), "unknown")
  
  vote["result_text"] = unicode(dom.xpath("string(vote-metadata/vote-result)"))
  vote["result"] = unicode(dom.xpath("string(vote-metadata/vote-result)"))
  
  bill_num = unicode(dom.xpath("string(vote-metadata/legis-num)"))
  if bill_num not in ("", "QUORUM", "JOURNAL", "MOTION", "ADJOURN") and not re.match(r"QUORUM \d+$", bill_num):
    bill_types = { "S": "s", "S CON RES": "sconres", "S J RES": "sjres", "S RES": "sres", "H R": "hr", "H CON RES": "hconres", "H J RES": "hjres", "H RES": "hres" }
    try:
      bill_type, bill_number = bill_num.rsplit(" ", 1)
      vote["bill"] = {
        "congress": vote["congress"],
        "type": bill_types[bill_type],
        "number": int(bill_number)
      }
    except ValueError: # rsplit failed, i.e. there is no space in the legis-num field
      raise Exception("Unhandled bill number in the legis-num field")
    
  if str(dom.xpath("string(vote-metadata/amendment-num)")):
    vote["amendment"] = {
      "type": "h-bill",
      "number": int(str(dom.xpath("string(vote-metadata/amendment-num)"))),
      "author": unicode(dom.xpath("string(vote-metadata/amendment-author)")),
    }

  # Assemble a complete question from the vote type, amendment, and bill number.
  if "amendment" in vote and "bill" in vote:
    vote["question"] += ": Amendment %s to %s" % (vote["amendment"]["number"], unicode(dom.xpath("string(vote-metadata/legis-num)")))
  elif "amendment" in vote:
    vote["question"] += ": Amendment %s to [unknown bill]" % vote["amendment"]["number"]
  elif "bill" in vote:
    vote["question"] += ": " + unicode(dom.xpath("string(vote-metadata/legis-num)"))
    if "subject" in vote: vote["question"] += " " + vote["subject"]
  elif "subject" in vote:
    vote["question"] += ": " + vote["subject"]

  # Count up the votes.
  vote["votes"] = { } # by vote type
  def add_vote(vote_option, voter):
    vote["votes"].setdefault(vote_option, []).append(voter)
  
  # Ensure the options are noted, even if no one votes that way.
  if unicode(dom.xpath("string(vote-metadata/vote-question)")) == "Election of the Speaker":
    for n in dom.xpath('vote-metadata/vote-totals/totals-by-candidate/candidate'):
      vote["votes"][n.text] = []
  elif unicode(dom.xpath("string(vote-metadata/vote-question)")) == "Call of the House":
    for n in dom.xpath('vote-metadata/vote-totals/totals-by-candidate/candidate'):
      vote["votes"][n.text] = []
  elif "YEA-AND-NAY" in dom.xpath('string(vote-metadata/vote-type)'):
    vote["votes"]['Yea'] = []
    vote["votes"]['Nay'] = []
    vote["votes"]['Present'] = []
    vote["votes"]['Not Voting'] = []
  else:
    vote["votes"]['Aye'] = []
    vote["votes"]['No'] = []
    vote["votes"]['Present'] = []
    vote["votes"]['Not Voting'] = []
  
  for member in dom.xpath("vote-data/recorded-vote"):
    display_name = unicode(member.xpath("string(legislator)"))
    state = str(member.xpath("string(legislator/@state)"))
    party = str(member.xpath("string(legislator/@party)"))
    vote_cast = str(member.xpath("string(vote)"))

    bioguideid = str(member.xpath("string(legislator/@name-id)"))

    if bioguideid == "0000000": 
      # there is a specific upstream error for this range of votes, where G.K. Butterfield's bioguide ID is 000000.
      # after discussion in https://github.com/unitedstates/congress/issues/46, 
      # we are hardcoding a fix until it's fixed upstream.
      if (vote['congress'] == 108) and (vote['session'] == '2004') and (vote['number'] >= 405 and vote['number'] <= 544):
        bioguideid = "B001251"
      else:
        raise Exception("Invalid bioguide ID for %s (%s-%s)" % (display_name, state, party))

    add_vote(vote_cast, {
        "id": bioguideid,
        "state": state,
        "party": party,
        "display_name": display_name,
    })


def normalize_vote_type(vote_type):
  # Takes the "type" field of a House or Senate vote and returns a normalized
  # version of the same, as best as possible.
  
  # note that these allow .* after each pattern, so some things look like
  # no-ops but they are really truncating the type after the specified text.
  mapping = (
    (r"On (Agreeing to )?the (Joint |Concurrent )?Resolution", "On the $2Resolution"),
    (r"On (Agreeing to )?the Conference Report", "On the Conference Report"),
    (r"On (Agreeing to )?the (En Bloc )?Amendments?", "On the Amendment"),
    (r"On (?:the )?Motion to Recommit", "On the Motion to Recommit"),
    (r"(On Motion to )?(Concur in|Concurring|On Concurring|Agree to|On Agreeing to) (the )?Senate (Amendment|amdt|Adt)s?", "Concurring in the Senate Amendment"),
    (r"(On Motion to )?Suspend (the )?Rules and (Agree|Concur|Pass)(, As Amended)", "On Motion to Suspend the Rules and $3$4"),
    (r"Will the House Now Consider the Resolution|On (Question of )?Consideration of the Resolution", "On Consideration of the Resolution"),
    (r"On (the )?Motion to Adjourn", "On the Motion to Adjourn"),
    (r"On (the )?Cloture Motion", "On the Cloture Motion"),
    (r"On Cloture on the Motion to Proceed", "On the Cloture Motion"),
    (r"On (the )?Nomination", "On the Nomination"),
    (r"On Passage( of the Bill|$)", "On Passage of the Bill"),
    (r"On (the )?Motion to Proceed", "On the Motion to Proceed"),
  )
  
  for regex, replacement in mapping:
    m = re.match(regex, vote_type, re.I)
    if m:
      if m.groups():
        for i, val in enumerate(m.groups()):
          replacement = replacement.replace("$%d" % (i+1), val if val else "")
      return replacement

  return vote_type

def get_vote_category(vote_question):
  # Takes the "question" field of a House or Senate vote and returns a normalized
  # category for the vote type.
  #
  # Based on Eric's vote_type_for function in sunlightlabs/congress.
  
  mapping = (
    # empty text (historical data)
    (r"^$", "unknown"),
  
    # common
    (r"^On Overriding the Veto", "veto-override"),
    (r"^On Presidential Veto", "veto-override"),
    (r"Objections of the President Not ?Withstanding", "veto-override"), # order matters so must go before bill passage
    (r"^On Passage", "passage"),
    (r"^On (Agreeing to )?the (Joint |Concurrent )?Resolution", "passage"),
    (r"^On (Agreeing to )?the Conference Report", "passage"),
    (r"^On (Agreeing to )?the (En Bloc )?Amendments?", "amendment"),
      
    # senate only
    (r"cloture", "cloture"),
    (r"^On the Nomination", "nomination"),
    (r"^Guilty or Not Guilty", "conviction"), # was "impeachment" in sunlightlabs/congress but that's not quite right
    (r"^On the Resolution of Ratification", "treaty"),
    (r"^On (?:the )?Motion to Recommit", "recommit"),
      
    # house only
    (r"^(On Motion to )?(Concur in|Concurring|On Concurring|Agree to|On Agreeing to) (the )?Senate (Amendment|amdt|Adt)s?", "passage"),
    (r"^(On Motion to )?Suspend (the )?Rules and (Agree|Concur|Pass)", "passage-suspension"),
    (r"^Call of the House$", "quorum"),
    (r"^Election of the Speaker$", "leadership"),
    
    # various procedural things
    # order matters, so these must go last
    (r"^On Ordering the Previous Question", "procedural"),
    (r"^On Approving the Journal", "procedural"),
    (r"^Will the House Now Consider the Resolution|On (Question of )?Consideration of the Resolution", "procedural"),
    (r"^On (the )?Motion to Adjourn", "procedural"),
    (r"Authoriz(e|ing) Conferees", "procedural"),
    (r"On the Point of Order|Sustaining the Ruling of the Chair", "procedural"),
    (r"^On .*Motion ", "procedural"), # $1 is a name like "Broun of Georgia"
    (r"^On the Decision of the Chair", "procedural"),
    (r"^Whether the Amendment is Germane", "procedural"),
  )
  
  for regex, category in mapping:
    if re.search(regex, vote_question, re.I):
      return category

  # unhandled
  logging.warn("Unhandled vote question: %s" % vote_question)
  return "unknown"

