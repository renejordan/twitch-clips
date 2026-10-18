"""External scheduler entry: plan by default, --dispatch requires Actions:write.

Run every 20 minutes on an always-on scheduler. Use a repository-scoped token
in GH_TOKEN, never in a URL. No scheduler/credential is provisioned by this file.
The workflow's state CAS and hourly journal remain the final idempotency guard.
"""
import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path

from tiktok14_publish import eligible,parse_timestamp
from tiktok14_services import GITHUB_URL,request_json,ServiceError


def decision(state,runs,current):
    if not isinstance(state.get('queue'),list) or not isinstance(state.get('attempts'),list):
        raise ServiceError('invalid_dispatch_state')
    if any(run.get('head_branch')=='main' and run.get('status') in
            ('queued','in_progress','waiting','pending','requested') and
            run.get('event') in ('schedule','workflow_dispatch') for run in runs):
        return 'active_run'
    if any(row.get('status')!='verified_public' for row in state['attempts']): return 'dispatch'
    slot=current.strftime('%Y-%m-%dT%H')
    if any(parse_timestamp(row['reserved_at']).strftime('%Y-%m-%dT%H')==slot for row in state['attempts']):
        return 'hour_complete'
    if state['queue']:
        if eligible(state['queue'][0],current): return 'dispatch'
        age=(current-parse_timestamp(state['queue'][0]['original_created_at'])).total_seconds()
        if 0<=age<=72*3600: return 'needs_review'
    return 'hour_complete' if state.get('last_prepare_hour')==slot else 'dispatch'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dispatch',action='store_true',help='actually dispatch main in safe automatic mode')
    args=parser.parse_args()
    token=os.environ.pop('GH_TOKEN','')
    try:
        raw=request_json(GITHUB_URL+'/contents/state.json?ref=tiktok14-state',token or None)
        state=json.loads(base64.b64decode(raw['content']))
        runs=request_json(GITHUB_URL+'/actions/workflows/tiktok14.yml/runs?per_page=100',token or None)
        result=decision(state,runs['workflow_runs'],dt.datetime.now(dt.timezone.utc))
        print('TikTok dispatcher: '+result+(' (plan only)' if not args.dispatch else ''))
        if result!='dispatch' or not args.dispatch: return 0
        if not token: raise ServiceError('dispatch_actions_write_credential_required')
        # Never retry a lost dispatch response. The next scheduler tick checks
        # active runs and durable state before deciding whether another is needed.
        request_json(GITHUB_URL+'/actions/workflows/tiktok14.yml/dispatches',token,'POST',
                     {'ref':'main','inputs':{'mode':'auto'}})
        print('TikTok dispatcher: accepted; verify the Actions run separately')
        return 0
    except ServiceError as error:
        print('STOP: '+str(error)); return 1
    except Exception:
        print('STOP: dispatch_response_invalid'); return 1


if __name__=='__main__': raise SystemExit(main())
