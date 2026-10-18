import json
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_speech import validate_speech,subtitle_plan
from tiktok14_services import ServiceError
class SpeechTests(unittest.TestCase):
 def test_uncertain_speech_yields_no_rendered_words_but_cannot_rescue_bad_audio(self):
  primary=self.transcript();secondary=self.transcript();secondary['words'][2]['text']='nicht'
  mode,words,distance,reason=subtitle_plan(primary,secondary,{'rms':.05,'clipped_fraction':0})
  self.assertEqual((mode,words),('title_only',[]));self.assertGreater(distance,0)
  self.assertEqual(reason,'qa_transcripts_disagree')
  for audio in ({'rms':.0001,'clipped_fraction':0},{'rms':.05,'clipped_fraction':.1}):
   with self.assertRaisesRegex(ServiceError,'qa_audio_quality_failed'):subtitle_plan(primary,secondary,audio)
 def test_verified_words_keep_the_strict_agreement_gate(self):
  mode,words,distance,reason=subtitle_plan(self.transcript(),self.transcript(),{'rms':.05,'clipped_fraction':0})
  self.assertEqual(mode,'verified_words');self.assertEqual(distance,0);self.assertIsNone(reason)
  self.assertEqual(len(words),8)
 def transcript(self,low=False):
  return {'words':[{'text':text,'probability':(.4 if low and i==2 else .95)} for i,text in enumerate('Ich habe den Creeper direkt am Haus gesehen'.split())],'uncertain_segments':[]}
 def test_isolated_uncertain_word_can_be_confirmed_by_second_model(self):
  self.assertEqual(validate_speech(self.transcript(True),self.transcript(),{'rms':.05,'clipped_fraction':0}),0)
 def test_same_uncertain_word_from_two_uncertain_models_is_not_confirmation(self):
  primary=self.transcript(True);secondary=self.transcript(True)
  primary['words'][2]['probability']=.05
  secondary['words'][2]['probability']=.05
  with self.assertRaises(ServiceError):validate_speech(primary,secondary,{'rms':.05,'clipped_fraction':0})
 def test_agreement_does_not_confirm_a_word_at_a_different_audio_position(self):
  primary=self.transcript(True);secondary=self.transcript()
  primary['words'][2]['start']=1.;secondary['words'][2]['start']=10.
  with self.assertRaises(ServiceError):validate_speech(primary,secondary,{'rms':.05,'clipped_fraction':0})
 def test_different_transcript_or_clipped_audio_fails(self):
  secondary=self.transcript();secondary['words'][2]['text']='nicht';secondary['words'][3]['text']='morgen'
  with self.assertRaises(ServiceError):validate_speech(self.transcript(),secondary,{'rms':.05,'clipped_fraction':0})
  with self.assertRaises(ServiceError):validate_speech(self.transcript(),self.transcript(),{'rms':.05,'clipped_fraction':.1})
 def test_single_high_confidence_negation_disagreement_cannot_pass(self):
  primary=self.transcript();primary['words'][4]['text']='nicht'
  with self.assertRaisesRegex(ServiceError,'qa_transcripts_disagree'):
   validate_speech(primary,self.transcript(),{'rms':.05,'clipped_fraction':0})
if __name__=='__main__':unittest.main()
