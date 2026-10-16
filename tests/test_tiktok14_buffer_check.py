"""Connection diagnostics use fake credentials and never contact Buffer."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tiktok14_buffer_check as check


def response_data():
    return {'data': {
        'account': {'organizations': [{'id': check.ORGANIZATION_ID,
            'limits': {'scheduledPosts': 10}}]},
        'channel': {'id': check.CHANNEL_ID, 'name': 'ufo3103', 'service': 'tiktok',
            'organizationId': check.ORGANIZATION_ID,
            'externalLink': 'https://tiktok.com/@ufo3103',
            'scopes': ['video.publish'], 'isDisconnected': False,
            'isLocked': False, 'isQueuePaused': False, 'timezone': 'Europe/Berlin'},
        'dailyPostingLimits': [{'channelId': check.CHANNEL_ID, 'isAtLimit': False,
            'limit': 25, 'scheduled': 0, 'sent': 0}]}}


class BufferConnectionTests(unittest.TestCase):
    def test_verified_identity_and_capabilities_return_only_allowed_summary(self):
        result = check.validate(response_data())
        self.assertEqual(result, {'queue_capacity': 10, 'buffer_daily_limit': 25,
                                 'buffer_scheduled': 0, 'buffer_sent': 0})

    def test_wrong_identity_or_unready_connection_is_rejected(self):
        for field, value in [('id', 'other'), ('name', 'other'),
                ('service', 'instagram'), ('organizationId', 'other'),
                ('externalLink', 'https://tiktok.com/@other'),
                ('isDisconnected', True), ('isLocked', True),
                ('isQueuePaused', True), ('timezone', 'UTC'), ('scopes', [])]:
            with self.subTest(field=field):
                body = response_data()
                body['data']['channel'][field] = value
                with self.assertRaises(check.CheckFailed):
                    check.validate(body)

    def test_missing_flags_and_wrong_organization_fail_closed(self):
        for field in ('isDisconnected', 'isLocked', 'isQueuePaused'):
            body = response_data()
            del body['data']['channel'][field]
            with self.assertRaises(check.CheckFailed):
                check.validate(body)
        body = response_data()
        body['data']['account']['organizations'][0]['id'] = 'other'
        with self.assertRaises(check.CheckFailed):
            check.validate(body)

    def test_partial_errors_and_invalid_limits_are_rejected(self):
        variants = []
        body = response_data()
        body['errors'] = [{'message': 'PRIVATE SERVER DETAIL'}]
        variants.append(body)
        for field, value in [('channelId', 'other'), ('isAtLimit', True),
                             ('sent', -1), ('scheduled', True), ('limit', None)]:
            body = response_data()
            body['data']['dailyPostingLimits'][0][field] = value
            variants.append(body)
        for body in variants + [{}, {'data': None}]:
            with self.assertRaises(check.CheckFailed):
                check.validate(body)

    def test_empty_secret_makes_no_request(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(check, 'fetch') as fetch:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(check.main(), 1)
            fetch.assert_not_called()
            self.assertIn('BUFFER_API_KEY is missing', output.getvalue())

    def test_error_output_never_contains_key_or_server_details(self):
        for error in (HTTPError(check.ENDPOINT, 401, 'PRIVATE SERVER DETAIL', {}, None),
                      RuntimeError('FAKE-SECRET PRIVATE SERVER DETAIL'),
                      check.CheckFailed('invalid_response')):
            with patch.dict('os.environ', {'BUFFER_API_KEY': 'FAKE-SECRET'}, clear=True), \
                    patch.object(check, 'fetch', side_effect=error):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(check.main(), 1)
                self.assertNotIn('FAKE-SECRET', output.getvalue())
                self.assertNotIn('PRIVATE SERVER DETAIL', output.getvalue())

    def test_success_output_does_not_echo_extra_response_data(self):
        body = response_data()
        body['data']['account']['email'] = 'PRIVATE SERVER DETAIL'
        body['data']['channel']['extra'] = 'FAKE-SECRET'
        with patch.dict('os.environ', {'BUFFER_API_KEY': 'FAKE-SECRET'}, clear=True), \
                patch.object(check, 'fetch', return_value=body):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(check.main(), 0)
            self.assertIn('TikTok @ufo3103', output.getvalue())
            self.assertNotIn('FAKE-SECRET', output.getvalue())
            self.assertNotIn('PRIVATE SERVER DETAIL', output.getvalue())

    def test_request_is_fixed_read_only_and_sends_key_only_in_header(self):
        class Response(io.BytesIO):
            pass
        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return Response(json.dumps(response_data()).encode())
        opener = Opener()
        with patch.object(check, 'build_opener', return_value=opener):
            check.fetch('FAKE-SECRET')
        request = opener.request
        self.assertEqual(request.full_url, 'https://api.buffer.com')
        self.assertEqual(request.get_header('Authorization'), 'Bearer FAKE-SECRET')
        body = json.loads(request.data)
        self.assertTrue(body['query'].startswith('query TikTok14ConnectionReadOnly'))
        self.assertNotIn('mutation', body['query'])
        self.assertNotIn('FAKE-SECRET', request.data.decode())
        self.assertEqual(opener.timeout, 20)

    def test_redirects_are_not_followed_with_credentials(self):
        request = check.Request(check.ENDPOINT, headers={'Authorization': 'Bearer FAKE'})
        self.assertIsNone(check.NoRedirect().redirect_request(
            request, None, 302, 'Found', {}, 'https://example.com'))

    def test_oversized_or_invalid_response_fails(self):
        class Opener:
            def __init__(self, data):
                self.data = data
            def open(self, *args, **kwargs):
                return io.BytesIO(self.data)
        for data in (b'x' * (check.MAX_RESPONSE_BYTES + 1), b'not-json'):
            with patch.object(check, 'build_opener', return_value=Opener(data)):
                with self.assertRaises(check.CheckFailed):
                    check.fetch('FAKE-SECRET')


if __name__ == '__main__':
    unittest.main()
