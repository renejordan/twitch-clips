import json
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_speech import validate_speech
from tiktok14_services import ServiceError
class SpeechTests(unittest.TestCase):
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
