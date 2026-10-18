import datetime as dt
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tiktok14_clock as clock
from test_tiktok14_worker import fixture, NOW

class ClockTests(unittest.TestCase):
 def test_confirmed_creation_rejection_waits_without_blocking_forever(self):
  state=fixture()[0]
  state['last_send_rejection']={'retry_after':(NOW+dt.timedelta(hours=1)).isoformat()}
  self.assertEqual(clock.plan(state,[],NOW),'send_cooldown')
  self.assertEqual(clock.plan(state,[],NOW+dt.timedelta(hours=1)),'dispatch_auto')

 def test_long_outage_reconciliation_waits_an_hour_without_using_buffer(self):
  current=NOW+dt.timedelta(hours=3)
  attempt={'status':'pending','reserved_at':NOW.isoformat(),'last_reconcile_at':(current-dt.timedelta(minutes=5)).isoformat()}
  state={'queue':[],'attempts':[attempt]}
  self.assertEqual(clock.plan(state,[],current),'reconciliation_backoff')
  self.assertEqual(clock.plan(state,[],current+dt.timedelta(minutes=55)),'dispatch_reconcile')

 def test_fifteen_berlin_hours_and_dst_boundaries(self):
  for day in ('2026-10-18','2026-10-25','2027-03-28'):
   hours=[]
   for hour in range(24):
    t=dt.datetime.fromisoformat(f'{day}T{hour:02}:00:00+00:00')
    if clock.send_window(t):hours.append(t.astimezone(clock.BERLIN).hour)
   self.assertEqual(hours,list(range(9,24)))
 def test_pending_send_reconciles_outside_post_window(self):
  state=fixture()[0];state['attempts']=[{'status':'pending','reserved_at':NOW.isoformat()}]
  self.assertEqual(clock.plan(state,[],NOW.replace(hour=1)),'dispatch_reconcile')
 def test_worker_enforces_window_even_for_direct_manual_auto_run(self):
  from test_tiktok14_worker import MemoryState,Gateway
  from tiktok14_worker import Worker
  state,config,_,overview=fixture();store=MemoryState(state);gateway=Gateway(store,overview)
  self.assertEqual(Worker(store,gateway,lambda _:True).run_one(config,None,NOW.replace(hour=1)),'outside_window')
  self.assertEqual(gateway.sent,[])
 def test_no_new_posts_before_nine_or_after_23(self):
  for hour in (0,3,5,22,23):
   self.assertEqual(clock.plan(fixture()[0],[],NOW.replace(hour=hour)),'outside_window')
 def test_active_main_publisher_suppresses_dispatch(self):
  runs=[{'head_branch':'main','status':'queued','event':'workflow_dispatch'}]
  self.assertEqual(clock.plan(fixture()[0],runs,NOW),'active_publisher')
 def test_tick_checks_held_publishers_before_dispatch(self):
  import base64,json
  class API:
   def __init__(self):self.paths=[]
   def call(self,method,path,body=None):
    self.paths.append(path)
    if method!='GET':raise AssertionError('held publisher must suppress dispatch')
    if '/contents/' in path:return {'content':base64.b64encode(json.dumps({'queue':[],'attempts':[]}).encode()).decode()}
    return {'workflow_runs':[{'head_branch':'main','status':'waiting'}] if 'status=waiting&' in path else [],'total_count':1 if 'status=waiting&' in path else 0}
  api=API()
  self.assertEqual(clock.tick(api,NOW),'active_publisher')
  for status in clock.ACTIVE:self.assertTrue(any('status='+status+'&' in path for path in api.paths))
 def test_spring_forward_preserves_strict_rolling_cap(self):
  state={'queue':[],'attempts':[]}
  for hour in range(9,24):
   local=dt.datetime(2027,3,27,hour,tzinfo=clock.BERLIN)
   state['attempts'].append({'status':'verified_public','reserved_at':local.astimezone(dt.timezone.utc).isoformat()})
  current=dt.datetime(2027,3,28,9,tzinfo=clock.BERLIN).astimezone(dt.timezone.utc)
  self.assertEqual(clock.plan(state,[],current),'daily_limit')
  self.assertEqual(clock.plan(state,[],current+dt.timedelta(hours=1)),'dispatch_auto')
 def test_lost_dispatch_is_not_retried_in_same_tick(self):
  class API:
   def __init__(self):self.sends=0
   def call(self,method,path,body=None):
    if method=='POST':self.sends+=1;raise clock.ServiceError('transport_error')
    if '/contents/' in path:
     import base64,json
     return {'content':base64.b64encode(json.dumps({'queue':[],'attempts':[]}).encode()).decode()}
    return {'workflow_runs':[]}
  api=API()
  with self.assertRaises(clock.ServiceError):clock.tick(api,NOW)
  self.assertEqual(api.sends,1)
 def test_old_unreviewed_candidate_gets_a_qa_opportunity(self):
  state=fixture()[0];state['queue'][0].pop('media_review',None)
  self.assertEqual(clock.plan(state,[],NOW),'dispatch_auto')
 def test_automatic_quality_gate_requires_explicit_live_commissioning(self):
  state=fixture()[0];state['queue'][0]['media_review']={'version':2}
  state['last_commissioning_hour']=NOW.strftime('%Y-%m-%dT%H')
  self.assertEqual(clock.plan(state,[],NOW),'awaiting_commissioning')
  self.assertEqual(clock.plan(state,[],NOW+dt.timedelta(hours=1)),'dispatch_auto')
 def test_hour_complete_still_allows_pending_reconciliation(self):
  state=fixture()[0];state['attempts']=[{'status':'verified_public','reserved_at':NOW.isoformat()}]
  self.assertEqual(clock.plan(state,[],NOW),'hour_complete')
  state['attempts'][0]['status']='pending'
  self.assertEqual(clock.plan(state,[],NOW),'dispatch_reconcile')
 def test_one_prefetch_after_verified_send_prepares_next_slot(self):
  state=fixture()[0];state['queue']=[]
  state['attempts']=[{'status':'verified_public','reserved_at':NOW.isoformat()}]
  self.assertEqual(clock.plan(state,[],NOW),'dispatch_prefetch')
  state['last_prefetch_hour']=NOW.strftime('%Y-%m-%dT%H')
  self.assertEqual(clock.plan(state,[],NOW),'hour_complete')
 def test_morning_prefetch_does_not_authorize_an_early_post(self):
  current=NOW.replace(hour=6,minute=35);state=fixture()[0];state['queue']=[]
  self.assertEqual(current.astimezone(clock.BERLIN).hour,8)
  self.assertEqual(clock.plan(state,[],current),'dispatch_prefetch')
 def test_next_tick_never_misses_hour_boundary(self):
  t=NOW.replace(minute=59,second=50)
  self.assertLessEqual(clock.delay(t),10)
  self.assertLessEqual(clock.delay(NOW),120)
 def test_no_new_dispatch_after_fifteen_durable_sends(self):
  state=fixture()[0]
  state['attempts']=[{'status':'verified_public','reserved_at':(NOW-dt.timedelta(minutes=i*61+60)).isoformat()} for i in range(15)]
  self.assertEqual(clock.plan(state,[],NOW),'daily_limit')
if __name__=='__main__':unittest.main()
