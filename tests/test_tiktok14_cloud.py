"""Cloud orchestration tests, without credentials, network, render or upload."""
import base64
import contextlib
import datetime as dt
import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tiktok14_cloud as cloud
from tiktok14_services import ServiceError
from test_tiktok14_worker import MemoryState, fixture, NOW


class CloudTests(unittest.TestCase):
    def test_completed_rejection_survives_hard_stop_before_the_next_candidate(self):
        ns={'_report':{'rejected':[]}}
        def execute():
            ns['_report']['rejected'].append({'clip_id':'first-rejected','status':'quality_rejected','reason':'qa_visual_complete_payoff'})
            ns['_persist_rejections']()
            raise KeyboardInterrupt('simulated runner stop')
        ns['main']=execute;store=MemoryState({'version':1,'attempts':[],'queue':[]})
        with patch.object(cloud,'producer_namespace',return_value=ns):
            with self.assertRaises(KeyboardInterrupt):cloud.prepare(store,fixture()[1],{'created':[],'processed_ids':[]},NOW,None)
        self.assertEqual(store.data['rejected'][0]['clip_id'],'first-rejected')
        self.assertEqual(store.data['queue'],[])
    def test_own_duplicate_is_removed_and_search_continues_in_same_hour(self):
        for same_bytes in (True,False):
            state,config,_,_=fixture();item=state['queue'][0]
            item['source_sha256']='d'*64
            previous=dict(item,clip_id='older-id',status='verified_public',reserved_at='2026-10-16T11:00:00Z')
            if not same_bytes:previous['source_sha256']='e'*64
            else:previous['original_created_at']='2026-10-16T09:00:00Z'
            state['attempts']=[previous];state['last_prepare_hour']=NOW.strftime('%Y-%m-%dT%H')
            store=MemoryState(state);ns={'main':lambda:None}
            with patch.object(cloud,'producer_namespace',return_value=ns),patch.object(cloud,'report_result'):
                self.assertEqual(cloud.prepare(store,config,{'created':[],'processed_ids':[]},NOW,None),'empty')
            self.assertEqual(store.data['queue'],[])
            self.assertEqual(store.data['rejected'][0]['rejection_reason'],'known_source_duplicate')

    def test_publish_clears_own_duplicate_before_media_or_buffer_calls(self):
        state,config,_,_=fixture();item=state['queue'][0]
        state['attempts']=[dict(item,clip_id='different-id',reserved_at='2026-10-16T11:00:00Z',status='verified_public')]
        store=MemoryState(state)
        with patch.object(cloud,'legacy_running',return_value=False),patch.object(cloud,'assert_single_route'), \
                patch.object(cloud,'verify_media') as media,patch.object(cloud,'BufferGateway') as buffer:
            self.assertEqual(cloud.publish(store,config,None,'fake'),'known_source_duplicate_skipped')
            self.assertEqual(store.data['queue'],[]);media.assert_not_called();buffer.assert_not_called()

    def test_automatic_receipt_cannot_publish_before_live_commissioning(self):
        state,config,_,_=fixture();state['queue'][0]['media_review']={'version':2}
        with patch.dict(os.environ,TIKTOK14_AUTOREVIEW_ENABLED=''),patch.object(cloud,'legacy_running',return_value=False), \
                patch.object(cloud,'read_legacy',return_value={'created':[],'processed_ids':[]}), \
                patch.object(cloud,'assert_single_route'),patch.object(cloud,'eligible',return_value=True), \
                patch.object(cloud,'verify_media') as media,patch.object(cloud,'BufferGateway') as buffer:
            self.assertEqual(cloud.publish(MemoryState(state),config,None,'fake'),'automatic_commissioning_required')
            media.assert_not_called();buffer.assert_not_called()
    def test_incomplete_final_evidence_is_rejected_before_immutable_hosting(self):
        from test_tiktok14_autoreview import AutoReviewTests
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            movie=Path(directory)/'tiktok.mp4';movie.write_bytes(b'fixture video')
            transcript=movie.parent/'transcript.json';transcript.write_text('{}')
            item=fixture()[0]['queue'][0]
            item.update(source_sha256='d'*64,sha256=hashlib.sha256(movie.read_bytes()).hexdigest(),
                transcript_sha256=hashlib.sha256(transcript.read_bytes()).hexdigest())
            evidence=AutoReviewTests().evidence(item);evidence['final_visual']['evidence']=''
            clip={'id':item['clip_id'],'_qa_evidence':evidence}
            ns={}
            ns['main']=lambda:ns['release'](clip,movie,movie,NOW)
            host=Mock();store=MemoryState({'version':1,'attempts':[],'queue':[]})
            with patch.object(cloud,'producer_namespace',return_value=ns),patch.object(cloud,'report_result'):
                with self.assertRaisesRegex(ServiceError,'automatic_evidence_invalid_before_host'):
                    cloud.prepare(store,fixture()[1],{'created':[],'processed_ids':[]},NOW,host)
            host.assert_not_called()
            self.assertEqual(store.data['queue'],[])
            self.assertEqual(store.data['last_production']['result'],'degraded')

    def test_known_running_auto20_prevents_new_media_or_buffer_transfer(self):
        state,config,_,_=fixture()
        with patch.object(cloud,'legacy_running',return_value=True), \
                patch.object(cloud,'verify_media') as media,patch.object(cloud,'BufferGateway') as buffer:
            self.assertEqual(cloud.publish(MemoryState(state),config,None,'fake'),'auto20_running')
            media.assert_not_called()
            buffer.assert_not_called()

    def test_real_producer_stops_after_failed_durable_handoff(self):
        store=MemoryState({'version':1,'attempts':[],'queue':[]})
        save=store.save
        def fail_handoff(data,sha):
            if data['queue']:raise ServiceError('state_write_failed')
            return save(data,sha)
        store.save=fail_handoff
        _,config,_,_=fixture()
        namespace=cloud.producer_namespace()
        clip={'id':'12345678','clip_slug':'Example-123','channel_login':'rewinside',
            'url':'https://clips.twitch.tv/Example-123','age_hours':2,'view_count':1200,
            'duration':22,'title':'Gaming clip','rank':1,
            'original_created_at':'2026-10-16T10:00:00Z'}
        namespace['fetch_candidates']=lambda:[('rewinside',clip['url'])]*2
        namespace['inspect_original']=lambda *args:clip
        namespace['download']=lambda *args:Path('fake.mp4')
        namespace['render']=lambda *args:(Path('fake.mp4'),Path('fake.jpg'),True)
        hosted=[]
        def host(*args):
            hosted.append(True)
            return 'https://github.com/renejordan/twitch-clips/releases/download/tiktok14-2026-10/12345678.mp4','cover','a'*64
        with patch.object(cloud,'producer_namespace',return_value=namespace):
            with self.assertRaises(ServiceError):
                cloud.prepare(store,config,{'processed_ids':[],'created':[]},NOW,host)
        self.assertEqual(store.data['queue'],[])
        self.assertEqual(len(hosted),1)

    def test_initial_state_permanently_excludes_completed_single_test(self):
        state=cloud.initial_state()
        self.assertEqual(state['attempts'][0]['clip_id'],'761785150')
        self.assertEqual(state['attempts'][0]['status'],'verified_public')
        self.assertEqual(state['attempts'][0]['tiktok_url'],
            'https://www.tiktok.com/@ufo3103/video/7697189362877992225')

    def test_legacy_originals_are_excluded_by_both_id_and_slug(self):
        legacy={'processed_ids':['already-used'],'created':[
            {'clip_id':'987654321','clip_slug':'SomeSlug',
             'source_url':'https://clips.twitch.tv/AnotherSlug'}]}
        ids=cloud.legacy_ids(legacy)
        self.assertTrue({'already-used','987654321','SomeSlug','AnotherSlug'} <= ids)
        with self.assertRaises(ServiceError): cloud.legacy_ids({'processed_ids':None})

    def test_store_initialization_never_replaces_a_corrupt_existing_branch(self):
        class Git:
            def call(self,method,path,body=None):
                if path.startswith('/git/ref/'): return {'ref':'refs/heads/tiktok14-state'}
                raise ServiceError('github_http_404')
        with patch.object(cloud.GitHubState,'initialize') as initialize:
            with self.assertRaises(ServiceError): cloud.ensure_store(Git())
            initialize.assert_not_called()

    def test_production_does_not_start_with_an_unresolved_send(self):
        state=cloud.initial_state()
        state['attempts'].append({'clip_id':'new','status':'reserved'})
        store=MemoryState(state)
        with patch.object(cloud,'producer_namespace') as producer:
            self.assertEqual(cloud.prepare(store,{'sources':['trymacs'],'legacy_sources':['trymacs'],
                'accounting_mode':'independent'},{'processed_ids':[],'created':[]},NOW,lambda *args:None),'pending')
            producer.assert_not_called()

    def test_producer_handoff_persists_hash_and_does_not_change_legacy_state(self):
        state,config,_,_=fixture()
        store=MemoryState({'version':1,'attempts':[],'queue':[]})
        record=state['queue'][0]
        legacy={'processed_ids':['old'],'created':[]}
        before=json.dumps(legacy,sort_keys=True)
        namespace={}
        def execute():
            data=namespace['read_state']()
            record['sha256']=None
            video=Path('video.mp4')
            namespace['release']({'id':record['clip_id'],'channel_login':'rewinside'},video,video,NOW)
            data['created'].append(record)
            namespace['save_state'](data)
        namespace['main']=execute
        def host(*args): return record['video_url'],record['video_url']+'.jpg','b'*64
        with patch.object(cloud,'producer_namespace',return_value=namespace), \
                patch.object(cloud,'report_result'):
            self.assertEqual(cloud.prepare(store,config,legacy,NOW,host),'needs_review')
        self.assertEqual(store.data['queue'][0]['sha256'],'b'*64)
        self.assertFalse(store.data['queue'][0]['subtitle_verified'])
        self.assertEqual(store.data['queue'][0]['status'],'awaiting_review_tiktok14')
        self.assertEqual(json.dumps(legacy,sort_keys=True),before)

    def test_no_cli_publishing_from_review_branch_or_untrusted_repo(self):
        for env in ({'GITHUB_REPOSITORY':'other/repo','GITHUB_REF':'refs/heads/main'},
                    {'GITHUB_REPOSITORY':'renejordan/twitch-clips',
                     'GITHUB_REF':'refs/heads/codex/tiktok14-safety-audit'}):
            with patch.dict(os.environ,env,clear=True),patch.object(cloud,'GitHubAPI') as api:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertNotEqual(cloud.main('publish'),0)
                api.assert_not_called()
                self.assertNotIn('Traceback',output.getvalue())

    def test_subprocess_environment_excludes_all_service_credentials(self):
        with patch.dict(os.environ,{'GH_TOKEN':'fake-gh','BUFFER_API_KEY':'fake-buffer',
                'TIKTOK_SESSIONID':'fake-cookie','PATH':'safe-path'},clear=True):
            env=cloud.child_environment()
        self.assertEqual(env['PATH'],'safe-path')
        self.assertFalse(any(value.startswith('fake-') for value in env.values()))

    def test_media_must_match_sha_and_only_trusted_redirects_are_allowed(self):
        for url in ('http://github.com/a.mp4','https://evil.test/a.mp4',
                    'https://github.com/renejordan/twitch-clips/releases/download/tiktok14-2026-10/a.mp4?x=1'):
            with patch.object(cloud,'build_opener') as opener:
                with self.assertRaises(ServiceError): cloud.verify_media(url,'a'*64)
                opener.assert_not_called()
        self.assertFalse(cloud.allowed_media_redirect('https://evil.test/file'))
        self.assertFalse(cloud.allowed_media_redirect('https://release-assets.githubusercontent.com.evil.test/file'))
        self.assertFalse(cloud.allowed_media_redirect('https://release-assets.githubusercontent.com:444/file'))
        self.assertTrue(cloud.allowed_media_redirect('https://release-assets.githubusercontent.com/file?sig=public'))


if __name__=='__main__': unittest.main()
