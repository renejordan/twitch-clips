import datetime as dt
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_autoreview import transcript_distance,visual_error,automated_receipt
from tiktok14_quality import review_error
from test_tiktok14_worker import fixture,NOW
class AutoReviewTests(unittest.TestCase):
 def test_context_title_is_bound_to_original_metadata(self):
  from tiktok14_quality import context_headline
  item=fixture()[0]['queue'][0];item['source_sha256']='d'*64
  item['original_title']='Minecraft: der Sprung endet in Lava'
  evidence=self.evidence(item)
  evidence['headline']=context_headline(item['original_title'],item['streamer'])
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertIsNone(review_error(item,NOW))
  item['original_title']='Andere Szene ohne dieses Ereignis'
  self.assertEqual(review_error(item,NOW),'automatic_title_invalid')

 def test_legacy_receipt_cannot_silently_omit_ocr_region_evidence(self):
  item=fixture()[0]['queue'][0];item['source_sha256']='d'*64
  evidence=self.evidence(item)
  for key in ('detections','region_reviews','classifications'):evidence['caption_scan'].pop(key)
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertIsNotNone(review_error(item,NOW))
 def test_missing_audio_stream_rejects_candidate_before_loading_speech_models(self):
  import tempfile,types
  from unittest.mock import Mock,patch
  from tiktok14_qa_pipeline import source_review
  from tiktok14_services import QualityRejected
  container=Mock();container.streams.audio=[]
  opened=Mock();opened.__enter__=Mock(return_value=container);opened.__exit__=Mock(return_value=False)
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'silent.mp4';source.write_bytes(b'local stream fixture')
   with patch.dict(sys.modules,{'av':types.SimpleNamespace(open=lambda _:opened)}):
    with self.assertRaisesRegex(QualityRejected,'qa_audio_missing'):
     source_review({'OUT':root,'probe':lambda _:15}, {'channel_login':'trymacs'},source,root)
 def test_practical_fast_review_uses_real_samples_and_audio_without_claiming_asr_or_ocr(self):
  from tiktok14_publish import eligible
  item=fixture()[0]['queue'][0];item.update(source_sha256='d'*64,editing_status='rendered_9x16_title_only',transcript_subtitles=False)
  evidence=self.evidence(item);evidence.update(quality_policy='ranked_practical_v1',
   review_method='sampled_frames_and_full_decode',asr_used=False,primary_model=None,secondary_model=None,
   caption_mode='title_only',rendered_word_count=0,transcript_distance=None,
   timestamps=[0,12.5,24.85],source_frame_hashes=['a'*64]*3,
   final_timestamps=[0,12.5,24.85],final_frame_hashes=['b'*64]*3,
   caption_scan={'method':'original_overlays_preserved_no_generated_word_subtitles'})
  evidence['source_visual']['existing_captions']=True
  evidence['final_visual'].update(legible_title=True,legible_subtitles=False,caption_quality='readable_title_only')
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertTrue(eligible(item,NOW))
  self.assertNotIn('Two full audio transcriptions',str(item['media_review']))
  evidence['rendered_word_count']=1;item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertFalse(eligible(item,NOW))
 def test_practical_selection_accepts_ranked_gameplay_without_perfect_payoff(self):
  from tiktok14_publish import eligible
  item=fixture()[0]['queue'][0];item['source_sha256']='d'*64
  evidence=self.evidence(item);evidence['quality_policy']='ranked_practical_v1'
  item.update(editing_status='rendered_9x16_title_only',transcript_subtitles=False)
  evidence.update(caption_mode='title_only',rendered_word_count=0,transcript_distance=.4)
  evidence['final_visual'].update(legible_subtitles=False,legible_title=True,caption_quality='readable_title_only')
  evidence['source_visual'].update(complete_payoff=False,standalone_understandable=False,
   sustained_watchability=False,hook_score=1,payoff_score=1)
  evidence['final_visual']['event_retained']=False
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertEqual(item['media_review']['version'],3)
  self.assertNotIn('full_clip_payoff',item['media_review']['checks'])
  self.assertIsNone(review_error(item,NOW))
  self.assertTrue(eligible(item,NOW))
  for field,value in [('browser_chrome',True),('gameplay_visible',False),('safe_for_general_audience',False)]:
   original=evidence['source_visual'][field];evidence['source_visual'][field]=value
   item['media_review']=automated_receipt(item,evidence,NOW)
   self.assertIsNotNone(review_error(item,NOW));evidence['source_visual'][field]=original
 def test_title_only_allows_uncertain_words_but_requires_visible_event_and_no_rendered_dialogue(self):
  from tiktok14_publish import eligible
  item=fixture()[0]['queue'][0];item.update(source_sha256='d'*64,editing_status='rendered_9x16_title_only',transcript_subtitles=False)
  evidence=self.evidence(item);evidence.update(caption_mode='title_only',rendered_word_count=0,
   headline='Gaming-Moment mit rewinside',transcript_distance=.4)
  evidence['final_visual'].update(legible_subtitles=False,legible_title=True,caption_quality='readable_title_only')
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertIsNone(review_error(item,NOW));self.assertTrue(eligible(item,NOW))
  self.assertIn('No word subtitles',item['media_review']['checks']['subtitles_accuracy']['evidence'])
  evidence['rendered_word_count']=1;item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertIsNotNone(review_error(item,NOW))
  evidence['rendered_word_count']=0;evidence['source_visual']['complete_payoff']=False
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertIsNotNone(review_error(item,NOW))
 def test_transcript_comparison_ignores_punctuation_and_case_but_not_words(self):
  self.assertEqual(transcript_distance('Oh, mein Gott!','oh mein gott'),0)
  self.assertGreater(transcript_distance('Ich habe gewonnen','Ich habe verloren'),.2)
 def test_german_contractions_do_not_count_as_transcription_errors(self):
  self.assertEqual(transcript_distance("Ich schaff's nicht",'ich schaffs nicht'),0)
 def visual(self):
  return {'gameplay_visible':True,'browser_chrome':False,'nested_rebroadcast':False,
   'existing_captions':False,'complete_payoff':True,'standalone_understandable':True,'sustained_watchability':True,
   'hook_score':4,'payoff_score':4,'setup':'Player approaches the building before throwing an item.',
   'payoff':'The thrown item explodes and breaks the blocks.', 'payoff_timestamp':18,
   'safe_for_general_audience':True,'frame_problem':'none'}
 def test_missing_or_ambiguous_visual_evidence_never_passes(self):
  for key,value in [('browser_chrome',True),('nested_rebroadcast',True),('gameplay_visible',False),
   ('complete_payoff',False),('hook_score',2),('payoff_score',True),('setup','ok'),('payoff_timestamp',float('nan'))]:
   row=self.visual();row[key]=value
   self.assertIsNotNone(visual_error(row,25))
  self.assertIsNone(visual_error(self.visual(),25))
 def evidence(self,item):
  return {'source_sha256':item['source_sha256'],'duration':25.,'timestamps':[i*25/9 for i in range(10)],
   'caption_mode':'verified_words','rendered_word_count':5,'headline':'Gaming-Moment mit rewinside',
   'media_sha256':item['sha256'],'transcript_sha256':item['transcript_sha256'],
   'source_frame_hashes':['a'*64]*10,'final_timestamps':[i*25/9 for i in range(10)],'final_frame_hashes':['b'*64]*10,
   'reviewed_source_sha256':'c'*64,'caption_scan':{'method':'full_duration_2fps_ocr_and_speech_alignment','frames':50,'detections':[],'region_reviews':[],'classifications':{}},
   'source_visual':self.visual(),'final_visual':{'event_retained':True,'legible_subtitles':True,'composition_usable':True,'browser_chrome':False,'nested_rebroadcast':False,'evidence':'Gameplay and captions remain visible in all sampled final frames.'},
   'transcript_distance':0.,'primary_model':'whisper-large-v3-turbo','secondary_model':'whisper-small',
   'vision_model':'qwen3-vl-4b-q4km','decoded_full_video':True,'audio_rms':.05,'clipped_fraction':0.001}
 def test_automatic_review_never_invents_human_watch_claim(self):
  item=fixture()[0]['queue'][0];item['source_sha256']='d'*64
  evidence=self.evidence(item)
  receipt=automated_receipt(item,evidence,NOW)
  self.assertNotIn('watched_full_video',receipt)
  item['media_review']=receipt
  self.assertIsNone(review_error(item,NOW))
  item['source_sha256']='e'*64
  self.assertIsNotNone(review_error(item,NOW))
 def test_cropping_the_actual_event_blocks_final_approval(self):
  item=fixture()[0]['queue'][0];item['source_sha256']='d'*64
  evidence=self.evidence(item);evidence['final_visual']['event_retained']=False
  item['media_review']=automated_receipt(item,evidence,NOW)
  self.assertEqual(review_error(item,NOW),'automatic_final_composition_failed')
 def test_malformed_model_output_is_a_technical_failure(self):
  from tiktok14_vision import validate_response
  from tiktok14_services import ServiceError
  for evidence in ('','x'*241,False):
   with self.subTest(evidence=evidence),self.assertRaises(ServiceError):
    validate_response({'evidence':evidence,'event_retained':True,'capture_layout':'direct_game_capture_with_facecam',
     'composition_quality':'usable','caption_quality':'readable_single'},True,[0,10,20])
if __name__=='__main__':unittest.main()
