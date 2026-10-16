#!/usr/bin/env python3
"""Safety-first, unofficial TikTok uploader for user-authorized videos.

No token printed; maintains a committed reservation before every attempted upload.
Does NOT guarantee that a TikTok video is public after a browser 'success'.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE = Path('state/auto14_queue.json')
JOURNAL = Path('state/auto14_publish.json')
LEGACY = Path('state/auto20.json')
REPO_PREFIX = 'https://github.com/renejordan/twitch-clips/releases/download/tiktok14-'
MAX_PER_DAY = 14
LOCAL_ZONE = ZoneInfo('Europe/Berlin')
UTC = dt.timezone.utc


def now():
    return dt.datetime.now(UTC)


def stamp(d=None):
    return (d or now()).isoformat(timespec='seconds').replace('+00:00', 'Z')


def parse_timestamp(text):
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(UTC)


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def data():
    return read_json(SOURCE, {'created': []}), read_json(JOURNAL, {'version': 1, 'attempts': []})


def persist(journal):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def eligible(item, current):
    if item.get('delivery_route') != 'github14' or item.get('status') != 'ready_tiktok14':
        return False
    if item.get('editing_status') != 'rendered_9x16_with_burned_subtitles':
        return False
    if item.get('subtitle_verified') is not True or item.get('transcript_subtitles') is not True:
        return False
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,100}', str(item.get('clip_id', ''))):
        return False
    if not str(item.get('video_url', '')).startswith(REPO_PREFIX):
        return False
    try:
        age_h = (current - parse_timestamp(item['original_created_at'])).total_seconds() / 3600
    except (KeyError, ValueError, TypeError):
        return False
    return 0 <= age_h <= 72


def can_reserve(journal, current):
    attempts = journal['attempts']
    if any(a.get('status') in ('reserved', 'unknown') for a in attempts):
        return False, 'STOP: unknown prior upload status; verify on TikTok before retrying'
    local_date = current.astimezone(LOCAL_ZONE).date()
    total = 0
    for attempt in attempts:
        try:
            moment = parse_timestamp(attempt['reserved_at'])
        except (KeyError, ValueError):
            return False, 'STOP: corrupt journal entry'
        if moment > current or (current - moment).total_seconds() < 86400 or moment.astimezone(LOCAL_ZONE).date() == local_date:
            total += 1
    if total >= MAX_PER_DAY:
        return False, 'SKIP: fourteen upload attempts reached (rolling 24h/local day)'
    return True, 'OK'


def reserve():
    if not os.environ.get('TIKTOK_SESSIONID', '').strip():
        print('SKIP: missing TIKTOK_SESSIONID GitHub secret; no upload started')
        return
    if os.environ.get('TIKTOK14_PAUSE', '') == 'true':
        print('SKIP: explicit pause')
        return
    queue, journal = data()
    current = now()
    allowed, reason = can_reserve(journal, current)
    if not allowed:
        print(reason)
        return
    previous_ids = {str(a['clip_id']) for a in journal['attempts']}
    legacy = read_json(LEGACY, {'created': [], 'processed_ids': []})
    legacy_ids = {str(c.get('clip_id')) for c in legacy.get('created', [])}
    legacy_ids.update(str(x) for x in legacy.get('processed_ids', []))
    options = [c for c in queue['created'] if eligible(c, current)
               and str(c['clip_id']) not in previous_ids and str(c['clip_id']) not in legacy_ids]
    options.sort(key=lambda item: item.get('created_at', ''), reverse=True)
    if not options:
        print('SKIP: no new eligible video; never reuse legacy Metricool clips')
        return
    candidate = options[0]
    journal['attempts'].append({
        'clip_id': str(candidate['clip_id']),
        'streamer': candidate.get('streamer'),
        'run_id': os.environ.get('GITHUB_RUN_ID', 'local-test'),
        'reserved_at': stamp(current),
        'status': 'reserved',
        'account_expected': '@ufo3103',
    })
    persist(journal)
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as handle:
            handle.write('selected=true\n')
    print('RESERVED: one video; upload not yet attempted')


def download_and_check(url, target):
    if not url.startswith(REPO_PREFIX):
        raise ValueError('Untrusted release URL')
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    size = 0
    with urllib.request.urlopen(request, timeout=75) as response, open(target, 'wb') as output:
        if not response.url.startswith('https://'):
            raise ValueError('Unsafe redirect')
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > 150 * 1024 * 1024:
                raise ValueError('File too large')
            output.write(block)
    if size < 50_000:
        raise ValueError('File unexpectedly small')
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                             '-show_entries', 'stream=width,height', '-show_entries', 'format=duration',
                             '-of', 'json', str(target)], check=True, text=True,
                            capture_output=True, timeout=30)
    info = json.loads(result.stdout)
    v = info.get('streams') or []
    if not v or (v[0]['width'], v[0]['height']) != (1080, 1920):
        raise ValueError('Invalid video dimensions')
    if not 15 <= float(info['format']['duration']) <= 65:
        raise ValueError('Invalid clip length')


def upload():
    queue, journal = data()
    run_id = os.environ.get('GITHUB_RUN_ID', 'local-test')
    reserved = [a for a in journal['attempts'] if a.get('run_id') == run_id and a.get('status') == 'reserved']
    if len(reserved) != 1:
        print('SKIP: this run has no unique reservation')
        return
    attempt = reserved[0]
    attempt['status'] = 'unknown'
    persist(journal)  # Fail closed even if the browser crashes after posting.
    item = next((c for c in queue['created'] if str(c.get('clip_id')) == attempt['clip_id']), None)
    if not item or not os.environ.get('TIKTOK_SESSIONID', ''):
        print('STOP: clip or session not available')
        return
    try:
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / 'video.mp4'
            download_and_check(item['video_url'], video)
            from tiktok_uploader.upload import TikTokUploader
            # The upstream library prints cookies (including the TikTok session)
            # even in non-debug paths. Redirect process FDs to /dev/null.
            with open(os.devnull, 'w') as sink:
                saved_out, saved_err = os.dup(1), os.dup(2)
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                    os.dup2(sink.fileno(), 1)
                    os.dup2(sink.fileno(), 2)
                    try:
                        with TikTokUploader(
                            cookies_list=[{'name': 'sessionid', 'value': os.environ['TIKTOK_SESSIONID'],
                                           'domain': '.tiktok.com', 'path': '/'}],
                            browser='chromium', headless=True,
                        ) as uploader:
                            ok = uploader.upload_video(str(video),
                                description=str(item.get('caption', ''))[:1800],
                                visibility='everyone', num_retries=0)
                    finally:
                        sys.stdout.flush()
                        sys.stderr.flush()
                finally:
                    os.dup2(saved_out, 1)
                    os.dup2(saved_err, 2)
                    os.close(saved_out)
                    os.close(saved_err)
        if ok:
            attempt['status'] = 'reported_success_unverified'
            attempt['finished_at'] = stamp()
            print('Browser uploader reported success. Public TikTok URL NOT independently verified.')
        else:
            print('UNKNOWN: browser uploader did not confirm upload; no automatic retry')
    except Exception as exc:
        print('UNKNOWN: uploader exception type ' + type(exc).__name__ + '; no automatic retry')
    finally:
        persist(journal)


def selftest():
    moment = dt.datetime(2026, 10, 16, 12, tzinfo=UTC)
    sample = dict(delivery_route='github14', status='ready_tiktok14',
                  editing_status='rendered_9x16_with_burned_subtitles',
                  subtitle_verified=True, transcript_subtitles=True, clip_id='12345678',
                  original_created_at=stamp(moment-dt.timedelta(hours=2)),
                  video_url=REPO_PREFIX+'2026-10/12345678.mp4')
    assert eligible(sample, moment)
    assert not eligible(dict(sample, status='awaiting_metricool'), moment)
    assert not eligible(dict(sample, original_created_at=stamp(moment-dt.timedelta(hours=73))), moment)
    assert not eligible(dict(sample, subtitle_verified=False), moment)
    assert can_reserve({'attempts': []}, moment)[0]
    attempts = [{'clip_id': str(i), 'reserved_at': stamp(moment-dt.timedelta(hours=2)),
                 'status': 'reported_success_unverified'} for i in range(14)]
    assert not can_reserve({'attempts': attempts}, moment)[0]
    assert not can_reserve({'attempts': [dict(attempts[0], status='unknown')]}, moment)[0]
    print('SELFTEST OK: unique clips, legacy protection, required subtitles, 14/24h cap, ambiguous-upload stop')


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action == 'selftest':
        selftest()
    elif action == 'reserve':
        reserve()
    elif action == 'upload':
        upload()
    else:
        raise SystemExit('Usage: tiktok14_publish.py selftest|reserve|upload')
