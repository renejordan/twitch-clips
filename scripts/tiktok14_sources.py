"""Daily TwitchTracker German top 50, with a durable last-known-good fallback."""
import copy
import datetime as dt
import re
from urllib.request import Request,build_opener
from tiktok14_services import NoRedirect,ServiceError

URL='https://twitchtracker.com/channels/ranking/german'

def valid(names):
 return (isinstance(names,list) and len(names)==50 and
  all(isinstance(name,str) and re.fullmatch('[a-z0-9_]{3,25}',name) for name in names) and len(set(names))==50)

def parse_ranking(html):
 if 'German language' not in html:raise ServiceError('ranking_language_unverified')
 ranks={}
 for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',html,re.S|re.I):
  rank=re.search(r'<td\b[^>]*>\s*#(\d+)\s*</td>',row,re.I)
  channel=re.search(r'href="/([A-Za-z0-9_]{3,25})"',row)
  if rank and channel and 1<=int(rank[1])<=50:
   if int(rank[1]) in ranks:raise ServiceError('ranking_duplicate_rank')
   ranks[int(rank[1])]=channel[1].lower()
 names=[ranks[i] for i in range(1,51)] if set(ranks)==set(range(1,51)) else []
 if not valid(names):raise ServiceError('ranking_incomplete')
 return names

def fetch_ranking():
 with build_opener(NoRedirect()).open(Request(URL,headers={'User-Agent':'TikTok14 clip source refresh/1.0'}),timeout=20) as response:
  raw=response.read(2*1024*1024+1)
 if len(raw)>2*1024*1024:raise ServiceError('ranking_response_too_large')
 return parse_ranking(raw.decode('utf-8'))

def resolve(config,state,current,refresh=False,fetch=None):
 if config.get('source_selection')!='twitchtracker_german_top50':return config,False
 result=copy.deepcopy(config);cache=state.get('source_ranking',{})
 names=cache.get('sources') if valid(cache.get('sources')) else config['sources']
 changed=False
 if refresh and str(cache.get('checked_at',''))[:10]!=current.date().isoformat():
  stamp=current.isoformat();updated={'source_url':URL,'checked_at':stamp,'sources':names,
   'fetched_at':cache.get('fetched_at',config.get('source_snapshot_at'))}
  try:
   candidate=(fetch or fetch_ranking)()
   if not valid(candidate):raise ServiceError('ranking_incomplete')
   names=candidate
   updated.update(sources=names,fetched_at=stamp,result='fresh')
  except Exception:updated.update(result='cached_fallback')
  state['source_ranking']=updated;changed=True
 result['sources']=names
 return result,changed
