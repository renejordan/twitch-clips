"""Instrument only the independent producer; never change Auto20's media code."""
from collections import Counter
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import threading

from tiktok14_quality import blocked
from tiktok14_services import ServiceError

# Conservative editorial categories. New games need an explicit reviewed addition.
GAMES=frozenset({'League of Legends','Minecraft','Fortnite','VALORANT',
    'Counter-Strike','Counter-Strike 2','World of Warcraft','Dota 2','Deadlock',
    'Grand Theft Auto V','EA Sports FC 26','EA SPORTS FC 26','Rocket League',
    'Overwatch 2','PUBG: BATTLEGROUNDS','Apex Legends','Hearthstone',
    'Teamfight Tactics','Diablo IV','Escape from Tarkov','Rust','DayZ',
    'ARC Raiders','Dead by Daylight','Just Dance 2026','Super Mario Maker 2',
    'Pokémon','Pokémon Legends: Z-A','ELDEN RING','Hollow Knight: Silksong'})


def metadata_decision(info,channel,current,min_views=800):
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
    if info['view_count']<min_views: return None,'views_below_800'
    if age>48 and (info['view_count']<8000 or info['view_count']/max(1,age)<150):
        return None,'older_clip_metrics_insufficient'
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
        count('listing_requested')
        try:
            result=namespace['run'](['yt-dlp','--no-warnings','--flat-playlist',
                '--playlist-end','30','--socket-timeout','15','--retries','1',
                '--dump-single-json',f'https://www.twitch.tv/{channel}/clips?filter=clips&range=7d'],timeout=65)
            data=json.loads(result.stdout)
            if not isinstance(data.get('entries'),list): raise ValueError()
            links=[]
            for row in data['entries'][:30]:
                if not isinstance(row,dict): continue
                link=row.get('webpage_url') or row.get('url')
                if isinstance(link,str) and namespace['twitch_slug'](link): links.append((channel,link))
            count('listing_ok')
            with lock: counts['discovered']+=len(links)
            return links
        except Exception:
            count('listing_failed')
            return []

    def inspect(channel,link,current,min_views=800):
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
        words=[]; evidence=[]
        for segment in segments:
            if (segment.no_speech_prob>.5 or segment.avg_logprob<-.7 or
                    segment.compression_ratio>2.4):
                raise ServiceError('asr_segment_uncertain')
            for word in segment.words or []:
                if not word.word.strip(): continue
                if word.probability<.6: raise ServiceError('asr_word_uncertain')
                words.append((float(word.start),float(word.end),word.word.strip()))
                evidence.append({'start':word.start,'end':word.end,'text':word.word.strip(),
                                 'probability':word.probability})
        if len(words)<3: raise ServiceError('asr_insufficient_speech')
        target=namespace['OUT']/'transcript.json'
        target.write_text(json.dumps({'model':'small','language':'de','words':evidence,
            'editorial_accuracy':'not_reviewed'},ensure_ascii=False,indent=2),encoding='utf-8')
        return words

    original_download=namespace['download']
    def download(clip):
        count('download_attempted')
        try: return original_download(clip)
        except Exception:
            count('download_failed')
            raise

    original_render=namespace['render']
    def render(clip,source):
        count('render_attempted')
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
        # Keep original setup AND payoff; speech-density crops cut sentences/punchlines.
        pick_window=lambda duration,words:(0.0,duration),download=download,render=render)
