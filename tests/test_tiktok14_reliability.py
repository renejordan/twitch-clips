"""Regression coverage for real empty runs, review gates and trigger idempotency."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tiktok14_cloud as cloud
import tiktok14_publish as publish
from test_tiktok14_worker import fixture, MemoryState, Gateway, NOW
from tiktok14_services import ServiceError
from tiktok14_worker import Worker
from tiktok14_quality import blocked,review_error
from tiktok14_media import metadata_decision


class ReliabilityTests(unittest.TestCase):
    def test_all_thirty_discovered_entries_are_considered(self):
        namespace=cloud.producer_namespace()
        entries=[{'url':f'https://clips.twitch.tv/Example-{i}'} for i in range(30)]
        namespace['run']=lambda *a,**k:subprocess.CompletedProcess([],0,json.dumps({'entries':entries}), '')
        self.assertEqual(len(namespace['channel_urls']('trymacs')),30)

    def test_auto_generated_subtitle_flags_are_not_editorial_review(self):
        state,_,_,_=fixture()
        state['queue'][0].pop('media_review',None)
        self.assertFalse(publish.eligible(state['queue'][0],NOW))

    def test_user_requested_fifteen_limit_is_explicit(self):
        self.assertEqual(publish.MAX_PER_DAY,15)

    def test_independent_route_counts_other_visible_posts(self):
        state,config,_,overview=fixture()
        config['accounting_mode']='independent'
        for i in range(15):
            overview['recent']['edges'].append({'node':{'id':f'{i:024x}',
                'channelId':'6ad16c0c778b240e2f21aca5','status':'sent',
                'sentAt':'2026-10-16T10:00:00Z',
                'externalLink':f'https://www.tiktok.com/@ufo3103/video/{7697189362877992225+i}'}})
        store=MemoryState(state)
        gateway=Gateway(store,overview)
        self.assertEqual(Worker(store,gateway,lambda _:True).run_one(config,None,NOW),'limit')
        self.assertEqual(gateway.sent,[])

    def test_banned_clip_never_passes_with_positive_flags(self):
        state,_,_,_=fixture()
        for clip_id in ('2845373187','1586086735','2914846804'):
            item=dict(state['queue'][0],clip_id=clip_id)
            self.assertFalse(publish.eligible(item,NOW))

    def test_same_utc_hour_cannot_create_a_second_post(self):
        state,config,_,overview=fixture()
        config['accounting_mode']='independent'
        state['attempts']=[{'clip_id':'previous','status':'verified_public',
            'reserved_at':'2026-10-16T12:00:00Z','sent_at':'2026-10-16T12:01:00Z',
            'tiktok_url':'https://www.tiktok.com/@ufo3103/video/7697189362877992225'}]
        current=NOW+dt.timedelta(minutes=20)
        store=MemoryState(state); gateway=Gateway(store,overview)
        self.assertEqual(Worker(store,gateway,lambda _:True).run_one(config,None,current),'hour_complete')
        self.assertEqual(gateway.sent,[])

    def test_cloud_has_nonpublishing_diagnostic_mode(self):
        self.assertTrue(callable(getattr(cloud,'diagnose',None)))

    def test_real_extractor_aliases_cannot_bypass_a_slug_ban(self):
        slug='GrossTubularAntelopeWow-1KWH2cn3DcuhqWSe'
        for row in ({'display_id':slug},{'webpage_url':'https://clips.twitch.tv/'+slug+'?utm_source=x#f'},
                {'original_url':'https://www.twitch.tv/bastighg/clip/'+slug}):
            self.assertTrue(blocked(row))

    def test_actual_creators_array_and_gaming_metadata(self):
        info={'id':'12345678','channel':'Trymacs','creators':['Trymacs'],
            'extractor_key':'TwitchClips','timestamp':NOW.timestamp()-3600,
            'duration':25,'view_count':1200,'categories':['Minecraft'],'title':'A game clip'}
        self.assertEqual(metadata_decision(info,'trymacs',NOW),('Minecraft','qualified_metadata'))
        self.assertEqual(metadata_decision(dict(info,categories=['Just Chatting']),'trymacs',NOW)[1],
                         'gaming_category_not_verified')
        self.assertEqual(metadata_decision(dict(info,creators=['Wrong']),'trymacs',NOW)[1],
                         'broadcaster_mismatch')

    def test_review_of_another_media_hash_or_future_timestamp_is_invalid(self):
        item=fixture()[0]['queue'][0]
        self.assertIsNone(review_error(item,NOW))
        item['sha256']='b'*64
        self.assertEqual(review_error(item,NOW),'review_not_bound_to_media')

    def test_long_clips_preserve_their_complete_setup_and_payoff(self):
        namespace=cloud.producer_namespace()
        self.assertEqual(namespace['pick_window'](60,[(12,40,'speech')]),(0,60))

    def test_missing_state_branch_is_never_reseeded_with_partial_history(self):
        class Missing:
            def call(self,*a,**k): raise ServiceError('github_http_404')
        with patch.object(cloud,'verify_public',return_value=True), \
                patch.object(cloud.GitHubState,'initialize') as initialize:
            with self.assertRaises(ServiceError): cloud.ensure_store(Missing())
            initialize.assert_not_called()

    def test_failed_listings_are_degraded_and_allow_a_later_retry(self):
        state,config,_,_=fixture()
        state['queue']=[]
        store=MemoryState(state)
        ns=cloud.producer_namespace()
        def failed(*a,**k): raise ServiceError('media_tool_failed')
        ns['run']=failed
        with patch.object(cloud,'producer_namespace',return_value=ns), \
                patch.object(cloud,'report_result'),patch.object(cloud,'Host') as host:
            self.assertEqual(cloud.prepare(store,config,{'processed_ids':[],'created':[]},NOW,host),'degraded')
            self.assertEqual(store.data['last_production']['counts']['listing_failed'],1)
            self.assertNotIn('last_prepare_hour',store.data)
            self.assertEqual(cloud.prepare(store,config,{'processed_ids':[],'created':[]},NOW,host),'degraded')
            host.assert_not_called()

    def test_review_packet_keeps_monthly_release_within_1000_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('tiktok.mp4','cover.jpg','transcript.json','source-frames.jpg','final-frames.jpg'):
                (root/name).write_bytes(b'synthetic media')
            calls=[]
            def command(args,check=True):
                calls.append(args)
                return subprocess.CompletedProcess(args,0,'{"assets":[]}', '')
            host=cloud.Host('synthetic-token')
            host.command=command
            host({'id':'12345678','channel_login':'trymacs'},root/'tiktok.mp4',root/'cover.jpg',NOW)
            upload=next(args for args in calls if args[:2]==['release','upload'])
            self.assertEqual(len(upload[3:]),2)
            self.assertTrue(upload[-1].endswith('-review.zip'))

    def test_media_tool_failures_and_quality_rejection_are_not_silent_empty(self):
        for failure,expected,counter in (('download','degraded','download_failed'),
                ('render','degraded','render_failed'),('asr','quality_rejected','asr_segment_uncertain')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                ns=cloud.producer_namespace()
                ns['OUT']=Path(directory)
                clip={'id':'12345678','clip_slug':'Example-123','channel_login':'rewinside',
                    'url':'https://clips.twitch.tv/Example-123','age_hours':2,'view_count':1200,
                    'duration':25,'title':'Gaming clip','rank':1,
                    'original_created_at':'2026-10-16T10:00:00Z'}
                ns['fetch_candidates']=lambda:[('rewinside',clip['url'])]
                ns['inspect_original']=lambda *a:clip
                def run(command,**kwargs):
                    if failure=='download' or (failure=='render' and command[0]=='ffprobe'):
                        raise ServiceError('media_tool_failed')
                    if command[0]=='yt-dlp': (Path(directory)/'source.mp4').write_bytes(b'source')
                    return subprocess.CompletedProcess([],0,'25', '')
                ns['run']=run
                if failure=='asr':
                    def uncertain(*a): raise ServiceError('asr_segment_uncertain')
                    ns['transcribe']=uncertain
                state,config,_,_=fixture();state['queue']=[]
                store=MemoryState(state)
                with patch.object(cloud,'producer_namespace',return_value=ns), \
                        patch.object(cloud,'report_result'),patch.object(cloud,'Host') as host:
                    self.assertEqual(cloud.prepare(store,config,{'created':[],'processed_ids':[]},NOW,host),expected)
                    self.assertEqual(store.data['last_production']['counts'][counter],1)
                    host.assert_not_called()

    def test_send_margin_and_late_publication_are_explicitly_enforced(self):
        item=fixture()[0]['queue'][0]
        item['original_created_at']=(NOW-dt.timedelta(hours=71,minutes=1)).isoformat()
        self.assertFalse(publish.eligible(item,NOW))
        state,config,_,overview=fixture(); config['accounting_mode']='independent'
        store=MemoryState(state); gateway=Gateway(store,overview)
        worker=Worker(store,gateway,lambda _:True)
        worker.run_one(config,None,NOW)
        attempt=store.data['attempts'][0]
        self.assertEqual(attempt.get('original_created_at'),'2026-10-16T10:00:00Z')
        self.assertEqual(attempt.get('source_deadline'),'2026-10-19T10:00:00Z')
        gateway.result.update(status='sent',sentAt='2026-10-19T10:01:00Z',
            externalLink='https://www.tiktok.com/@ufo3103/video/7697189362877992225')
        with self.assertRaisesRegex(ServiceError,'published_after_source_deadline'):
            worker.run_one(config,None,NOW+dt.timedelta(days=3))
        self.assertEqual(store.data['attempts'][0]['status'],'late_publication')
        self.assertEqual(len(gateway.sent),1)


if __name__=='__main__': unittest.main()
