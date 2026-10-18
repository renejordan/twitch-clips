import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tiktok14_cloud as cloud
from tiktok14_media import configure
from tiktok14_services import ServiceError
from test_tiktok14_worker import fixture, MemoryState, NOW

class ReviewOperationsTests(unittest.TestCase):
    def test_uncertain_asr_produces_evidence_but_never_an_approval(self):
        word=lambda text,p:types.SimpleNamespace(start=0.,end=1.,word=text,probability=p)
        segment=types.SimpleNamespace(no_speech_prob=.1,avg_logprob=-.8,compression_ratio=1.,
            words=[word('Hallo',.99),word('Spieler',.4),word('hier',.9)])
        model=types.SimpleNamespace(transcribe=lambda *a,**k:([segment],None))
        module=types.SimpleNamespace(WhisperModel=lambda *a,**k:model)
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'faster_whisper':module}):
            ns={'OUT':Path(folder),'download':lambda x:x,'render':lambda *a:None}
            report={};configure(ns,report)
            words=ns['transcribe'](Path('source.mp4'))
            transcript=json.loads((Path(folder)/'transcript.json').read_text(encoding='utf-8'))
        self.assertEqual(len(words),3)
        self.assertEqual(transcript['editorial_accuracy'],'not_reviewed')
        self.assertTrue(transcript['requires_correction'])
        self.assertEqual(transcript['uncertain_word_indexes'],[1])
        self.assertEqual(len(transcript['uncertain_segments']),1)
        self.assertNotIn('media_review',transcript)

    def receipt(self):
        state,config,_,_=fixture()
        item=state['queue'][0]
        review=copy.deepcopy(item.pop('media_review'))
        item['status']='awaiting_review_tiktok14'
        return MemoryState(state),config,{'clip_id':item['clip_id'],'media_review':review}

    def test_review_approval_is_bound_to_current_candidate_and_does_not_post(self):
        store,config,receipt=self.receipt()
        self.assertEqual(cloud.apply_review(store,config,json.dumps(receipt),NOW),'review_approved')
        self.assertEqual(store.data['queue'][0]['status'],'ready_tiktok14')
        self.assertEqual(store.data['attempts'],[])

    def test_stale_or_wrong_hash_approval_never_changes_state(self):
        for kind in ('hash','clip','expired','missing_evidence'):
            store,config,receipt=self.receipt();before=store.load()
            if kind=='hash':receipt['media_review']['media_sha256']='f'*64
            if kind=='clip':receipt['clip_id']='another'
            if kind=='expired':receipt['media_review']['reviewed_at']='2026-10-01T12:00:00Z'
            if kind=='missing_evidence':receipt['media_review']['checks']['full_clip_payoff']['evidence']='ok'
            with self.subTest(kind=kind),self.assertRaises(ServiceError):
                cloud.apply_review(store,config,json.dumps(receipt),NOW)
            self.assertEqual(store.load(),before)

    def test_rejection_archives_candidate_and_unblocks_discovery(self):
        store,config,receipt=self.receipt()
        receipt['media_review'].update(decision='rejected',reason='Browser frame covers gameplay')
        self.assertEqual(cloud.apply_review(store,config,json.dumps(receipt),NOW),'review_rejected')
        self.assertEqual(store.data['queue'],[])
        self.assertEqual(store.data['rejected'][0]['rejection_reason'],'Browser frame covers gameplay')

    def test_review_never_claims_to_cancel_an_already_reserved_send(self):
        for decision in ('approved','rejected'):
            store,config,receipt=self.receipt()
            store.data['attempts']=[{'clip_id':receipt['clip_id'],'status':'reserved'}]
            before=store.load()
            receipt['media_review'].update(decision=decision,reason='Browser frame covers gameplay')
            with self.assertRaisesRegex(ServiceError,'review_send_already_pending'):
                cloud.apply_review(store,config,json.dumps(receipt),NOW)
            self.assertEqual(store.load(),before)

    def test_review_rejects_oversized_or_ambiguous_json(self):
        for value in ('x'*16001,'{"clip_id":"1","clip_id":"2"}', '[]'):
            store,config,_=self.receipt()
            with self.subTest(value=value[:40]),self.assertRaises(ServiceError):
                cloud.apply_review(store,config,value,NOW)

if __name__=='__main__':unittest.main()
