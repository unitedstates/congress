import utils
from utils import log


def run(options):
  
  year = options.get('year', current_session())
  print year