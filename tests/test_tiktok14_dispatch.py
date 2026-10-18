import datetime as dt
import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


class DispatchTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('tiktok14_dispatch'))
        import tiktok14_dispatch
        return tiktok14_dispatch

    def test_completed_hour_and_active_run_suppress_duplicate_dispatch(self):
        dispatch=self.module()
        current=dt.datetime(2026,10,18,8,20,tzinfo=dt.timezone.utc)
        state={'attempts':[],'queue':[],'last_prepare_hour':'2026-10-18T08'}
        self.assertEqual(dispatch.decision(state,[],current),'hour_complete')
        self.assertEqual(dispatch.decision({'attempts':[],'queue':[]},
            [{'status':'in_progress','head_branch':'main','event':'workflow_dispatch'}],current),'active_run')

    def test_pending_send_reconciles_even_after_completed_hour(self):
        dispatch=self.module()
        current=dt.datetime(2026,10,18,8,20,tzinfo=dt.timezone.utc)
        self.assertEqual(dispatch.decision({'queue':[],'last_prepare_hour':'2026-10-18T08',
            'attempts':[{'status':'reserved'}]},[],current),'dispatch')


if __name__=='__main__': unittest.main()
