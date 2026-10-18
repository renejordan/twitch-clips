"""Single-publisher controller with explicit independent or shared accounting."""
import datetime as dt
import re
from urllib.parse import urlsplit

from tiktok14_buffer_check import validate as validate_connection, CheckFailed
from tiktok14_publish import eligible, parse_timestamp, stamp, LOCAL_ZONE, MAX_PER_DAY
from tiktok14_services import ServiceError, CHANNEL_ID, canonical_video
from tiktok14_quality import identities,nearby_event


def sources(config):
    if config.get('accounting_mode','shared') not in ('shared','independent'):
        raise ServiceError('unknown_accounting_mode')
    permitted = config.get('sources')
    legacy = config.get('legacy_sources')
    if (not isinstance(permitted, list) or not permitted or
            not isinstance(legacy, list) or not legacy or
            any(not isinstance(name, str) or not re.fullmatch('[a-z0-9_]{3,25}', name)
                for name in permitted + legacy) or
            len(set(permitted)) != len(permitted)):
        raise ServiceError('source_permission_missing')
    if config.get('accounting_mode','shared') == 'shared' and set(permitted) & set(legacy):
        raise ServiceError('shared_source_coordination_required')
    return set(permitted)


def observed_posts(overview):
    try:
        validate_connection({'data':overview})
        posts = {}
        for section in ('recent','due','pending'):
            page = overview[section]
            if page['pageInfo']['hasNextPage'] is not False:
                raise ServiceError('buffer_history_incomplete')
            for edge in page['edges']:
                node = edge['node']
                if node['channelId'] != CHANNEL_ID or not re.fullmatch('[a-f0-9]{24}',node['id']):
                    raise ServiceError('buffer_post_identity_mismatch')
                if node['id'] in posts and posts[node['id']] != node:
                    raise ServiceError('buffer_snapshot_inconsistent')
                posts[node['id']] = node
        return list(posts.values())
    except (CheckFailed, KeyError, TypeError, AttributeError):
        raise ServiceError('buffer_snapshot_invalid') from None


def history_start(current):
    midnight = current.astimezone(LOCAL_ZONE).replace(hour=0,minute=0,second=0,microsecond=0)
    return min(current-dt.timedelta(hours=24),midnight.astimezone(dt.timezone.utc))


def history(external, current):
    """Require a genuinely independent observer, never synthesize from Buffer."""
    try:
        observed = parse_timestamp(external['observed_at'])
        if (external.get('complete') is not True or
                not 0 <= (current-observed).total_seconds() <= 300 or
                parse_timestamp(external['window_start']) > history_start(current) or
                parse_timestamp(external['valid_until']) < current or
                not isinstance(external['posts'],list)):
            raise ServiceError('external_history_incomplete')
        result = {}
        for row in external['posts']:
            video_id = row['video_id']
            moment = parse_timestamp(row['at'])
            if not isinstance(video_id,str) or not re.fullmatch('[0-9]{10,30}',video_id):
                raise ServiceError('external_history_invalid')
            if moment > current:
                raise ServiceError('external_future_reservation_requires_coordination')
            if video_id in result and result[video_id] != moment:
                raise ServiceError('external_history_inconsistent')
            result[video_id] = moment
        return result
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ServiceError('external_history_invalid') from None


def in_budget(moment, current):
    if moment > current:
        raise ServiceError('future_attempt')
    return ((current-moment).total_seconds() < 86400 or
            moment.astimezone(LOCAL_ZONE).date() == current.astimezone(LOCAL_ZONE).date())


def counted_events(state, external, posts, current):
    events = dict(external)
    for index, attempt in enumerate(state['attempts']):
        if attempt.get('status') != 'verified_public':
            raise ServiceError('unresolved_previous_attempt')
        reserved = parse_timestamp(attempt['reserved_at'])
        sent = parse_timestamp(attempt.get('sent_at',attempt['reserved_at']))
        url = canonical_video(attempt['tiktok_url'])
        # Processing across midnight still consumes the later posting window.
        events[url.rsplit('/',1)[1]] = max(reserved,sent)
    for post in posts:
        if post['status'] != 'sent':
            raise ServiceError('other_buffer_post_unresolved')
        raw_url = post.get('externalLink')
        if not isinstance(raw_url,str):
            raise ServiceError('buffer_history_url_missing')
        parsed = urlsplit(raw_url)
        url = canonical_video(parsed._replace(query='',fragment='').geturl())
        video_id = url.rsplit('/',1)[1]
        moment = parse_timestamp(post['sentAt'])
        if video_id not in events or moment > events[video_id]:
            events[video_id] = moment
    return sum(in_budget(moment,current) for moment in events.values())


def reconciliation_due(attempt,current):
    """Fast initial confirmation, then conserve the free API during outages."""
    last=attempt.get('last_reconcile_at')
    if not last:return True
    age=(current-parse_timestamp(attempt['reserved_at'])).total_seconds()
    interval=120 if age<600 else 600 if age<3600 else 3600
    return (current-parse_timestamp(last)).total_seconds()>=interval


class Worker:
    def __init__(self, store, gateway, verify):
        self.store, self.gateway, self.verify = store, gateway, verify

    def reconcile(self, state, sha, attempt, current):
        post_id = attempt.get('buffer_post_id')
        if not post_id:
            # Crash after accepting a send: recover only an exact deterministic
            # media title, with channel and creation-window checks. Never resend.
            overview = self.gateway.overview(stamp(min(history_start(current),
                parse_timestamp(attempt['reserved_at'])-dt.timedelta(minutes=5))),
                                              stamp(current+dt.timedelta(days=1)))
            candidates = []
            for post in observed_posts(overview):
                created = parse_timestamp(post['createdAt'])
                reserved = parse_timestamp(attempt['reserved_at'])
                titles = [asset.get('video',{}).get('title') for asset in post.get('assets',[])
                          if isinstance(asset.get('video'),dict)]
                if (attempt['asset_title'] in titles and
                        -5 <= (created-reserved).total_seconds() <= 600):
                    candidates.append(post)
            if len(candidates) != 1:
                return 'unresolved'
            post_id = candidates[0]['id']
            attempt['buffer_post_id'] = post_id
            attempt['status'] = 'pending'
            sha = self.store.save(state,sha)
        post = self.gateway.post(post_id)
        if post.get('channelId') != CHANNEL_ID or post.get('id') != post_id:
            raise ServiceError('reconciliation_channel_mismatch')
        if post.get('status') in ('scheduled','sending'):
            return 'pending'
        if post.get('status') != 'sent':
            return 'unresolved'
        url = canonical_video(post.get('externalLink'))
        sent_at = parse_timestamp(post['sentAt'])
        if (sent_at < parse_timestamp(attempt['reserved_at']) or
                sent_at > current+dt.timedelta(minutes=5)):
            raise ServiceError('reconciliation_time_mismatch')
        deadline=attempt.get('source_deadline')
        if deadline and sent_at>parse_timestamp(deadline):
            attempt.update(status='late_publication',sent_at=stamp(sent_at),tiktok_url=url)
            self.store.save(state,sha)
            raise ServiceError('published_after_source_deadline')
        if not self.verify(url):
            return 'unverified'
        attempt.update(status='verified_public',tiktok_url=url,
                       sent_at=stamp(sent_at),verified_at=stamp(current))
        state['queue'] = [item for item in state['queue'] if item['clip_id'] != attempt['clip_id']]
        self.store.save(state,sha)
        return 'verified_public'

    def run_one(self, config, external, current):
        if current.tzinfo is None:
            raise ServiceError('current_time_missing_timezone')
        state, sha = self.store.load()
        if not isinstance(state.get('attempts'),list) or not isinstance(state.get('queue'),list):
            raise ServiceError('invalid_state')
        unresolved = [attempt for attempt in state['attempts']
                      if attempt.get('status') != 'verified_public']
        if unresolved:
            if len(unresolved) != 1:
                raise ServiceError('multiple_unresolved_attempts')
            return self.reconcile(state,sha,unresolved[0],current)
        from tiktok14_publish import posting_time
        if not posting_time(current): return 'outside_window'
        permitted = sources(config)
        independent = config.get('accounting_mode','shared') == 'independent'
        external_events = {} if independent else history(external,current)
        if not state['queue']:
            return 'empty'
        slot=current.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H')
        if any(parse_timestamp(a['reserved_at']).strftime('%Y-%m-%dT%H')==slot
               for a in state['attempts']):
            return 'hour_complete'
        item = state['queue'][0]
        if (item.get('streamer') not in permitted or not eligible(item,current) or
                not re.fullmatch('[a-f0-9]{64}',str(item.get('sha256',''))) or
                not isinstance(item.get('caption'),str) or not item['caption'].strip() or
                len(item['caption']) > 2200):
            raise ServiceError('ineligible_queue_item')
        if identities(item)&set(state.get('used_ids',[])) or any(identities(attempt)&identities(item) or nearby_event(item,attempt) for attempt in state['attempts']):
            raise ServiceError('duplicate_clip')
        overview = self.gateway.overview(stamp(history_start(current)),
                                          stamp(current+dt.timedelta(days=1)))
        posts = observed_posts(overview)
        if any(post['status'] != 'sent' for post in posts):
            raise ServiceError('other_buffer_post_unresolved')
        if counted_events(state,external_events,posts,current) >= MAX_PER_DAY:
            return 'limit'
        title = 'tiktok14-'+item['clip_id']+'-'+item['sha256'][:12]+'.mp4'
        if any(asset.get('video',{}).get('title') == title for post in posts
               for asset in post.get('assets',[]) if isinstance(asset.get('video'),dict)):
            raise ServiceError('duplicate_media')
        attempt = {'clip_id':item['clip_id'],'reserved_at':stamp(current),
                   'streamer':item['streamer'],'sha256':item['sha256'],
                   'source_sha256':item.get('source_sha256',''),
                   'status':'reserved','asset_title':title,'video_url':item['video_url'],
                   'clip_slug':item.get('clip_slug',''),
                   'original_created_at':item['original_created_at'],
                   'source_deadline':stamp(parse_timestamp(item['original_created_at'])+dt.timedelta(hours=72))}
        state['attempts'].append(attempt)
        sha = self.store.save(state,sha)
        # No retry, even when the HTTP response is lost. A later run reconciles.
        result = self.gateway.create_post(item['video_url'],item['caption'],title)
        attempt.update(status='pending',buffer_post_id=result['id'])
        self.store.save(state,sha)
        return 'pending'
