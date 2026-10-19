"""Exercise reservation ordering and crash recovery with in-memory service boundaries."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tiktok14_worker as worker
from tiktok14_services import ServiceError, CHANNEL_ID, ORGANIZATION_ID

NOW = dt.datetime(2026, 10, 16, 12, tzinfo=dt.timezone.utc)
URL = 'https://www.tiktok.com/@ufo3103/video/7697189362877992225'
POST_ID = '6ad1e7e9e7970040db23ebed'


def add_review(item,current=NOW):
    """Synthetic reviewed-media receipt. It is never used with live services."""
    item.update(sha256=item.get('sha256','a'*64),transcript_sha256='c'*64,
                rights_status='user_declared_source_list')
    item['media_review']={'version':1,'decision':'approved','reviewer':'test-reviewer',
        'reviewed_at':current.isoformat(),'watched_full_video':True,
        'media_sha256':item['sha256'],'transcript_sha256':item['transcript_sha256'],
        'checks':{name:{'result':'pass','evidence':'Synthetic full-media test evidence'} for name in
            ('subtitles_accuracy','frame_composition','full_clip_payoff','audio_intelligibility','gaming_context')}}
    return item


def fixture():
    item = dict(clip_id='12345678', streamer='rewinside',
        delivery_route='github14', status='ready_tiktok14',
        editing_status='rendered_9x16_with_burned_subtitles',
        subtitle_verified=True, transcript_subtitles=True,
        original_created_at='2026-10-16T10:00:00Z',
        video_url='https://github.com/renejordan/twitch-clips/releases/download/tiktok14-2026-10/12345678.mp4',
        caption='Gaming clip', sha256='a'*64)
    state = {'version':1, 'queue':[add_review(item)], 'attempts':[]}
    config = {'sources':['rewinside'], 'legacy_sources':['trymacs']}
    external = {'complete':True, 'observed_at':'2026-10-16T12:00:00Z',
        'window_start':'2026-10-15T12:00:00Z', 'valid_until':'2026-10-16T12:05:00Z', 'posts':[]}
    overview = {
        'channel':{'id':CHANNEL_ID, 'organizationId':ORGANIZATION_ID, 'name':'ufo3103',
            'service':'tiktok', 'externalLink':'https://tiktok.com/@ufo3103',
            'timezone':'Europe/Berlin', 'scopes':['video.publish'],
            'isDisconnected':False,'isLocked':False,'isQueuePaused':False},
        'account':{'organizations':[{'id':ORGANIZATION_ID,'limits':{'scheduledPosts':10}}]},
        'dailyPostingLimits':[{'channelId':CHANNEL_ID,'isAtLimit':False,'limit':25,'sent':0,'scheduled':0}],
        **{key:{'edges':[], 'pageInfo':{'hasNextPage':False}} for key in ('recent','due','pending')}}
    return state, config, external, overview


class MemoryState:
    def __init__(self, state):
        self.data = copy.deepcopy(state)
        self.version = 1
        self.fail_write = False

    def load(self):
        return copy.deepcopy(self.data), str(self.version)

    def save(self, data, previous_sha):
        if self.fail_write or previous_sha != str(self.version):
            raise ServiceError('github_http_409')
        self.data = copy.deepcopy(data)
        self.version += 1
        return str(self.version)


class Gateway:
    def __init__(self, state, overview):
        self.store, self.snapshot = state, overview
        self.sent = []
        self.outcome = None
        self.result = {'id':POST_ID,'status':'sending','channelId':CHANNEL_ID,
                       'externalLink':None,'sentAt':None}

    def overview(self, since, until):
        self.window = (since,until)
        return copy.deepcopy(self.snapshot)

    def create_post(self, video_url, caption, asset_title):
        # Sending before durable reservation is the mutation this guard catches.
        if not self.store.data['attempts'] or self.store.data['attempts'][-1]['status'] != 'reserved':
            raise AssertionError('unreserved send')
        self.sent.append((video_url, caption, asset_title))
        if self.outcome: raise self.outcome
        return copy.deepcopy(self.result)

    def post(self, post_id):
        if post_id != POST_ID: raise AssertionError('wrong post read')
        return copy.deepcopy(self.result)


class WorkerTests(unittest.TestCase):
    def test_rate_limit_before_reservation_saves_cooldown(self):
        from unittest.mock import patch
        with patch.object(self.gateway,'overview',side_effect=ServiceError('buffer_http_429')) as overview:
            self.assertEqual(self.run_one(),'buffer_preflight_cooldown')
            self.assertEqual(self.run_one(),'send_cooldown')
            self.assertEqual(overview.call_count,1)
        self.assertEqual(self.store.data['attempts'],[])
        self.assertEqual(self.gateway.sent,[])

    def test_http_rate_limit_clears_only_an_unaccepted_reservation(self):
        self.gateway.outcome=ServiceError('buffer_http_429')
        self.assertEqual(self.run_one(),'create_rejected')
        self.assertEqual(self.store.data['attempts'],[])
        self.assertEqual(self.run_one(),'send_cooldown')
        self.assertEqual(len(self.gateway.sent),1)

    def test_explicit_create_rejection_is_retried_later_without_unknown_send(self):
        self.config['accounting_mode']='independent'
        self.gateway.outcome=worker.PostRejected('buffer_limit_reached')
        self.assertEqual(self.run_one(),'create_rejected')
        self.assertEqual(self.store.data['attempts'],[])
        self.assertEqual(len(self.store.data['rejected_sends']),1)
        self.assertEqual(len(self.store.data['queue']),1)
        self.gateway.outcome=None
        self.assertEqual(self.run_one(),'send_cooldown')
        later=NOW+dt.timedelta(hours=1)
        add_review(self.store.data['queue'][0],later)
        self.assertEqual(self.worker.run_one(self.config,self.external,later),'pending')
        self.assertEqual(len(self.store.data['attempts']),1)

    def test_invalid_input_rejection_discards_only_the_unsent_candidate(self):
        self.gateway.outcome=worker.PostRejected('buffer_invalid_input')
        self.assertEqual(self.run_one(),'create_rejected')
        self.assertEqual(self.store.data['attempts'],[])
        self.assertEqual(self.store.data['queue'],[])
        self.assertEqual(self.store.data['rejected'][0]['clip_id'],'12345678')

    def test_independent_mode_needs_no_metricool_history_and_allows_same_sources(self):
        self.config.update(accounting_mode='independent',legacy_sources=['rewinside'])
        self.assertEqual(self.worker.run_one(self.config,None,NOW),'pending')
        self.assertEqual(len(self.gateway.sent),1)

    def test_independent_mode_still_caps_its_own_fifteen_attempts(self):
        self.config.update(accounting_mode='independent',legacy_sources=['rewinside'])
        self.store.data['attempts'] = [dict(clip_id=str(i),status='verified_public',
            reserved_at='2026-10-16T10:00:00Z',sent_at='2026-10-16T10:01:00Z',
            tiktok_url='https://www.tiktok.com/@ufo3103/video/'+str(7000000000000000000+i)) for i in range(15)]
        self.assertEqual(self.worker.run_one(self.config,None,NOW),'limit')
        self.assertEqual(self.gateway.sent,[])

    def test_independent_mode_never_overrides_buffer_platform_quota(self):
        self.config.update(accounting_mode='independent',legacy_sources=['rewinside'])
        self.gateway.snapshot['dailyPostingLimits'][0]['isAtLimit']=True
        with self.assertRaises(ServiceError): self.worker.run_one(self.config,None,NOW)
        self.assertEqual(self.gateway.sent,[])

    def test_misspelled_mode_does_not_bypass_shared_accounting(self):
        self.config['accounting_mode']='indepedent'
        with self.assertRaises(ServiceError): self.worker.run_one(self.config,None,NOW)
        self.assertEqual(self.gateway.sent,[])

    def test_25_hour_berlin_day_requires_history_from_local_midnight(self):
        moment = dt.datetime(2026,10,25,22,30,tzinfo=dt.timezone.utc)
        external = {'complete':True,'posts':[],
            'observed_at':'2026-10-25T22:30:00Z',
            'window_start':'2026-10-24T22:30:00Z',
            'valid_until':'2026-10-25T22:35:00Z'}
        with self.assertRaises(ServiceError): worker.history(external,moment)

    def test_buffer_window_covers_full_25_hour_berlin_day(self):
        moment = dt.datetime(2026,10,25,22,30,tzinfo=dt.timezone.utc)
        self.external.update(observed_at='2026-10-25T22:30:00Z',
            window_start='2026-10-24T22:00:00Z',valid_until='2026-10-25T22:35:00Z')
        self.store.data['queue'][0]['original_created_at']='2026-10-25T20:00:00Z'
        add_review(self.store.data['queue'][0],moment)
        self.assertEqual(self.worker.run_one(self.config,self.external,moment),'pending')
        self.assertEqual(self.gateway.window[0],'2026-10-24T22:00:00Z')

    def setUp(self):
        state, self.config, self.external, overview = fixture()
        self.store = MemoryState(state)
        self.gateway = Gateway(self.store, overview)
        self.worker = worker.Worker(self.store, self.gateway, lambda url: url == URL)

    def run_one(self):
        return self.worker.run_one(self.config, self.external, NOW)

    def test_reserves_before_send_and_never_resends_pending_post(self):
        self.assertEqual(self.run_one(), 'pending')
        self.assertEqual(self.store.data['attempts'][0]['buffer_post_id'], POST_ID)
        self.assertEqual(self.run_one(), 'pending')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_conflicting_reservation_prevents_network_send(self):
        self.store.fail_write = True
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.gateway.sent, [])

    def test_unknown_send_outcome_remains_reserved_without_automatic_retry(self):
        self.gateway.outcome = ServiceError('transport_error')
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.store.data['attempts'][0]['status'], 'reserved')
        self.assertEqual(self.run_one(), 'unresolved')
        self.assertEqual(len(self.gateway.sent), 1)

    def recovered_post(self):
        return {**self.gateway.result,'status':'sent','externalLink':URL,
            'sentAt':'2026-10-16T12:00:02Z','createdAt':'2026-10-16T12:00:01Z',
            'assets':[{'source':self.gateway.sent[0][0],
                'video':{'title':self.gateway.sent[0][2]}}]}

    def test_recovers_unknown_acceptance_once_by_exact_media_identity(self):
        self.gateway.outcome = ServiceError('transport_error')
        with self.assertRaises(ServiceError): self.run_one()
        post = self.recovered_post()
        self.gateway.snapshot['recent']['edges'] = [{'node':post}]
        self.gateway.result = post
        self.assertEqual(self.run_one(),'verified_public')
        self.assertEqual(self.store.data['attempts'][0]['buffer_post_id'],POST_ID)
        self.assertEqual(len(self.gateway.sent),1)
        self.assertEqual(self.store.data['queue'],[])

    def test_ambiguous_recovery_never_selects_or_resends_either_post(self):
        self.gateway.outcome = ServiceError('transport_error')
        with self.assertRaises(ServiceError): self.run_one()
        post = self.recovered_post()
        self.gateway.snapshot['recent']['edges'] = [
            {'node':post},{'node':{**post,'id':'f'*24}}]
        self.assertEqual(self.run_one(),'unresolved')
        self.assertEqual(self.store.data['attempts'][0]['status'],'reserved')
        self.assertEqual(len(self.gateway.sent),1)

    def test_crash_after_accepted_send_preserves_durable_reservation(self):
        create = self.gateway.create_post
        def accept_and_break_write(*args):
            result = create(*args)
            self.store.fail_write = True
            return result
        self.gateway.create_post = accept_and_break_write
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.store.data['attempts'][0]['status'],'reserved')
        self.store.fail_write = False
        post = self.recovered_post()
        self.gateway.snapshot['recent']['edges'] = [{'node':post}]
        self.gateway.result = post
        self.assertEqual(self.run_one(),'verified_public')
        self.assertEqual(len(self.gateway.sent),1)

    def test_conflict_after_public_verification_never_causes_second_send(self):
        self.run_one()
        self.gateway.result.update(status='sent',externalLink=URL,sentAt='2026-10-16T12:00:02Z')
        self.store.fail_write = True
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.store.data['attempts'][0]['status'],'pending')
        self.store.fail_write = False
        self.assertEqual(self.run_one(),'verified_public')
        self.assertEqual(len(self.gateway.sent),1)

    def test_sent_status_requires_independent_public_verification(self):
        self.run_one()
        self.gateway.result.update(status='sent', externalLink=URL, sentAt='2026-10-16T12:00:02Z')
        self.worker.verify = lambda url: False
        self.assertEqual(self.run_one(), 'unverified')
        self.assertEqual(self.store.data['attempts'][0]['status'], 'pending')
        self.worker.verify = lambda url: url == URL
        self.assertEqual(self.run_one(), 'verified_public')
        self.assertEqual(self.store.data['queue'], [])
        self.assertEqual(len(self.gateway.sent), 1)

    def test_public_page_recovers_sent_post_after_oembed_failure_without_resending(self):
        import json
        from unittest.mock import patch
        import tiktok14_services as services
        self.run_one()
        self.gateway.result.update(status='sent',externalLink=URL,sentAt='2026-10-16T12:00:02Z')
        self.worker.verify=services.verify_public
        item={'id':URL.rsplit('/',1)[1],
              'author':{'uniqueId':'ufo3103','privateAccount':False,'secret':False},
              'privateItem':False,'secret':False,
              'video':{'id':URL.rsplit('/',1)[1],'duration':16}}
        data={'__DEFAULT_SCOPE__':{'webapp.video-detail':{
            'statusCode':0,'itemInfo':{'itemStruct':item}}}}
        page='<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'+json.dumps(data)+'</script>'
        with patch.object(services,'request_json',side_effect=ServiceError('tiktok_http_429')):
            with patch.object(services,'request_public_page',return_value=''):
                self.assertEqual(self.run_one(),'unverified')
                self.assertEqual(self.store.data['attempts'][0]['status'],'pending')
            with patch.object(services,'request_public_page',return_value=page):
                self.assertEqual(self.run_one(),'verified_public')
                self.assertEqual(self.run_one(),'empty')
        self.assertEqual(self.store.data['queue'],[])
        self.assertEqual(len(self.gateway.sent),1)

    def test_external_history_unknown_or_expired_prevents_sending(self):
        for changes in ({'complete':False}, {'valid_until':'2026-10-16T11:59:59Z'},
                        {'window_start':'2026-10-16T00:00:00Z'},
                        {'observed_at':'2026-10-16T10:00:00Z'}):
            self.external.update(changes)
            with self.assertRaises(ServiceError): self.run_one()
            self.assertEqual(self.gateway.sent, [])

    def test_external_posts_count_toward_fifteen_attempts(self):
        self.external['posts'] = [{'video_id':str(7000000000000000000+i),
            'at':'2026-10-16T10:00:00Z'} for i in range(15)]
        self.assertEqual(self.run_one(), 'limit')
        self.assertEqual(self.gateway.sent, [])

    def test_external_deduplication_and_calendar_midnight_rolling_limit(self):
        self.external['posts'] = [{'video_id':str(7000000000000000000+i),
            'at':'2026-10-15T21:59:00Z'} for i in range(13)]
        self.external['posts'].append(copy.deepcopy(self.external['posts'][0]))
        self.assertEqual(self.run_one(), 'pending')

    def test_missing_or_overlapping_source_permission_prevents_sending(self):
        for sources in ([], ['trymacs'], ['rewinside','trymacs'], ['bad/name']):
            self.config['sources'] = sources
            with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.gateway.sent, [])

    def test_nonpermitted_or_reused_clip_prevents_sending(self):
        self.config['sources'] = ['zombey']
        with self.assertRaises(ServiceError): self.run_one()
        self.config['sources'] = ['rewinside']
        self.store.data['attempts'] = [{'clip_id':'12345678','status':'verified_public',
            'reserved_at':'2026-10-10T12:00:00Z','sent_at':'2026-10-10T12:01:00Z',
            'tiktok_url':URL}]
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.gateway.sent, [])

    def test_incomplete_buffer_history_or_other_pending_post_prevents_send(self):
        self.gateway.snapshot['recent']['pageInfo']['hasNextPage'] = True
        with self.assertRaises(ServiceError): self.run_one()
        self.gateway.snapshot['recent']['pageInfo']['hasNextPage'] = False
        self.gateway.snapshot['pending']['edges'] = [{'node':{
            'id':'f'*24,'channelId':CHANNEL_ID,'status':'scheduled'}}]
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.gateway.sent, [])

    def test_wrong_channel_on_reconciliation_cannot_be_verified(self):
        self.run_one()
        self.gateway.result.update(status='sent',channelId='other',externalLink=URL,
                                   sentAt='2026-10-16T12:00:02Z')
        with self.assertRaises(ServiceError): self.run_one()
        self.assertEqual(self.store.data['attempts'][0]['status'], 'pending')


if __name__ == '__main__': unittest.main()
