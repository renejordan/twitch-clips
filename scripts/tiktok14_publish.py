#!/usr/bin/env python3
"""Offline eligibility checks and a closed commissioning gate for TikTok14.

The previous browser uploader is quarantined: it could not verify the account,
public visibility or safe cross-route deduplication. No cookie is read here.
An enabled repository variable alone must never authorize live posting.
"""
import datetime as dt
import re
import sys
from zoneinfo import ZoneInfo

REPO_PREFIX = 'https://github.com/renejordan/twitch-clips/releases/download/tiktok14-'
MAX_PER_DAY = 14
LOCAL_ZONE = ZoneInfo('Europe/Berlin')
UTC = dt.timezone.utc


def stamp(d):
    return d.isoformat(timespec='seconds').replace('+00:00', 'Z')


def parse_timestamp(text):
    if not isinstance(text, str):
        raise ValueError('Timestamp must be a string')
    value = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timestamp must include a timezone')
    return value.astimezone(UTC)


def eligible(item, current):
    if item.get('delivery_route') != 'github14' or item.get('status') != 'ready_tiktok14':
        return False
    if item.get('editing_status') != 'rendered_9x16_with_burned_subtitles':
        return False
    if item.get('subtitle_verified') is not True or item.get('transcript_subtitles') is not True:
        return False
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,100}', str(item.get('clip_id', ''))):
        return False
    # Exact repository, monthly tag and plain MP4 filename. No path traversal,
    # query strings, fragments or percent-encoded alternative destinations.
    if not re.fullmatch(re.escape(REPO_PREFIX) + r'\d{4}-(?:0[1-9]|1[0-2])/[A-Za-z0-9_-]+\.mp4',
                        str(item.get('video_url', ''))):
        return False
    try:
        age_h = (current - parse_timestamp(item['original_created_at'])).total_seconds() / 3600
    except (KeyError, ValueError, TypeError):
        return False
    return 0 <= age_h <= 72


def can_reserve(journal, current):
    if not isinstance(journal, dict) or not isinstance(journal.get('attempts'), list):
        return False, 'STOP: corrupt journal'
    attempts = journal['attempts']
    local_date = current.astimezone(LOCAL_ZONE).date()
    total = 0
    for attempt in attempts:
        if not isinstance(attempt, dict):
            return False, 'STOP: corrupt journal entry'
        # Browser success alone is unresolved and must stop future uploads,
        # including on the next day. Do not edit a journal to bypass this gate.
        if attempt.get('status') != 'verified_public':
            return False, 'STOP: unresolved upload; independently verify on TikTok before continuing'
        try:
            moment = parse_timestamp(attempt['reserved_at'])
        except (KeyError, ValueError, TypeError):
            return False, 'STOP: corrupt journal timestamp'
        if moment > current:
            return False, 'STOP: future reservation timestamp'
        if (current - moment).total_seconds() < 86400 or moment.astimezone(LOCAL_ZONE).date() == local_date:
            total += 1
    if total >= MAX_PER_DAY:
        return False, 'SKIP: fourteen upload attempts reached (rolling 24h/local day)'
    return True, 'OK'


def preflight():
    """Intentionally closed until a reviewed, verified publishing adapter exists.

    This is a code-level hold, not a verification flag or environment override.
    Do not replace it with a boolean claiming authentication was verified.
    """
    print('STOP: TikTok14 live publishing is not commissioned. Secure account authentication, '
          'a controlled first post with independently verified visibility, and shared '
          'Metricool/Auto20 duplicate protection are still required. See scripts/TIKTOK14.md.')
    raise SystemExit(3)


def reserve():
    preflight()


def upload():
    preflight()


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
                 'status': 'verified_public'} for i in range(14)]
    assert not can_reserve({'attempts': attempts}, moment)[0]
    for status in ('reserved', 'unknown', 'reported_success_unverified'):
        assert not can_reserve({'attempts': [dict(attempts[0], status=status)]}, moment)[0]
    print('SELFTEST OK: eligibility, subtitles, 14/24h cap, unresolved-upload stop; NO live upload test')


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action == 'selftest':
        selftest()
    elif action == 'preflight':
        preflight()
    elif action == 'reserve':
        reserve()
    elif action == 'upload':
        upload()
    else:
        raise SystemExit('Usage: tiktok14_publish.py selftest|preflight|reserve|upload')
