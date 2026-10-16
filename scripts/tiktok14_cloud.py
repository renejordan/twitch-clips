"""GitHub-only production and Buffer delivery. No Metricool access or cookies."""
import base64
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

import tiktok14_prepare as producer
from tiktok14_publish import eligible, parse_timestamp, stamp, REPO_PREFIX
from tiktok14_services import (BufferGateway, GitHubAPI, GitHubState, NoRedirect,
                               ServiceError, verify_public)
from tiktok14_worker import Worker, counted_events, sources

REPOSITORY='renejordan/twitch-clips'
TEST_URL='https://www.tiktok.com/@ufo3103/video/7697189362877992225'
CONFIG=Path('scripts/tiktok14_config.json')
MAX_MEDIA=128*1024*1024


class ProductionInterrupted(BaseException):
    """Escape the legacy producer's ordinary per-candidate Exception handler."""


def initial_state():
    return {'version':1,'queue':[],'attempts':[{
        'clip_id':'761785150',
        'clip_slug':'SpicyLuckyCodDeIlluminati-YapuNSUEQJCM8URt',
        'reserved_at':'2026-10-16T09:05:16Z',
        'status':'verified_public','buffer_post_id':'6ad1e7e9e7970040db23ebed',
        'sent_at':'2026-10-16T09:07:25Z','tiktok_url':TEST_URL,
        'verified_at':'2026-10-16T09:14:20Z'}]}


def ensure_store(github):
    store=GitHubState(github)
    try:
        github.call('GET','/git/ref/heads/tiktok14-state')
    except ServiceError as error:
        if str(error) != 'github_http_404': raise
        if not verify_public(TEST_URL): raise ServiceError('first_test_not_public')
        store.initialize(initial_state())
    # An existing but corrupt/inaccessible branch must never be initialized over.
    store.load()
    return store


def legacy_ids(data):
    if (not isinstance(data,dict) or not isinstance(data.get('processed_ids'),list)
            or not isinstance(data.get('created'),list)):
        raise ServiceError('invalid_auto20_state')
    used=set(map(str,data['processed_ids']))
    for row in data['created']:
        if not isinstance(row,dict): raise ServiceError('invalid_auto20_record')
        used.update(str(row.get(key,'')) for key in ('clip_id','clip_slug'))
        url=row.get('source_url','')
        if isinstance(url,str) and re.fullmatch(r'https://(?:www\.)?twitch\.tv/[^/]+/clip/[^/?#]+|https://clips\.twitch\.tv/[^/?#]+',url):
            used.add(url.rsplit('/',1)[1])
    return used


def read_legacy(github):
    raw=github.call('GET','/contents/state/auto20.json?ref=main')
    try:
        if raw['encoding'] != 'base64': raise ValueError()
        data=json.loads(base64.b64decode(raw['content'],validate=False))
        legacy_ids(data)
        return data
    except (KeyError,ValueError,TypeError):
        raise ServiceError('invalid_auto20_response') from None


def legacy_running(github):
    data=github.call('GET','/actions/workflows/tiktok.yml/runs?status=in_progress&per_page=1')
    count=data.get('total_count')
    if type(count) is not int or count<0: raise ServiceError('invalid_auto20_run_status')
    return count>0


def child_environment():
    allowed=('PATH','HOME','USERPROFILE','SYSTEMROOT','WINDIR','TEMP','TMP',
             'LANG','LC_ALL','TZ','SSL_CERT_FILE','SSL_CERT_DIR',
             'PYTHONPATH','VIRTUAL_ENV','LD_LIBRARY_PATH')
    result={key:value for key,value in os.environ.items() if key in allowed}
    result['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
    result['PYTHONUNBUFFERED']='1'
    return result


def run_media(command,check=True,**kwargs):
    if not command or command[0] not in ('yt-dlp','ffmpeg','ffprobe'):
        raise ServiceError('unexpected_media_tool')
    kwargs.pop('capture_output',None)
    result=subprocess.run(command,check=False,text=True,capture_output=True,
                          env=child_environment(),**kwargs)
    if check and result.returncode: raise ServiceError('media_tool_failed')
    return result


def producer_namespace():
    with contextlib.redirect_stdout(io.StringIO()): producer.generate()
    namespace={'__name__':'tiktok14_isolated_producer'}
    exec(compile(producer.SCRIPT.read_text(encoding='utf-8'),str(producer.SCRIPT),'exec'),namespace)
    namespace['run']=run_media
    return namespace


class Host:
    def __init__(self,token): self.token=token

    def command(self,args,check=True):
        env=child_environment()
        env['GH_TOKEN']=self.token
        result=subprocess.run(['gh',*args,'-R',REPOSITORY],env=env,
            capture_output=True,text=True,timeout=120,check=False)
        if check and result.returncode: raise ServiceError('github_media_host_failed')
        return result

    def __call__(self,clip,video,cover,current):
        digest=hashlib.sha256(video.read_bytes()).hexdigest()
        if video.stat().st_size > MAX_MEDIA: raise ServiceError('media_too_large')
        name=clip['channel_login']+'-'+clip['id']+'-'+digest[:12]
        if not re.fullmatch('[a-z0-9_]+-[A-Za-z0-9_-]+-[a-f0-9]{12}',name):
            raise ServiceError('invalid_media_name')
        movie=video.parent/(name+'.mp4')
        thumb=video.parent/(name+'-cover.jpg')
        movie.write_bytes(video.read_bytes())
        thumb.write_bytes(cover.read_bytes())
        tag='tiktok14-'+current.strftime('%Y-%m')
        if self.command(['release','view',tag],check=False).returncode:
            self.command(['release','create',tag,'--target','main','--title',
                          'TikTok14 '+current.strftime('%Y-%m'),'--notes',
                          'Separat vorbereitete Gaming-Clips fuer TikTok14.'])
        # Never replace existing media. Unknown hosting outcomes cannot overwrite it.
        self.command(['release','upload',tag,str(movie),str(thumb)])
        prefix=REPO_PREFIX+current.strftime('%Y-%m')+'/'
        return prefix+movie.name,prefix+thumb.name,digest


def prepare(store,config,legacy,current,host):
    permitted=sources(config)
    old=legacy_ids(legacy)
    state,sha=store.load()
    if any(row.get('status')!='verified_public' for row in state['attempts']):
        return 'pending'
    if counted_events(state,{},[],current)>=14: return 'limit'
    if state['queue']:
        item=state['queue'][0]
        if (eligible(item,current) and item.get('streamer') in permitted and
                not {item['clip_id'],item.get('clip_slug','')} & old):
            return 'ready'
        state.setdefault('rejected',[]).extend(state['queue'])
        state['queue']=[]
        sha=store.save(state,sha)
    namespace=producer_namespace()
    namespace['STREAMERS']=list(config['sources'])
    namespace['RANK']={name:index+1 for index,name in enumerate(config['sources'])}
    namespace['now_utc']=lambda:current
    records=copy.deepcopy(state.get('rejected',[]))
    records += [dict(row,created_at=row.get('created_at',row['reserved_at']))
                for row in state['attempts']]
    processed=set(old)
    for row in records:
        processed.update(str(row.get(key,'')) for key in ('clip_id','clip_slug'))
    namespace['read_state']=lambda:{'version':2,'created':copy.deepcopy(records),
                                    'processed_ids':list(processed)}
    receipts={}
    def release(clip,movie,cover,now):
        try:
            url,thumbnail,digest=host(clip,movie,cover,now)
        except Exception:
            raise ProductionInterrupted('media_host_failed') from None
        receipts[url]=digest
        return url,thumbnail
    def persist(data):
        nonlocal sha
        record=copy.deepcopy(data['created'][-1])
        digest=receipts.get(record.get('video_url'))
        if not digest: raise ServiceError('unverified_production_receipt')
        record.update(sha256=digest,rights_status='user_declared_source_list')
        candidate=copy.deepcopy(state)
        candidate['queue']=[record]
        try:
            new_sha=store.save(candidate,sha)
        except Exception:
            raise ProductionInterrupted('production_state_write_failed') from None
        state.clear()
        state.update(candidate)
        sha=new_sha
    namespace['release']=release
    namespace['save_state']=persist
    # Legacy media code may emit extraction details. Never expose its raw output.
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        try:
            namespace['main']()
        except ProductionInterrupted as error:
            raise ServiceError(str(error)) from None
    return 'ready' if state['queue'] else 'empty'


def allowed_media_redirect(url):
    parsed=urlsplit(url)
    return (parsed.scheme=='https' and parsed.netloc in
            ('release-assets.githubusercontent.com','objects.githubusercontent.com'))


def verify_media(url,digest):
    if (not isinstance(url,str) or not re.fullmatch(re.escape(REPO_PREFIX)+
            r'\d{4}-(?:0[1-9]|1[0-2])/[A-Za-z0-9_-]+\.mp4',url)
            or not re.fullmatch('[a-f0-9]{64}',str(digest))):
        raise ServiceError('invalid_media_reference')
    opener=build_opener(NoRedirect())
    for _ in range(6):
        try:
            with opener.open(Request(url,headers={'User-Agent':'TikTok14/1.0'}),timeout=30) as response:
                hasher=hashlib.sha256()
                total=0
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk: break
                    total+=len(chunk)
                    if total>MAX_MEDIA: raise ServiceError('media_too_large')
                    hasher.update(chunk)
                if total<1024 or hasher.hexdigest()!=digest:
                    raise ServiceError('media_hash_mismatch')
                return True
        except HTTPError as error:
            if error.code not in (301,302,303,307,308):
                raise ServiceError('public_media_unavailable') from None
            target=error.headers.get('Location','')
            if not allowed_media_redirect(target): raise ServiceError('unapproved_media_redirect') from None
            url=target
        except ServiceError: raise
        except Exception: raise ServiceError('public_media_transport_failed') from None
    raise ServiceError('too_many_media_redirects')


def publish(store,config,github,key):
    state,sha=store.load()
    pending=any(row.get('status')!='verified_public' for row in state['attempts'])
    if not pending:
        if legacy_running(github): return 'auto20_running'
        if not state['queue']: return 'empty'
        item=state['queue'][0]
        old=legacy_ids(read_legacy(github))
        if {item['clip_id'],item.get('clip_slug','')} & old:
            state.setdefault('rejected',[]).extend(state['queue'])
            state['queue']=[]
            store.save(state,sha)
            return 'known_auto20_duplicate_skipped'
        if not eligible(item,dt.datetime.now(dt.timezone.utc)):
            raise ServiceError('queued_clip_expired')
        verify_media(item['video_url'],item.get('sha256'))
    gateway=BufferGateway(key)
    worker=Worker(store,gateway,verify_public)
    result=worker.run_one(config,None,dt.datetime.now(dt.timezone.utc))
    for _ in range(3):
        if result not in ('pending','unverified'): break
        time.sleep(60)
        result=worker.run_one(config,None,dt.datetime.now(dt.timezone.utc))
    if result=='verified_public':
        final,_=store.load()
        print('TikTok verified: '+final['attempts'][-1]['tiktok_url'])
    return result


def main(action=None):
    action=action or (sys.argv[1] if len(sys.argv)>1 else '')
    token=os.environ.pop('GH_TOKEN','')
    key=os.environ.pop('BUFFER_API_KEY','')
    os.environ.pop('GITHUB_TOKEN',None)
    try:
        ref=os.getenv('GITHUB_REF','')
        if (os.getenv('GITHUB_REPOSITORY')!=REPOSITORY or
                ref not in ('refs/heads/main','refs/heads/codex/tiktok14-safety-audit') or
                action not in ('prepare','publish') or
                (action=='publish' and ref!='refs/heads/main')):
            raise ServiceError('unapproved_cloud_context')
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        if config.get('accounting_mode')!='independent':
            raise ServiceError('independent_mode_not_configured')
        sources(config)
        github=GitHubAPI(token)
        if action=='prepare':
            store=ensure_store(github)
            result=('auto20_running' if legacy_running(github) else
                    prepare(store,config,read_legacy(github),
                            dt.datetime.now(dt.timezone.utc),Host(token)))
        else:
            result=publish(GitHubState(github),config,github,key)
        print('TikTok14 '+action+': '+result)
        return 0 if result not in ('unresolved','unverified') else 1
    except ServiceError as error:
        code=str(error)
        print('STOP: '+(code if re.fullmatch('[a-z0-9_]+',code) else 'cloud_check_failed'))
        return 1
    except Exception:
        print('STOP: cloud_operation_failed; no server details or credentials logged')
        return 1


if __name__=='__main__': raise SystemExit(main())
