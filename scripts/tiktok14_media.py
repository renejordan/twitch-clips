"""Instrument only the independent producer; never change Auto20's media code."""
from collections import Counter
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from tiktok14_quality import blocked
from tiktok14_services import ServiceError,QualityRejected,ProductionInterrupted


def automated_render(namespace,clip,source,model_dir):
    """Run actual models outside the state writer with no service credentials."""
    from tiktok14_cloud import child_environment
    namespace['OUT'].mkdir(parents=True,exist_ok=True)
    if not __import__('re').fullmatch('[A-Za-z0-9_-]{4,100}',str(clip['id'])):raise ProductionInterrupted('qa_clip_id_invalid')
    out=Path(tempfile.mkdtemp(prefix='qa-'+str(clip['id'])+'-',dir=namespace['OUT'])).resolve()
    payload=out/'clip.json'
    payload.write_text(json.dumps({key:value for key,value in clip.items() if not key.startswith('_')},ensure_ascii=False),encoding='utf-8')
    try:
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('tiktok14_qa_pipeline.py')),
            '--source',str(Path(source).resolve()),'--clip',str(payload),'--output',str(out),
            '--models',str(Path(model_dir).resolve())],env=child_environment(),
            capture_output=True,text=True,timeout=1200,check=False)
        verdict=json.loads((out/'qa-result.json').read_text(encoding='utf-8'))
        if result.returncode==2 and verdict.get('status')=='rejected':
            reason=verdict.get('reason','')
            if not isinstance(reason,str) or not __import__('re').fullmatch('qa_[a-z_]+',reason):raise ValueError()
            raise QualityRejected(reason)
        if result.returncode or verdict.get('status')!='passed':
            reason=verdict.get('reason','')
            if verdict.get('status')=='technical_failure' and isinstance(reason,str) and __import__('re').fullmatch('qa_[a-z_]{1,120}',reason):
                raise ProductionInterrupted(reason)
            raise ServiceError('qa_child_failed')
        evidence=json.loads((out/'qa-evidence.json').read_text(encoding='utf-8'))
        if evidence.get('source_sha256')!=hashlib.sha256(Path(source).read_bytes()).hexdigest():raise ServiceError('qa_source_hash_mismatch')
        for name in ('tiktok.mp4','cover.jpg','transcript.json','source-frames.jpg','final-frames.jpg'):
            if not (out/name).is_file():raise ServiceError('qa_output_missing')
        clip['_qa_evidence']=evidence
        return out/'tiktok.mp4',out/'cover.jpg',evidence.get('caption_mode')=='verified_words'
    except QualityRejected:raise
    except Exception:raise ProductionInterrupted('qa_service_failed') from None

# Conservative editorial categories. New games need an explicit reviewed addition.
GAMES=frozenset({'League of Legends','Minecraft','Fortnite','VALORANT',
    'Counter-Strike','Counter-Strike 2','World of Warcraft','Dota 2','Deadlock',
    'Grand Theft Auto V','EA Sports FC 26','EA SPORTS FC 26','Rocket League',
    'Overwatch 2','PUBG: BATTLEGROUNDS','Apex Legends','Hearthstone',
    'Teamfight Tactics','Diablo IV','Escape from Tarkov','Rust','DayZ',
    'ARC Raiders','Dead by Daylight','Just Dance 2026','Super Mario Maker 2',
    'Pokémon','Pokémon Legends: Z-A','ELDEN RING','Hollow Knight: Silksong'})


def metadata_decision(info,channel,current,min_views=100):
    if blocked(info): return None,'permanently_blocked'
    creators=info.get('creators')
    if creators is None: creators=[info.get('creator')]
    if (str(info.get('channel','')).casefold()!=channel.casefold() or
            not isinstance(creators,list) or
            channel.casefold() not in [str(value).casefold() for value in creators]):
        return None,'broadcaster_mismatch'
    if 'twitch' not in str(info.get('extractor_key',info.get('extractor',''))).lower():
        return None,'not_twitch_metadata'
    for key in ('timestamp','duration','view_count'):
        if type(info.get(key)) not in (int,float) or not math.isfinite(info[key]):
            return None,'invalid_'+key
    age=(current-dt.datetime.fromtimestamp(info['timestamp'],dt.timezone.utc)).total_seconds()/3600
    if not 0<=age<=72: return None,'age_outside_72h'
    if not 15<=info['duration']<=60: return None,'duration_outside_15_60s'
    if info['view_count']<min_views: return None,'views_below_100'
    # Views rank discovery, while actual media evidence decides quality. The
    # old 8000-view gate discarded almost every otherwise valid 48–72h clip.
    categories=info.get('categories')
    if not isinstance(categories,list) or len(categories)!=1 or categories[0] not in GAMES:
        return None,'gaming_category_not_verified'
    if not isinstance(info.get('title'),str) or len(info['title'].strip())<5:
        return None,'title_too_short'
    return categories[0],'qualified_metadata'


def configure(namespace,report):
    """Use each namespace's run boundary so tests/media children never get secrets."""
    lock=threading.Lock()
    counts=Counter()
    report['counts']=counts
    def count(key):
        with lock: counts[key]+=1

    def listing(channel):
        links=[]; seen=set()
        for period in ('24hr','7d'):
            count('listing_requested')
            try:
                result=namespace['run'](['yt-dlp','--no-warnings','--flat-playlist',
                    '--playlist-end','30','--socket-timeout','15','--retries','1',
                    '--dump-single-json',f'https://www.twitch.tv/{channel}/clips?filter=clips&range={period}'],timeout=65)
                data=json.loads(result.stdout)
                if not isinstance(data.get('entries'),list): raise ValueError()
                for row in data['entries'][:30]:
                    if not isinstance(row,dict): continue
                    link=row.get('webpage_url') or row.get('url')
                    slug=namespace['twitch_slug'](link) if isinstance(link,str) else None
                    if not slug or slug in seen: continue
                    seen.add(slug)
                    # Flat API metadata can exclude obvious unusable entries.
                    # Every survivor still needs fresh per-clip original verification.
                    current=namespace['now_utc']().timestamp()
                    valid=lambda key:type(row.get(key)) in (int,float) and math.isfinite(row[key])
                    if valid('timestamp') and not 0<=current-row['timestamp']<=72*3600:
                        count('listing_age_prefilter');continue
                    if valid('view_count') and row['view_count']<100:
                        count('listing_views_prefilter');continue
                    if valid('duration') and not 15<=row['duration']<=60:
                        count('listing_duration_prefilter');continue
                    links.append((channel,link))
                count('listing_ok')
            except Exception: count('listing_failed')
        with lock: counts['discovered']+=len(links)
        return links

    def inspect(channel,link,current,min_views=100):
        count('metadata_requested')
        try:
            response=namespace['run'](['yt-dlp','--no-warnings','--no-playlist',
                '--socket-timeout','15','--retries','1','--skip-download','--dump-single-json',link],timeout=45)
            info=json.loads(response.stdout)
            category,reason=metadata_decision(info,channel,current,min_views)
            count(reason)
            if not category: return None
            slug=namespace['twitch_slug'](info.get('webpage_url') or link)
            if not slug: count('invalid_source_url'); return None
            age=(current-dt.datetime.fromtimestamp(info['timestamp'],dt.timezone.utc)).total_seconds()/3600
            return {'id':str(info['id']),'clip_slug':slug,'url':link,
                'channel_login':channel,'rank':namespace['RANK'][channel],
                'title':info['title'],'view_count':info['view_count'],
                'duration':float(info['duration']),'category':category,
                'original_created_at':namespace['iso'](dt.datetime.fromtimestamp(info['timestamp'],dt.timezone.utc)),
                'age_hours':age}
        except Exception:
            count('metadata_failed')
            return None

    model=None
    def transcribe(path):
        nonlocal model
        from faster_whisper import WhisperModel
        if model is None: model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4)
        segments,details=model.transcribe(str(path),language='de',beam_size=5,
            word_timestamps=True,condition_on_previous_text=False,vad_filter=True,
            hallucination_silence_threshold=1.0)
        words=[]; evidence=[]; uncertain_words=[]; uncertain_segments=[]
        for segment in segments:
            if (segment.no_speech_prob>.5 or segment.avg_logprob<-.7 or
                    segment.compression_ratio>2.4):
                uncertain_segments.append({'start':segment.words[0].start if segment.words else None,
                    'no_speech_prob':segment.no_speech_prob,'avg_logprob':segment.avg_logprob,
                    'compression_ratio':segment.compression_ratio})
            for word in segment.words or []:
                if not word.word.strip(): continue
                if word.probability<.6: uncertain_words.append(len(words))
                words.append((float(word.start),float(word.end),word.word.strip()))
                evidence.append({'start':word.start,'end':word.end,'text':word.word.strip(),
                                 'probability':word.probability})
        if len(words)<3: raise ServiceError('asr_insufficient_speech')
        target=namespace['OUT']/'transcript.json'
        target.write_text(json.dumps({'model':'small','language':'de','words':evidence,
            'requires_correction':bool(uncertain_words or uncertain_segments),
            'uncertain_word_indexes':uncertain_words,'uncertain_segments':uncertain_segments,
            'editorial_accuracy':'not_reviewed'},ensure_ascii=False,indent=2),encoding='utf-8')
        if uncertain_words or uncertain_segments: count('asr_draft_requires_correction')
        return words

    def download(clip):
        count('download_attempted')
        try:
            namespace['OUT'].mkdir(parents=True,exist_ok=True)
            for path in namespace['OUT'].glob('source.*'):path.unlink()
            namespace['run'](['yt-dlp','--no-warnings','--no-playlist','--socket-timeout','15',
                '--retries','2','--fragment-retries','2','-f','best[height<=1080]',
                '--merge-output-format','mp4','-o',str(namespace['OUT']/'source.%(ext)s'),clip['url']],timeout=120)
            files=[path for path in namespace['OUT'].glob('source.*') if path.suffix.lower() in ('.mp4','.mkv','.webm')]
            if len(files)!=1:raise ServiceError('media_download_incomplete')
            return files[0]
        except Exception:
            count('download_failed')
            raise

    original_render=namespace['render']
    def render(clip,source):
        count('render_attempted')
        report['current_candidate']={'clip_id':clip['id'],'clip_slug':clip.get('clip_slug'),
            'streamer':clip.get('channel_login')}
        if os.getenv('TIKTOK14_QA_MODELS'):
            try:
                result=automated_render(namespace,clip,source,os.environ['TIKTOK14_QA_MODELS'])
                count('render_ok');return result
            except QualityRejected as error:
                count(str(error))
                report.setdefault('rejected',[]).append({'clip_id':clip['id'],'clip_slug':clip['clip_slug'],
                    'streamer':clip['channel_login'],'source_url':clip['url'],'status':'quality_rejected',
                    'created_at':namespace['iso'](namespace['now_utc']()),'reason':str(error)})
                namespace.get('_persist_rejections',lambda:None)()
                raise
        try:
            movie,cover,subs=original_render(clip,source)
            # Full decode, not just the first two seconds.
            namespace['run'](['ffmpeg','-v','error','-i',str(movie),'-f','null','-'],timeout=120)
            for path,name in ((source,'source-frames.jpg'),(movie,'final-frames.jpg')):
                namespace['run'](['ffmpeg','-y','-v','error','-i',str(path),'-vf',
                    'fps=1/5,scale=270:-2,tile=3x4','-frames:v','1',str(namespace['OUT']/name)],timeout=60)
            count('render_ok')
            return movie,cover,subs
        except ServiceError as error:
            code=str(error)
            count(code if code.startswith('asr_') else 'render_failed')
            raise
        except Exception:
            count('render_failed')
            raise

    namespace.update(channel_urls=listing,inspect_original=inspect,transcribe=transcribe,
        very_strong=lambda clip:0<=clip['age_hours']<=72,
        # Keep original setup AND payoff; speech-density crops cut sentences/punchlines.
        pick_window=lambda duration,words:(0.0,duration),download=download,render=render)
