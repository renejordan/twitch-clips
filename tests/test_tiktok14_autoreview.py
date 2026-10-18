import datetime as dt
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_autoreview import transcript_distance,visual_error,automated_receipt
from tiktok14_quality import review_error
from test_tiktok14_worker import fixture,NOW
class AutoReviewTests(unittest.TestCase):
 def test_transcript_comparison_ignores_punctuation_and_case_but_not_words(self):
  self.assertEqual(transcript_distance('Oh, mein Gott!','oh mein gott'),0)
  self.assertGreater(transcript_distance('Ich habe gewonnen','Ich habe verloren'),.2)
 def test_german_contractions_do_not_count_as_transcription_errors(self):
  self.assertEqual(transcript_distance("Ich schaff's nicht",'ich schaffs nicht'),0)
 def visual(self):
  return {'gameplay_visible':True,'browser_chrome':False,'nested_rebroadcast':False,
   'existing_captions':False,'complete_payoff':True,'standalone_understandable':True,
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
   'media_sha256':item['sha256'],'transcript_sha256':item['transcript_sha256'],
   'source_frame_hashes':['a'*64]*10,'final_timestamps':[i*25/9 for i in range(10)],'final_frame_hashes':['b'*64]*10,
   'reviewed_source_sha256':'c'*64,'caption_scan':{'method':'full_duration_2fps_ocr_aligned_to_speech','frames':50},
   'source_visual':self.visual(),'final_visual':{'legible_subtitles':True,'composition_usable':True,'browser_chrome':False,'nested_rebroadcast':False,'evidence':'Gameplay and captions remain visible in all sampled final frames.'},
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
if __name__=='__main__':unittest.main()
