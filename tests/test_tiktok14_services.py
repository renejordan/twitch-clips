"""Offline security and persistence tests; all network boundaries are mocked."""
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tiktok14_services as services


class ServiceTests(unittest.TestCase):
    def test_public_verification_requires_exact_account_and_video(self):
        good = {'provider_name': 'TikTok', 'type': 'video',
                'author_url': 'https://www.tiktok.com/@ufo3103',
                'html': '<blockquote data-video-id="7697189362877992225"></blockquote>'}
        with patch.object(services, 'request_json', return_value=good):
            self.assertTrue(services.verify_public('https://tiktok.com/@ufo3103/video/7697189362877992225'))
        for field, value in [('author_url', 'https://www.tiktok.com/@other'),
                             ('provider_name', 'Other'), ('type', 'photo'),
                             ('html', '<p>7697189362877992225</p>')]:
            with patch.object(services, 'request_json', return_value={**good, field:value}):
                self.assertFalse(services.verify_public('https://www.tiktok.com/@ufo3103/video/7697189362877992225'))

    def test_untrusted_video_urls_never_make_requests(self):
        for url in ('http://tiktok.com/@ufo3103/video/123',
                    'https://www.tiktok.com.evil.test/@ufo3103/video/123',
                    'https://tiktok.com/@other/video/123',
                    'https://tiktok.com/@ufo3103/video/123?token=bad'):
            with patch.object(services, 'request_json') as request:
                with self.assertRaises(services.ServiceError):
                    services.verify_public(url)
                request.assert_not_called()

    def test_api_errors_do_not_echo_remote_details(self):
        gateway = services.BufferGateway('FAKE-CREDENTIAL')
        with patch.object(services, 'request_json', return_value={'errors':[{'message':'PRIVATE DETAIL FAKE-CREDENTIAL'}]}):
            with self.assertRaises(services.ServiceError) as error:
                gateway.graphql('query Check { account { id } }')
            self.assertNotIn('FAKE-CREDENTIAL', str(error.exception))
            self.assertNotIn('PRIVATE DETAIL', str(error.exception))

    def test_post_creation_has_no_implicit_retry(self):
        gateway = services.BufferGateway('FAKE-CREDENTIAL')
        with patch.object(services, 'request_json', side_effect=TimeoutError('PRIVATE DETAIL')) as request:
            with self.assertRaises(TimeoutError):
                gateway.create_post('https://example.com/a.mp4', 'safe caption', 'creator-123.mp4')
            self.assertEqual(request.call_count, 1)

    def test_create_post_refuses_api_union_error_and_carries_fixed_channel(self):
        gateway = services.BufferGateway('FAKE-CREDENTIAL')
        with patch.object(gateway, 'graphql', return_value={'createPost':{'__typename':'InvalidInputError','message':'PRIVATE'}}) as query:
            with self.assertRaises(services.ServiceError):
                gateway.create_post('https://example.com/a.mp4', 'caption', 'creator-123.mp4')
            values = query.call_args.args[1]['input']
            self.assertEqual(values['channelId'], services.CHANNEL_ID)
            self.assertEqual(values['mode'], 'shareNow')
            self.assertEqual(values['schedulingType'], 'automatic')
            self.assertFalse(values['saveToDraft'])

    def test_orphan_state_initialization_contains_no_workflow_files(self):
        calls = []
        class FakeGit:
            def call(self, method, path, body=None):
                calls.append((method, path, body))
                if path == '/git/trees': return {'sha':'TREE'}
                if path == '/git/commits': return {'sha':'COMMIT'}
                if path == '/git/refs': return {'ref':'refs/heads/tiktok14-state'}
                raise AssertionError(path)
        store = services.GitHubState(FakeGit())
        store.initialize({'version':1,'attempts':[],'queue':[]})
        tree = calls[0][2]['tree']
        self.assertEqual([x['path'] for x in tree], ['state.json'])
        self.assertEqual(calls[1][2]['parents'], [])
        self.assertNotIn('base_tree', calls[0][2])
        self.assertEqual(calls[2][2]['ref'], 'refs/heads/tiktok14-state')

    def test_state_save_carries_compare_and_swap_sha_and_never_changes_main(self):
        class FakeGit:
            def call(self, method, path, body=None):
                self.method, self.path, self.body = method,path,body
                return {'content':{'sha':'NEW'}}
        git = FakeGit()
        store = services.GitHubState(git)
        new = store.save({'version':1,'queue':[],'attempts':[]}, 'PREVIOUS')
        self.assertEqual(new, 'NEW')
        self.assertEqual(git.method,'PUT')
        self.assertEqual(git.path, '/contents/state.json')
        self.assertEqual(git.body['branch'],'tiktok14-state')
        self.assertEqual(git.body['sha'],'PREVIOUS')
        self.assertEqual(json.loads(base64.b64decode(git.body['content']))['version'],1)

    def test_state_conflicts_are_not_retried(self):
        git = unittest.mock.Mock()
        git.call.side_effect = services.ServiceError('github_http_409')
        with self.assertRaises(services.ServiceError):
            services.GitHubState(git).save({'version':1,'queue':[],'attempts':[]}, 'OLD')
        self.assertEqual(git.call.call_count,1)

    def test_state_read_rejects_wrong_shape(self):
        git = unittest.mock.Mock()
        git.call.return_value = {'sha':'SHA','encoding':'base64',
                                'content':base64.b64encode(b'{"version":1,"attempts":[]}').decode()}
        with self.assertRaises(services.ServiceError):
            services.GitHubState(git).load()

    def test_http_rejects_unapproved_hosts_before_credentials_are_used(self):
        with patch.object(services, 'build_opener') as opener:
            with self.assertRaises(services.ServiceError):
                services.request_json('https://evil.test/api','FAKE-CREDENTIAL')
            opener.assert_not_called()

    def test_authenticated_requests_do_not_follow_redirects(self):
        self.assertIsNone(services.NoRedirect().redirect_request(
            services.Request(services.BUFFER_URL),None,302,'Found',{},'https://evil.test'))

    def test_http_errors_and_invalid_json_do_not_reveal_remote_data(self):
        opener = unittest.mock.Mock()
        opener.open.side_effect = HTTPError(services.BUFFER_URL,401,
            'PRIVATE FAKE-CREDENTIAL',{},io.BytesIO(b'PRIVATE FAKE-CREDENTIAL'))
        with patch.object(services,'build_opener',return_value=opener):
            with self.assertRaises(services.ServiceError) as error:
                services.request_json(services.BUFFER_URL,'FAKE-CREDENTIAL')
        self.assertEqual(str(error.exception),'buffer_http_401')
        self.assertNotIn('FAKE-CREDENTIAL',str(error.exception))
        self.assertEqual(opener.open.call_count,1)
        class Opener:
            def open(self,*args,**kwargs):
                return io.BytesIO(b'<html>PRIVATE FAKE-CREDENTIAL</html>')
        with patch.object(services,'build_opener',return_value=Opener()):
            with self.assertRaises(services.ServiceError) as error:
                services.request_json(services.BUFFER_URL,'FAKE-CREDENTIAL')
        self.assertEqual(str(error.exception),'invalid_json')

    def test_request_size_is_bounded_and_tiktok_never_receives_credentials(self):
        class Opener:
            def open(self,*args,**kwargs):
                return io.BytesIO(b' '*(services.MAX_BYTES+1))
        with patch.object(services,'build_opener',return_value=Opener()):
            with self.assertRaises(services.ServiceError) as error:
                services.request_json(services.BUFFER_URL,'FAKE-CREDENTIAL')
        self.assertEqual(str(error.exception),'response_too_large')
        with patch.object(services,'build_opener') as opener:
            with self.assertRaises(services.ServiceError):
                services.request_json('https://www.tiktok.com/oembed?url=anything','FAKE-CREDENTIAL')
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
