"""Free GitHub heartbeat: one clock, existing publisher, no Buffer credential.

A bounded five-hour clock hands off to a successor while its job token is alive.
Native cron remains a recovery watchdog. --run is main-only; default is read-only.
"""
import argparse
import base64
import datetime as dt
import json
import os
import time
from zoneinfo import ZoneInfo
from tiktok14_services import GitHubAPI, ServiceError,request_json,GITHUB_URL
from tiktok14_publish import parse_timestamp,posting_time
from tiktok14_worker import reconciliation_due

BERLIN=ZoneInfo('Europe/Berlin')
ACTIVE={'queued','in_progress','waiting','pending','requested'}

class PublicReadOnly:
 def call(self,method,path,body=None):
  if method!='GET' or body is not None:raise ServiceError('clock_read_only')
  return request_json(GITHUB_URL+path)

def send_window(current):
 if current.tzinfo is None:raise ServiceError('clock_timezone_required')
 return posting_time(current)

def plan(state,runs,current):
 if not isinstance(state.get('attempts'),list) or not isinstance(state.get('queue'),list):
  raise ServiceError('invalid_clock_state')
 if any(r.get('head_branch')=='main' and r.get('status') in ACTIVE for r in runs):return 'active_publisher'
 unresolved=[a for a in state['attempts'] if a.get('status')!='verified_public']
 if unresolved:return 'dispatch_reconcile' if reconciliation_due(unresolved[0],current) else 'reconciliation_backoff'
 slot=current.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H')
 local=current.astimezone(BERLIN)
 scans=state.get('prepare_scans',{})
 if not state['queue'] and scans.get('hour')==slot and scans.get('count',0)>=3:return 'scan_budget_exhausted'
 if not send_window(current):
  if local.hour==8 and local.minute>=30 and not state['queue'] and state.get('last_prepare_hour')!=slot:return 'dispatch_prefetch'
  return 'outside_window'
 if state['queue'] and state.get('last_commissioning_hour')==slot:return 'awaiting_commissioning'
 if any(parse_timestamp(a['reserved_at']).strftime('%Y-%m-%dT%H')==slot for a in state['attempts']):
  if local.hour<23 and not state['queue'] and state.get('last_prefetch_hour')!=slot:return 'dispatch_prefetch'
  return 'hour_complete'
 moments=[max(parse_timestamp(a['reserved_at']),parse_timestamp(a.get('sent_at',a['reserved_at']))) for a in state['attempts']]
 if any(t>current for t in moments):raise ServiceError('future_clock_attempt')
 local_day=current.astimezone(BERLIN).date()
 if sum((current-t).total_seconds()<86400 or t.astimezone(BERLIN).date()==local_day for t in moments)>=15:return 'daily_limit'
 if not state['queue'] and state.get('last_prepare_hour')==slot:return 'scan_complete'
 return 'dispatch_auto'

def delay(current):
 # Two-minute reconciliation opportunities; an hourly boundary is never slept over.
 return max(1,min(120,3600-current.minute*60-current.second-current.microsecond/1e6))

def tick(api,current,dispatch=True):
 raw=api.call('GET','/contents/state.json?ref=tiktok14-state')
 try:state=json.loads(base64.b64decode(raw['content']))
 except (KeyError,ValueError,TypeError):raise ServiceError('invalid_clock_state') from None
 runs=[]
 for status in sorted(ACTIVE):
  response=api.call('GET','/actions/workflows/tiktok14.yml/runs?branch=main&status='+status+'&per_page=100')
  if not isinstance(response.get('workflow_runs'),list):raise ServiceError('invalid_clock_runs')
  if response.get('total_count',len(response['workflow_runs']))>100:raise ServiceError('clock_runs_incomplete')
  runs.extend(response['workflow_runs'])
 result=plan(state,runs,current)
 if dispatch and result.startswith('dispatch_'):
  # Never retry an uncertain POST here. Next tick re-reads live runs and journal.
  mode={'dispatch_prefetch':'prefetch','dispatch_reconcile':'reconcile'}.get(result,'auto')
  api.call('POST','/actions/workflows/tiktok14.yml/dispatches',{'ref':'main','inputs':{'mode':mode}})
 return result

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--run',action='store_true')
 parser.add_argument('--hours',type=float,default=None)
 args=parser.parse_args()
 token=os.environ.pop('GH_TOKEN','')
 try:
  if args.hours is None:args.hours=float(os.environ.pop('TIKTOK14_CLOCK_MINUTES','300'))/60
  if not 0<args.hours<=5:raise ServiceError('invalid_clock_duration')
  if args.run and (os.getenv('GITHUB_REPOSITORY')!='renejordan/twitch-clips' or
      os.getenv('GITHUB_REF')!='refs/heads/main' or not token):raise ServiceError('unapproved_clock_context')
  api=GitHubAPI(token) if token else PublicReadOnly()
  deadline=time.monotonic()+args.hours*3600
  previous=None
  while True:
   current=dt.datetime.now(dt.timezone.utc)
   try:result=tick(api,current,dispatch=args.run)
   except ServiceError as error:
    if str(error) in ('github_http_401','github_http_403'):raise
    result='retry_later_'+str(error)
   if result!=previous or result.startswith('dispatch_'):
    print(current.isoformat()+' clock: '+result,flush=True)
    previous=result
   if not args.run:return 0
   remaining=deadline-time.monotonic()
   if remaining<=0:break
   time.sleep(min(delay(current),remaining))
  # Current job's short-lived token is still valid. One successor, never a loop of POST retries.
  api.call('POST','/actions/workflows/tiktok14_clock.yml/dispatches',{'ref':'main','inputs':{'duration_minutes':'300'}})
  print('clock: successor_dispatch_accepted',flush=True)
  return 0
 except ServiceError as error:
  print('STOP: '+str(error),flush=True);return 1
 except Exception:
  print('STOP: clock_operation_failed',flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
