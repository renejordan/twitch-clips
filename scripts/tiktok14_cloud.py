"""GitHub-only production and Buffer delivery. No Metricool access or cookies."""
import base64
import contextlib
import concurrent.futures
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
import zipfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

import tiktok14_prepare as producer
from tiktok14_publish import eligible, parse_timestamp, stamp, REPO_PREFIX, MAX_PER_DAY, MAX_SEND_AGE_HOURS,LOCAL_ZONE
from tiktok14_quality import identities, blocked, review_error,nearby_event
from tiktok14_media import configure as configure_media
from tiktok14_services import (BufferGateway, GitHubAPI, GitHubState, NoRedirect,
                               ServiceError, verify_public, ProductionInterrupted,QualityRejected)
from tiktok14_worker import Worker, counted_events, sources
from tiktok14_history import compact as compact_history

REPOSITORY='renejordan/twitch-clips'
TEST_URL='https://www.tiktok.com/@ufo3103/video/7697189362877992225'
CONFIG=Path('scripts/tiktok14_config.json')
MAX_MEDIA=128*1024*1024


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
        # The initial one-post commissioning seed is no longer complete history.
        # Restore the existing journal; never erase deduplication after deletion.
        raise ServiceError('state_branch_missing_restore_required') from None
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
        used.update(identities(row))
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
    for status in ('in_progress','queued','waiting','pending'):
        data=github.call('GET','/actions/workflows/tiktok.yml/runs?status='+status+'&per_page=1')
        count=data.get('total_count')
        if type(count) is not int or count<0: raise ServiceError('invalid_auto20_run_status')
        if count: return True
    return False


def assert_single_route(github,config):
    if set(config['sources']) & set(config['legacy_sources']):
        workflow=github.call('GET','/actions/workflows/tiktok.yml')
        if workflow.get('state')!='disabled_manually':
            raise ServiceError('overlapping_auto20_route_must_be_retired')


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
    namespace['_report']={}
    configure_media(namespace,namespace['_report'])
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
        if clip.get('_qa_receipt') and clip['_qa_receipt'].get('media_sha256')!=digest:raise ServiceError('qa_media_changed_before_host')
        if video.stat().st_size > MAX_MEDIA: raise ServiceError('media_too_large')
        name=clip['channel_login']+'-'+clip['id']+'-'+digest[:12]
        if not re.fullmatch('[a-z0-9_]+-[A-Za-z0-9_-]+-[a-f0-9]{12}',name):
            raise ServiceError('invalid_media_name')
        movie=video.parent/(name+'.mp4')
        movie.write_bytes(video.read_bytes())
        review=video.parent/(name+'-review.zip')
        # Two assets per clip: 15 * 31 * 2 = 930, below GitHub's 1000/release cap.
        with zipfile.ZipFile(review,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('cover.jpg',cover.read_bytes())
            for filename in ('transcript.json','source-frames.jpg','final-frames.jpg'):
                path=video.parent/filename
                if not path.is_file(): raise ServiceError('review_evidence_missing')
                archive.write(path,filename)
            for filename in ('qa-evidence.json','asr-comparison.json'):
                path=video.parent/filename
                if path.is_file():archive.write(path,filename)
            archive.writestr('manifest.json',json.dumps({'clip_id':clip['id'],
                'source_url':clip.get('url'),'category':clip.get('category'),
                'video_sha256':digest,'transcript_sha256':hashlib.sha256(
                    (video.parent/'transcript.json').read_bytes()).hexdigest(),
                'review_status':'automated_local_models' if clip.get('_qa_receipt') else 'not_reviewed'},ensure_ascii=False,indent=2))
        tag='tiktok14-'+current.strftime('%Y-%m')
        existing=self.command(['release','view',tag,'--json','assets'],check=False)
        if existing.returncode:
            self.command(['release','create',tag,'--target','main','--title',
                          'TikTok14 '+current.strftime('%Y-%m'),'--notes',
                          'Separat vorbereitete Gaming-Clips fuer TikTok14.'])
        else:
            try: assets=json.loads(existing.stdout)['assets']
            except (KeyError,ValueError,TypeError): raise ServiceError('release_capacity_unknown') from None
            if not isinstance(assets,list) or len(assets)+2>1000:
                raise ServiceError('release_asset_capacity_reached')
        # Never replace existing media. Unknown hosting outcomes cannot overwrite it.
        self.command(['release','upload',tag,str(movie),str(review)])
        prefix=REPO_PREFIX+current.strftime('%Y-%m')+'/'
        return prefix+movie.name,prefix+review.name,digest


def own_duplicate(item,state):
    return bool(identities(item)&set(state.get('used_ids',[]))) or any(
        identities(item)&identities(row) or nearby_event(item,row) for row in state['attempts'])


def discard_queue(state,reason,current):
    state.setdefault('rejected',[]).extend(dict(item,status='rejected_tiktok14',
        rejection_reason=reason,rejected_at=stamp(current)) for item in state['queue'])
    state['queue']=[]
    state.pop('last_prepare_hour',None)


def prepare(store,config,legacy,current,host):
    permitted=sources(config)
    old=legacy_ids(legacy)
    state,sha=store.load()
    if any(row.get('status')!='verified_public' for row in state['attempts']):
        return 'pending'
    if compact_history(state,current):sha=store.save(state,sha)
    # Preparation never consumes a publishing slot. Keep one candidate ready
    # even while the rolling send quota is full; Worker enforces the send cap.
    if state['queue']:
        item=state['queue'][0]
        if own_duplicate(item,state) or any(nearby_event(item,row) for row in legacy['created']):
            discard_queue(state,'known_source_duplicate',current)
            sha=store.save(state,sha)
    if state['queue']:
        item=state['queue'][0]
        if (eligible(item,current) and item.get('streamer') in permitted and
                not identities(item) & old):
            return 'ready'
        if (item.get('status')=='awaiting_review_tiktok14' and not blocked(item) and
                item.get('streamer') in permitted and not identities(item)&old and
                0 <= (current-parse_timestamp(item['original_created_at'])).total_seconds() <= MAX_SEND_AGE_HOURS*3600):
            report_review(item)
            return 'needs_review'
        state.setdefault('rejected',[]).extend(state['queue'])
        state['queue']=[]
        sha=store.save(state,sha)
    slot=current.strftime('%Y-%m-%dT%H')
    after_send=any(row.get('status')=='verified_public' and
        parse_timestamp(row['reserved_at']).strftime('%Y-%m-%dT%H')==slot for row in state['attempts'])
    if state.get('last_prepare_hour')==slot and not (after_send and state.get('last_prefetch_hour')!=slot): return 'hour_complete'
    scans=state.get('prepare_scans',{})
    if scans.get('hour')==slot and scans.get('count',0)>=3:return 'scan_budget_exhausted'
    state['prepare_scans']={'hour':slot,'count':scans.get('count',0)+1 if scans.get('hour')==slot else 1}
    sha=store.save(state,sha)
    namespace=producer_namespace()
    namespace['STREAMERS']=list(config['sources'])
    namespace['RANK']={name:index+1 for index,name in enumerate(config['sources'])}
    namespace['now_utc']=lambda:current
    inspect=namespace.get('inspect_original')
    if inspect:
        def inspect_new_event(*args,**kwargs):
            clip=inspect(*args,**kwargs)
            if clip and any(nearby_event(clip,row) for row in state['attempts']+legacy['created']):
                report=namespace.setdefault('_report',{}).setdefault('counts',{})
                report['duplicate_source_event']=report.get('duplicate_source_event',0)+1
                return None
            return clip
        namespace['inspect_original']=inspect_new_event
    # Cloud budget counts sends, not failed/rejected production records.
    namespace['can_prepare']=lambda *a,**k:(True,'OK')
    records=copy.deepcopy(state.get('rejected',[]))
    records += [dict(row,created_at=row.get('created_at',row['reserved_at']))
                for row in state['attempts']]
    processed=set(old)|set(state.get('used_ids',[]))
    for row in records:
        processed.update(str(row.get(key,'')) for key in ('clip_id','clip_slug'))
    namespace['read_state']=lambda:{'version':2,'created':copy.deepcopy(records),
                                    'processed_ids':list(processed)}
    receipts={}
    def release(clip,movie,cover,now):
        original=dict(clip,source_sha256=clip.get('_qa_evidence',{}).get('source_sha256',''))
        if own_duplicate(original,state) or any(nearby_event(original,row) for row in legacy['created']):
            report=namespace.setdefault('_report',{})
            report.setdefault('counts',{})['qa_duplicate_source']=report.get('counts',{}).get('qa_duplicate_source',0)+1
            report.setdefault('rejected',[]).append({'clip_id':clip['id'],'clip_slug':clip.get('clip_slug'),
                'streamer':clip.get('channel_login'),'source_url':clip.get('url'),
                'source_sha256':original['source_sha256'],'status':'quality_rejected',
                'reason':'qa_duplicate_source','created_at':stamp(now)})
            raise QualityRejected('qa_duplicate_source')
        if clip.get('_qa_evidence'):
            try:
                from tiktok14_autoreview import automated_receipt
                preview={'clip_id':clip['id'],'sha256':hashlib.sha256(movie.read_bytes()).hexdigest(),
                    'streamer':clip.get('channel_login'),
                    'transcript_sha256':hashlib.sha256((movie.parent/'transcript.json').read_bytes()).hexdigest(),
                    'source_sha256':clip['_qa_evidence'].get('source_sha256'),
                    'rights_status':'user_declared_source_list'}
                preview['media_review']=automated_receipt(preview,clip['_qa_evidence'],now)
                if review_error(preview,now):raise ServiceError('automatic_evidence_invalid')
                clip['_qa_receipt']=preview['media_review']
            except Exception:raise ProductionInterrupted('automatic_evidence_invalid_before_host') from None
        try:
            url,thumbnail,digest=host(clip,movie,cover,now)
        except Exception:
            raise ProductionInterrupted('media_host_failed') from None
        receipts[url]=(digest,clip,movie.parent)
        return url,thumbnail
    def persist(data):
        nonlocal sha
        record=copy.deepcopy(data['created'][-1])
        receipt=receipts.get(record.get('video_url'))
        if not receipt: raise ServiceError('unverified_production_receipt')
        digest,clip,media_dir=receipt
        record.update(sha256=digest,rights_status='user_declared_source_list',
            status='awaiting_review_tiktok14',video_review_status='full_media_review_required',
            subtitle_verified=False,category=clip.get('category'))
        transcript=media_dir/'transcript.json'
        if transcript.exists():
            record['transcript_sha256']=hashlib.sha256(transcript.read_bytes()).hexdigest()
            record['asr_requires_correction']=bool(json.loads(
                transcript.read_text(encoding='utf-8')).get('requires_correction',True))
        if clip.get('_qa_evidence'):
            from tiktok14_autoreview import automated_receipt
            record['source_sha256']=clip['_qa_evidence']['source_sha256']
            record['hook']=clip['_qa_evidence']['headline']
            record['caption']=f"Gaming-Moment von {record['streamer']} · Quelle: Twitch\n#gaming #twitch"
            if clip['_qa_evidence']['caption_mode']=='title_only':
                record.update(editing_status='rendered_9x16_title_only',transcript_subtitles=False)
            record['media_review']=clip['_qa_receipt']
            if review_error(record,current):raise ProductionInterrupted('automatic_evidence_invalid')
            record.update(status='ready_tiktok14',video_review_status='automated_media_evidence_passed',subtitle_verified=False)
        root=record['video_url'][:-4]
        record.pop('cover_url',None)
        record['review_assets']={'bundle':root+'-review.zip'}
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
    interruption=None
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        try:
            namespace['main']()
        except ProductionInterrupted as error:
            interruption=str(error)
    counts=dict(namespace.get('_report',{}).get('counts',{}))
    rejected=namespace.get('_report',{}).get('rejected',[])
    if rejected:state.setdefault('rejected',[]).extend(rejected)
    technical=bool(interruption) or any(counts.get(key) for key in
        ('listing_failed','metadata_failed','download_failed','render_failed'))
    quality=any(value for key,value in counts.items() if key.startswith(('asr_','qa_')))
    result=('ready' if state['queue'] and eligible(state['queue'][0],current) else 'needs_review' if state['queue'] else
        'degraded' if technical else 'quality_rejected' if quality else 'empty')
    if result!='degraded':
        state['last_prepare_hour']=slot
        if after_send: state['last_prefetch_hour']=slot
    state['last_production']={'at':stamp(current),'result':result,'counts':counts}
    store.save(state,sha)
    report_result(state['last_production'])
    if state['queue'] and not eligible(state['queue'][0],current): report_review(state['queue'][0])
    if interruption:raise ServiceError(interruption) from None
    return result


def report_result(report):
    Path('tiktok14-diagnostics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('TikTok14 diagnostics: '+json.dumps(report,sort_keys=True))
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a',encoding='utf-8') as handle:
            handle.write('### TikTok production diagnostics\n```json\n'+json.dumps(report,indent=2)+'\n```\n')


def report_review(item):
    summary=os.getenv('GITHUB_STEP_SUMMARY')
    if not summary: return
    movie=item.get('video_url','')
    if not isinstance(movie,str) or not re.fullmatch(re.escape(REPO_PREFIX)+
            r'\d{4}-(?:0[1-9]|1[0-2])/[A-Za-z0-9_-]+\.mp4',movie): return
    with open(summary,'a',encoding='utf-8') as handle:
        handle.write('\n### Clip wartet auf vollstaendige Medienpruefung\n'
            f'\n[Fertiges Video]({movie}) · [Pruefpaket]({movie[:-4]}-review.zip)\n'
            '\nNoch keine Freigabe und kein TikTok-Post. Unsichere ASR-Stellen stehen '
            'im Transkript; falsche eingebrannte Untertitel muessen vor Freigabe '
            'durch einen neu gerenderten, erneut geprueften Kandidaten ersetzt werden.\n')


def apply_review(store,config,payload,current):
    """Accept a review of these exact bytes. This operation never contacts Buffer."""
    def unique_pairs(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate_key')
            result[key]=value
        return result
    try:
        if not isinstance(payload,str) or len(payload.encode('utf-8'))>16000: raise ValueError()
        receipt=json.loads(payload,object_pairs_hook=unique_pairs)
        if not isinstance(receipt,dict): raise ValueError()
        review=receipt['media_review']
        if not isinstance(review,dict): raise ValueError()
    except (ValueError,KeyError,TypeError,RecursionError):
        raise ServiceError('invalid_review_payload') from None
    state,sha=store.load()
    if any(row.get('status')!='verified_public' for row in state['attempts']):
        raise ServiceError('review_send_already_pending')
    if len(state['queue'])!=1: raise ServiceError('review_candidate_missing')
    item=state['queue'][0]
    if (str(receipt.get('clip_id',''))!=str(item.get('clip_id','')) or
            review.get('media_sha256')!=item.get('sha256') or
            review.get('transcript_sha256')!=item.get('transcript_sha256')):
        raise ServiceError('review_candidate_changed')
    candidate=copy.deepcopy(item)
    candidate['media_review']=review
    decision=review.get('decision')
    if decision=='approved':
        error=review_error(candidate,current)
        if error: raise ServiceError(error)
        candidate['status']='ready_tiktok14'
        if candidate.get('streamer') not in sources(config) or not eligible(candidate,current):
            raise ServiceError('review_candidate_ineligible')
        state['queue']=[candidate]
    elif decision=='rejected':
        reason=review.get('reason')
        if (not isinstance(reason,str) or not 12<=len(reason.strip())<=1000 or
                not isinstance(review.get('reviewer'),str) or len(review['reviewer'].strip())<3):
            raise ServiceError('review_rejection_reason_required')
        candidate.update(status='rejected_tiktok14',rejection_reason=reason,
                         rejected_at=stamp(current))
        state.setdefault('rejected',[]).append(candidate)
        state['queue']=[]
        state.pop('last_prepare_hour',None)
    else: raise ServiceError('invalid_review_decision')
    store.save(state,sha)
    return 'review_'+decision


def diagnose(config,legacy,state,current):
    """Network metadata only: no media download, render, hosting, state write or post."""
    namespace=producer_namespace()
    namespace['STREAMERS']=list(sources(config))
    namespace['RANK']={name:i+1 for i,name in enumerate(config['sources'])}
    old=legacy_ids(legacy)
    for row in state['attempts']+state['queue']+state.get('rejected',[]): old.update(identities(row))
    candidates=[pair for pair in namespace['fetch_candidates']()
                if namespace['twitch_slug'](pair[1]) not in old]
    qualified=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for clip in pool.map(lambda pair:namespace['inspect_original'](*pair,current),candidates):
            if clip and not identities(clip)&old: qualified.append(clip)
    report={'at':stamp(current),'mode':'read_only','counts':dict(namespace['_report']['counts']),
        'qualified':[{'clip_id':x['id'],'streamer':x['channel_login'],
            'category':x['category'],'age_hours':round(x['age_hours'],2)} for x in qualified]}
    report_result(report)
    return 'degraded' if report['counts'].get('listing_failed') or report['counts'].get('metadata_failed') else 'diagnosed'


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
        assert_single_route(github,config)
        item=state['queue'][0]
        if own_duplicate(item,state):
            discard_queue(state,'known_source_duplicate',dt.datetime.now(dt.timezone.utc))
            store.save(state,sha)
            return 'known_source_duplicate_skipped'
        legacy=read_legacy(github);old=legacy_ids(legacy)
        if identities(item) & old or blocked(item) or any(nearby_event(item,row) for row in legacy['created']):
            state.setdefault('rejected',[]).extend(state['queue'])
            state['queue']=[]
            store.save(state,sha)
            return 'known_auto20_duplicate_skipped'
        if not eligible(item,dt.datetime.now(dt.timezone.utc)):
            if review_error(item,dt.datetime.now(dt.timezone.utc)):
                return 'needs_review'
            raise ServiceError('queued_clip_expired')
        if item.get('media_review',{}).get('version')==2 and os.getenv('TIKTOK14_AUTOREVIEW_ENABLED')!='true':
            state['last_commissioning_hour']=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H')
            store.save(state,sha)
            return 'automatic_commissioning_required'
        verify_media(item['video_url'],item.get('sha256'))
    gateway=BufferGateway(key)
    worker=Worker(store,gateway,verify_public)
    result=worker.run_one(config,None,dt.datetime.now(dt.timezone.utc))
    # One API operation per tick; reconcile on the next scheduled opportunity.
    # Blind minute polling consumed the free plan's monthly request allowance.
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
                ref not in ('refs/heads/main','refs/heads/codex/tiktok14-safety-audit','refs/heads/codex/tiktok14-reliability','refs/heads/codex/tiktok14-longterm') or
                action not in ('prepare','publish','diagnose','review') or
                (action in ('publish','review') and ref!='refs/heads/main')):
            raise ServiceError('unapproved_cloud_context')
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        if config.get('accounting_mode')!='independent':
            raise ServiceError('independent_mode_not_configured')
        sources(config)
        github=GitHubAPI(token)
        if action=='diagnose':
            state,_=GitHubState(github).load()
            result=diagnose(config,read_legacy(github),state,dt.datetime.now(dt.timezone.utc))
        elif action=='prepare':
            store=ensure_store(github)
            result=('auto20_running' if legacy_running(github) else
                    prepare(store,config,read_legacy(github),
                            dt.datetime.now(dt.timezone.utc),Host(token)))
        elif action=='review':
            result=apply_review(GitHubState(github),config,
                os.environ.pop('TIKTOK14_REVIEW_JSON',''),dt.datetime.now(dt.timezone.utc))
        else:
            result=publish(GitHubState(github),config,github,key)
        print('TikTok14 '+action+': '+result)
        return 0 if result not in ('unresolved','unverified','degraded') else 1
    except ServiceError as error:
        code=str(error)
        print('STOP: '+(code if re.fullmatch('[a-z0-9_]+',code) else 'cloud_check_failed'))
        return 1
    except Exception:
        print('STOP: cloud_operation_failed; no server details or credentials logged')
        return 1


if __name__=='__main__': raise SystemExit(main())
