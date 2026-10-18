"""Editorial approval is a reviewed-media receipt, never an ASR success flag."""
import datetime as dt
import re
from urllib.parse import urlsplit, unquote

BLOCKED = frozenset({
    '2845373187','AliveCautiousMonitorPJSalt-_khBUBf020YdG7yv',
    '1586086735','DiligentSarcasticArugulaKevinTurtle-gbC316ajn04-BalO',
    '2914846804','MistyAgitatedPicklesKAPOW-_IMwx3P0gVRlJBWy',
    '3570577492','AltruisticVenomousVelociraptorSpicyBoy-ECiYgUQC2M1vchxM',
    'GrossTubularAntelopeWow-1KWH2cn3DcuhqWSe',
    '1497602893','PeppyBloodyTeaRlyTho-BUSJgy71xak5-60U',
    '2169900339','CreativeSpeedyMetalPipeHype-WuzCUT11-Pk1F9WY',
})
CHECKS=('subtitles_accuracy','frame_composition','full_clip_payoff',
        'audio_intelligibility','gaming_context')


def identities(row):
    values={str(row.get(key,'')) for key in ('id','clip_id','clip_slug','display_id','sha256')}
    for key in ('url','source_url','webpage_url','original_url'):
        value=row.get(key)
        if not isinstance(value,str): continue
        parsed=urlsplit(value)
        if parsed.scheme!='https' or parsed.username or parsed.password: continue
        if parsed.netloc in ('clips.twitch.tv','www.twitch.tv','twitch.tv'):
            path=unquote(parsed.path).rstrip('/')
            if ((parsed.netloc=='clips.twitch.tv' and path.count('/')==1) or
                    re.fullmatch('/[^/]+/clip/[^/]+',path)):
                values.add(path.rsplit('/',1)[-1])
    return values-{''}


def blocked(row):
    return bool(identities(row)&BLOCKED)


def review_error(item,current):
    if blocked(item): return 'permanently_blocked_clip'
    review=item.get('media_review')
    if not isinstance(review,dict): return 'full_media_review_required'
    if review.get('version')==2:
        from tiktok14_autoreview import automated_review_error
        return automated_review_error(item,review,current)
    try:
        reviewed=dt.datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
        if reviewed.tzinfo is None or not 0 <= (current-reviewed).total_seconds() <= 72*3600:
            return 'review_timestamp_invalid'
        if (review.get('version')!=1 or review.get('decision')!='approved' or
                not isinstance(review.get('reviewer'),str) or len(review['reviewer'].strip())<3 or
                not re.fullmatch('[a-f0-9]{64}',str(item.get('sha256',''))) or
                review.get('media_sha256')!=item['sha256'] or
                not re.fullmatch('[a-f0-9]{64}',str(item.get('transcript_sha256',''))) or
                review.get('transcript_sha256')!=item['transcript_sha256'] or
                review.get('watched_full_video') is not True):
            return 'review_not_bound_to_media'
        for name in CHECKS:
            check=review['checks'][name]
            if (check.get('result')!='pass' or not isinstance(check.get('evidence'),str) or
                    len(check['evidence'].strip())<12):
                return 'editorial_check_missing'
        # The account owner's existing source-list declaration is retained;
        # editorial review must not invent an independent licence verification.
        if item.get('rights_status')!='user_declared_source_list':
            return 'source_rights_declaration_missing'
    except (KeyError,ValueError,TypeError,AttributeError):
        return 'media_review_invalid'
    return None
