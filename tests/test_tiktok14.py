"""Offline regression tests. No real credentials, browser, download or upload."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import tiktok14_prepare as prepare
import tiktok14_publish as publish
from test_tiktok14_worker import add_review


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.moment = dt.datetime(2026, 10, 16, 12, tzinfo=dt.timezone.utc)
        self.attempt = {'clip_id': '12345678', 'reserved_at': '2026-10-14T10:00:00Z',
                        'status': 'reported_success_unverified'}
        self.item = dict(delivery_route='github14', status='ready_tiktok14',
                         editing_status='rendered_9x16_with_burned_subtitles',
                         subtitle_verified=True, transcript_subtitles=True, clip_id='12345678',
                         original_created_at='2026-10-16T10:00:00Z',
                         video_url=publish.REPO_PREFIX+'2026-10/streamer-12345678.mp4')
        add_review(self.item,self.moment)

    def test_unverified_browser_success_blocks_even_after_24_hours(self):
        self.assertFalse(publish.can_reserve({'attempts': [self.attempt]}, self.moment)[0])

    def test_unknown_journal_status_fails_closed(self):
        self.assertFalse(publish.can_reserve({'attempts': [dict(self.attempt, status='typo')]}, self.moment)[0])

    def test_naive_original_timestamp_is_rejected(self):
        self.assertFalse(publish.eligible(dict(self.item, original_created_at='2026-10-16T10:00:00'), self.moment))

    def test_naive_journal_timestamp_is_rejected(self):
        self.assertFalse(publish.can_reserve({'attempts': [dict(self.attempt, status='verified_public',
                                            reserved_at='2026-10-16T10:00:00')]}, self.moment)[0])

    def test_future_journal_timestamp_blocks(self):
        self.assertFalse(publish.can_reserve({'attempts': [dict(self.attempt, status='verified_public',
                                            reserved_at='2026-10-17T10:00:00Z')]}, self.moment)[0])

    def test_empty_history_allows_selection_but_fourteen_attempts_do_not(self):
        self.assertTrue(publish.can_reserve({'attempts': []}, self.moment)[0])
        attempts = [dict(self.attempt, clip_id=str(i), status='verified_public',
                         reserved_at='2026-10-16T10:00:00Z') for i in range(15)]
        self.assertFalse(publish.can_reserve({'attempts': attempts}, self.moment)[0])

    def test_valid_release_video_remains_eligible(self):
        self.assertTrue(publish.eligible(self.item, self.moment))

    def test_release_url_cannot_escape_tag_or_add_query(self):
        for suffix in ('2026-10/../elsewhere.mp4', '2026-10/a.mp4?redirect=1',
                       '2026-10/a.mp4#fragment', 'not-a-month/a.mp4', '2026-10/a.html'):
            with self.subTest(suffix=suffix):
                self.assertFalse(publish.eligible(dict(self.item, video_url=publish.REPO_PREFIX+suffix), self.moment))

    def test_missing_or_malformed_journal_fails_closed(self):
        for journal in ({}, {'attempts': None}, {'attempts': ['bad']}, {'attempts': [{}]}):
            with self.subTest(journal=journal):
                self.assertFalse(publish.can_reserve(journal, self.moment)[0])

    def test_uncommissioned_entrypoints_never_change_state(self):
        original = {'version': 1, 'attempts': []}
        for action in ('preflight', 'reserve', 'upload'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temporary:
                journal = Path(temporary) / 'state/auto14_publish.json'
                journal.parent.mkdir()
                journal.write_text(json.dumps(original), encoding='utf-8')
                environment = dict(os.environ, TIKTOK14_ENABLED='true',
                                   TIKTOK_SESSIONID='synthetic-test-value-not-a-credential')
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/tiktok14_publish.py'), action],
                                        cwd=temporary, env=environment, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 3)
                self.assertIn('not commissioned', result.stdout)
                self.assertNotIn(environment['TIKTOK_SESSIONID'], result.stdout + result.stderr)
                self.assertEqual(json.loads(journal.read_text(encoding='utf-8')), original)


class ProducerTests(unittest.TestCase):
    def test_selected_source_must_match_actual_original_creator(self):
        moment = dt.datetime(2026, 10, 16, 12, tzinfo=dt.timezone.utc)
        metadata = dict(id='12345678', webpage_url='https://clips.twitch.tv/Example-123',
            view_count=1200, duration=22, timestamp=(moment-dt.timedelta(hours=2)).timestamp(),
            extractor_key='TwitchClips', title='Gaming clip', channel='OtherCreator',
            creator='OtherCreator')
        with tempfile.TemporaryDirectory() as temporary:
            code = self.generated(temporary)
            response = subprocess.CompletedProcess([],0,stdout=json.dumps(metadata))
            with patch.object(subprocess,'run',return_value=response):
                self.assertIsNone(code['inspect_original']('trymacs','https://clips.twitch.tv/Example-123',moment))
            metadata.update(channel='Trymacs',creator='Trymacs')
            response.stdout = json.dumps(metadata)
            with patch.object(subprocess,'run',return_value=response):
                self.assertEqual(code['inspect_original']('trymacs','https://clips.twitch.tv/Example-123',moment)['channel_login'],'trymacs')

    def generated(self, temporary):
        with patch.object(prepare, 'WORKFLOW', ROOT / '.github/workflows/tiktok.yml'), \
                patch.object(prepare, 'SCRIPT', Path(temporary) / 'pipeline.py'), \
                contextlib.redirect_stdout(io.StringIO()):
            prepare.generate()
            return runpy.run_path(str(prepare.SCRIPT))

    def test_31_day_month_allows_465_productions(self):
        with tempfile.TemporaryDirectory() as temporary:
            code = self.generated(temporary)
            moment = dt.datetime(2026, 10, 31, 12, tzinfo=dt.timezone.utc)
            old = {'created_at': '2026-10-01T12:00:00Z'}
            self.assertTrue(code['can_prepare']({'created': [old] * 430}, moment)[0])
            self.assertFalse(code['can_prepare']({'created': [old] * 465}, moment)[0])

    def test_legacy_created_ids_and_source_slugs_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            code = self.generated(temporary)
            legacy = Path(temporary) / 'legacy.json'
            legacy.write_text(json.dumps({'processed_ids': [], 'created': [
                {'clip_id': '987654321', 'source_url': 'https://clips.twitch.tv/Example-123'}
            ]}), encoding='utf-8')
            # The generated producer reads this exact legacy path; isolate only that IO boundary.
            real_read = Path.read_text
            real_exists = Path.exists
            def read(path, *args, **kwargs):
                return real_read(legacy if path == Path('state/auto20.json') else path, *args, **kwargs)
            def exists(path):
                return path == Path('state/auto20.json') or real_exists(path)
            with patch.object(Path, 'read_text', read), patch.object(Path, 'exists', exists):
                used, urls = code['used_ids']({'processed_ids': [], 'created': []})
            self.assertIn('987654321', used)
            self.assertIn('Example-123', used)
            self.assertIn('https://clips.twitch.tv/Example-123', urls)


if __name__ == '__main__':
    unittest.main()
