import utils
import logging
import re
import json
from lxml import etree
import time, datetime

def fetch_vote(vote_id, options):
  logging.info("\n[%s] Fetching..." % vote_id)
  
  vote_chamber, vote_number, vote_congress, vote_session = utils.split_vote_id(vote_id)
  
  if vote_chamber == "h":
    session_year = utils.get_session_canonical_year(int(vote_congress), int(vote_session))
    url = "http://clerk.house.gov/evs/%d/roll%03d.xml" % (session_year, int(vote_number))
    # Vacated votes: 2011-484, 2012-327
  else:
    url = "http://www.senate.gov/legislative/LIS/roll_call_votes/vote%d%d/vote_%d_%d_%05d.xml" % (int(vote_congress), int(vote_session), int(vote_congress), int(vote_session), int(vote_number))
  
  # fetch vote XML page
  body = utils.download(
    url, 
    "%s/votes/%s/%s%s" % (vote_congress, vote_session, vote_chamber, vote_number),
    options.get('force', False),
    is_xml=True)

  if not body:
    return {'saved': False, 'ok': False, 'reason': "failed to download"}

  if options.get("download_only", False):
    return {'saved': False, 'ok': True, 'reason': "requested download only"}

  dom = etree.fromstring(body)

  vote = {
    'vote_id': vote_id,
    'chamber': vote_chamber,
    'congress': int(vote_congress),
    'session': int(vote_session),
    'number': int(vote_number)
  }
  
  if vote_chamber == "h":
    parse_house_vote(dom, vote)
  elif vote_chamber == "s":
    parse_senate_vote(dom, vote)
  
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
  utils.write(
    etree.tostring(root, pretty_print=True),
    output_for_vote(vote['vote_id'], "xml")
  )

def output_for_vote(vote_id, format):
  vote_chamber, vote_number, vote_congress, vote_session = utils.split_vote_id(vote_id)
  return "%s/%s/votes/%s/%s%s/%s" % (utils.data_dir(), vote_congress, vote_session, vote_chamber, vote_number, "data.%s" % format)

def parse_senate_vote(dom, vote):
  def parse_date(d):
    return datetime.datetime.strptime(d, "%B %d, %Y, %I:%M %p")

  vote["date"] = parse_date(dom.xpath("string(vote_date)"))
  vote["record_modified"] = parse_date(dom.xpath("string(modify_date)"))
  vote["question"] = unicode(dom.xpath("string(vote_question_text)"))
  vote["type_text"] = unicode(dom.xpath("string(vote_question)"))
  vote["subject"] = unicode(dom.xpath("string(vote_title)"))
  vote["requires"] = unicode(dom.xpath("string(majority_requirement)"))
  vote["result_text"] = unicode(dom.xpath("string(vote_result_text)"))
  vote["result"] = unicode(dom.xpath("string(vote_result)"))
  
  bill_types = { "S.": "s", "S.Con.Res.": "sconres", "S.J.Res.": "sjres", "S.Res.": "sres", "H.R.": "hr", "H.Con.Res.": "hconres", "H.J.Res.": "hjres", "H.Res.": "hres" }

  if unicode(dom.xpath("string(document/document_type)")):
    vote["bill"] = {
      "congress": int(dom.xpath("number(document/document_congress)")),
      "type": bill_types[unicode(dom.xpath("string(document/document_type)"))],
      "number": int(dom.xpath("number(document/document_number)")),
      "title": unicode(dom.xpath("string(document/document_title)")),
    }
    
  if unicode(dom.xpath("string(amendment/amendment_number)")):
    m = re.match(r"S.Amdt. (\d+)$", unicode(dom.xpath("string(amendment/amendment_number)")))
    if m:
      vote["amendment"] = {
        "chamber": "s",
        "number": int(m.group(1)),
        "purpose": unicode(dom.xpath("string(amendment/amendment_purpose)")),
      }
      
    bill_type, bill_number = unicode(dom.xpath("string(amendment/amendment_to_document_number)")).split(" ")
    vote["bill"] = {
      "congress": vote["congress"],
      "type": bill_types[bill_type],
      "number": int(bill_number),
      "title": unicode(dom.xpath("string(amendment/amendment_to_document_short_title)")),
    }
    
  # Count up the votes.
  votes = { } # by vote type
  def add_vote(vote, voter):
    if vote == "Present, Giving Live Pair": vote = "Present"
    votes.setdefault(vote, []).append(voter)
  
  # Ensure the options are noted, even if no one votes that way.
  if unicode(dom.xpath("string(vote_question)")) == "Guilty or Not Guilty":
    votes['Guilty'] = []
    votes['Not Guilty'] = []
  else:
    votes['Yea'] = []
    votes['Nay'] = []
  votes['Present'] = []
  votes['Not Voting'] = []
  
  # VP tie-breaker?
  if str(dom.xpath("string(tie_breaker/by_whom)")):
    add_vote(str(dom.xpath("string(tie_breaker/tie_breaker_vote)")), "VP")
    
  for member in dom.xpath("members/member"):
    # LIS ID, prefixed with "S" --- remove the "S"
    who = str(member.xpath("string(lis_member_id)"))
    who = who.replace("S", "")
    who = int(who)
    
    add_vote(str(member.xpath("string(vote_cast)")), who)
      
  vote["votes"] = votes
  
def parse_house_vote(dom, vote):
  def parse_date(d):
    return datetime.datetime.strptime(d, "%d-%b-%Y %I:%M %p")

  vote["date"] = parse_date(str(dom.xpath("string(vote-metadata/action-date)")) + " " + str(dom.xpath("string(vote-metadata/action-time)")))
  vote["question"] = unicode(dom.xpath("string(vote-metadata/vote-question)"))
  vote["type_text"] = unicode(dom.xpath("string(vote-metadata/vote-question)"))
  vote["subject"] = unicode(dom.xpath("string(vote-metadata/vote-desc)"))
  
  vote_types = { "YEA-AND-NAY": "1/2", "2/3 YEA-AND-NAY": "2/3", "3/5 YEA-AND-NAY": "3/5", "1/2": "1/2", "2/3" : "2/3", "QUORUM": "QUORUM", "RECORDED VOTE" : "1/2", "2/3 RECORDED VOTE": "2/3", "3/5 RECORDED VOTE": "3/5" }
  vote["requires"] = vote_types.get(str(dom.xpath("string(vote-metadata/vote-type)")), "unknown")
  
  vote["result_text"] = unicode(dom.xpath("string(vote-metadata/vote-result)"))
  vote["result"] = unicode(dom.xpath("string(vote-metadata/vote-result)"))
  
  if unicode(dom.xpath("string(vote-metadata/legis-num)")):
    bill_types = { "S": "s", "S Con Res": "sconres", "S J Res": "sjres", "S Res": "sres", "H R": "hr", "H Con Res": "hconres", "H J Res": "hjres", "H Res": "hres" }
    bill_type, bill_number = unicode(dom.xpath("string(vote-metadata/legis-num)")).rsplit(" ", 1)
    vote["bill"] = {
      "congress": vote["congress"],
      "type": bill_types[bill_type],
      "number": int(bill_number),
    }
    
  # Count up the votes.
  votes = { } # by vote type
  def add_vote(vote, voter):
    if vote == "Present, Giving Live Pair": vote = "Present"
    votes.setdefault(vote, []).append(voter)
  
  # Ensure the options are noted, even if no one votes that way.
  if unicode(dom.xpath("string(vote_question)")) == "Guilty or Not Guilty":
    votes['Guilty'] = []
    votes['Not Guilty'] = []
  else:
    votes['Yea'] = []
    votes['Nay'] = []
  votes['Present'] = []
  votes['Not Voting'] = []
  
  # VP tie-breaker?
  if str(dom.xpath("string(tie_breaker/by_whom)")):
    add_vote(str(dom.xpath("string(tie_breaker/tie_breaker_vote)")), "VP")
    
  for member in dom.xpath("members/member"):
    # LIS ID, prefixed with "S" --- remove the "S"
    who = str(member.xpath("string(lis_member_id)"))
    who = who.replace("S", "")
    who = int(who)
    
    add_vote(str(member.xpath("string(vote_cast)")), who)
      
  vote["votes"] = votes

