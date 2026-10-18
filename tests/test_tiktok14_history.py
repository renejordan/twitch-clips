import datetime as dt,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_history import compact
from test_tiktok14_worker import fixture,NOW,MemoryState,Gateway
from tiktok14_worker import Worker
from tiktok14_services import ServiceError
from tiktok14_quality import nearby_event

class HistoryTests(unittest.TestCase):
 def test_different_clip_ids_from_same_stream_moment_are_excluded(self):
  first={'clip_id':'1461286141','streamer':'krokoboss','original_created_at':'2026-10-17T20:39:52Z'}
  second={'clip_id':'2582959067','channel_login':'krokoboss','original_created_at':'2026-10-17T20:39:37Z'}
  self.assertTrue(nearby_event(first,second))
  second['original_created_at']='2026-10-17T20:45:00Z';self.assertFalse(nearby_event(first,second))
  second.update(channel_login='papaplatte',original_created_at=first['original_created_at']);self.assertFalse(nearby_event(first,second))
 def test_old_verified_records_shrink_but_unresolved_and_recent_records_remain(self):
  old=(NOW-dt.timedelta(days=8)).isoformat()
  state={'queue':[],'attempts':[{'clip_id':'12345','status':'verified_public','reserved_at':old},
   {'clip_id':'54321','status':'unknown','reserved_at':old},
   {'clip_id':'67890','status':'verified_public','reserved_at':NOW.isoformat()}]}
  self.assertTrue(compact(state,NOW))
  self.assertEqual(state['used_ids'],['12345'])
  self.assertEqual([x['clip_id'] for x in state['attempts']],['54321','67890'])
  self.assertEqual(state['archived_verified_count'],1)
  self.assertFalse(compact(state,NOW))
 def test_permanent_identity_prevents_reposting_after_compaction(self):
  state,config,_,overview=fixture();state['used_ids']=[state['queue'][0]['clip_id']]
  config['accounting_mode']='independent'
  store=MemoryState(state);gateway=Gateway(store,overview)
  with self.assertRaisesRegex(ServiceError,'duplicate_clip'):Worker(store,gateway,lambda _:True).run_one(config,None,NOW)
  self.assertEqual(gateway.sent,[])
if __name__=='__main__':unittest.main()
