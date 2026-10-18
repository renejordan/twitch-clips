import datetime as dt
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_sources import parse_ranking,resolve
from tiktok14_services import ServiceError

class SourceRankingTests(unittest.TestCase):
 def names(self,prefix='channel'):return [prefix+str(i) for i in range(50)]
 def test_current_german_ranks_are_ordered_and_incomplete_results_rejected(self):
  rows=['<tr><td>#'+str(i+1)+'</td><td><a href="/'+name+'">Name</a></td></tr>' for i,name in enumerate(self.names())]
  self.assertEqual(parse_ranking('German language'+''.join(reversed(rows))),self.names())
  for text in ['English language'+''.join(rows),'German language'+''.join(rows[:-1])]:
   with self.assertRaises(ServiceError):parse_ranking(text)
 def test_daily_refresh_is_durable_and_outage_uses_last_success(self):
  now=dt.datetime(2026,10,18,tzinfo=dt.timezone.utc)
  config={'sources':self.names(),'source_selection':'twitchtracker_german_top50'};state={}
  result,changed=resolve(config,state,now,True,lambda:self.names('new'))
  self.assertTrue(changed);self.assertEqual(result['sources'],self.names('new'))
  def unavailable():raise OSError('offline')
  result,changed=resolve(config,state,now,True,unavailable)
  self.assertFalse(changed)
  result,changed=resolve(config,state,now+dt.timedelta(days=1),True,unavailable)
  self.assertTrue(changed);self.assertEqual(result['sources'],self.names('new'))
  self.assertEqual(state['source_ranking']['result'],'cached_fallback')
  self.assertEqual(config['sources'],self.names())
 def test_publish_reads_same_cached_ranking_without_network(self):
  now=dt.datetime.now(dt.timezone.utc);state={'source_ranking':{'sources':self.names('new')}}
  config={'sources':self.names(),'source_selection':'twitchtracker_german_top50'}
  result,changed=resolve(config,state,now)
  self.assertFalse(changed);self.assertEqual(result['sources'],self.names('new'))
