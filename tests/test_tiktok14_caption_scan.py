import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_caption_scan import caption_candidates,classify_captions
from unittest.mock import Mock,patch
import tempfile
import contextlib,types
from tiktok14_services import ServiceError,QualityRejected

@contextlib.contextmanager
def image_fixture(directory):
 (Path(directory)/'scan-004.jpg').write_bytes(b'synthetic frame')
 image=Mock();image.size=(960,540)
 image.crop.return_value.save.side_effect=lambda path:Path(path).write_bytes(b'synthetic region')
 opened=Mock();opened.__enter__=Mock(return_value=image);opened.__exit__=Mock(return_value=False)
 with patch.dict(sys.modules,{'PIL':types.SimpleNamespace(Image=types.SimpleNamespace(open=lambda _:opened))}):yield
class CaptionScanTests(unittest.TestCase):
 def test_excessive_text_states_reject_only_the_candidate_before_inference(self):
  from tiktok14_caption_scan import MAX_TEXT_STATES
  rows=[{'at':1.,'box':[.3,.8,.7,.86],'text':f'caption {i}','confidence':.99}
   for i in range(MAX_TEXT_STATES+1)]
  vision=Mock()
  with self.assertRaisesRegex(QualityRejected,'qa_caption_text_density'):
   classify_captions({'detections':rows},'.',vision)
  vision.request_json.assert_not_called()
 def test_later_dialogue_cannot_inherit_hud_role_at_the_same_position(self):
  with tempfile.TemporaryDirectory() as directory,image_fixture(directory):
   (Path(directory)/'scan-021.jpg').write_bytes(b'later frame')
   first={'at':1.5,'box':[.3,.8,.7,.86],'text':'VICTORY','confidence':.99}
   later=dict(first,at=10.,text='Ich bin ein Waschbaer',confidence=.95)
   vision=Mock();vision.request_json.return_value={'region_0':'game_hud_or_chat',
    'region_1':'dialogue_subtitles','evidence':'The first text is a game result; the later text is added dialogue.'}
   report=classify_captions({'detections':[first,later]},directory,vision)
   self.assertEqual(len(vision.request_json.call_args.args[1]),4)
   self.assertAlmostEqual(report['crop_bottom_from'],.775)
   self.assertEqual([r['kind'] for r in report['region_reviews']],['game_hud_or_chat','dialogue_subtitles'])
 def test_large_game_result_banner_is_semantically_kept_without_cropping_action(self):
  for text in ('VICTORY','You Died','Respawn'):
   with self.subTest(text=text),tempfile.TemporaryDirectory() as directory,image_fixture(directory):
    rows=[([[300,260],[660,260],[660,300],[300,300]],text,.95)]
    detections=caption_candidates(rows,960,540,1.5,[])
    self.assertEqual(len(detections),1)
    vision=Mock();vision.request_json.return_value={'region_0':'game_hud_or_chat','evidence':'Visible game result banner with the game menu beneath it.'}
    report=classify_captions({'detections':detections},directory,vision)
    self.assertIsNone(report['crop_bottom_from'])
    self.assertEqual(len(vision.request_json.call_args.args[1]),2)
 def test_unmatched_dialogue_is_removed_and_unknown_role_is_technical_hold(self):
  with tempfile.TemporaryDirectory() as directory,image_fixture(directory):
   rows=[([[250,470],[650,470],[650,500],[250,500]],'Ich bin ein Waschbaer',.95)]
   found=caption_candidates(rows,960,540,1.5,[])
   vision=Mock();vision.request_json.return_value={'region_0':'dialogue_subtitles','evidence':'Added dialogue text appears over the direct gameplay capture.'}
   result=classify_captions({'detections':found},directory,vision)
   self.assertGreater(result['crop_bottom_from'],.75)
   vision.request_json.return_value={'region_0':'unclear','evidence':'The visible context does not establish the role of this text.'}
   with self.assertRaisesRegex(ServiceError,'qa_caption_regions_uncertain'):
    classify_captions({'detections':found},directory,vision)
 def test_speech_aligned_text_is_found_while_small_hud_and_side_chat_are_ignored(self):
  words=[{'start':1.,'end':2.,'text':'Oh mein Gott'}]
  box=lambda x,y,w,h:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
  rows=[(box(250,430,400,30),'Oh mein Gott',.95),
   (box(400,320,80,10),'Respawn',.95),(box(0,430,100,30),'Oh mein Gott',.95),
   (box(250,490,400,10),'Oh mein Gott',.95)]
  got=caption_candidates(rows,960,540,1.5,words)
  self.assertEqual(len(got),1);self.assertEqual(got[0]['text'],'Oh mein Gott')
 def test_wrong_existing_caption_is_detected_without_speech_agreement(self):
  rows=[([[250,430],[650,430],[650,460],[250,460]],'Ich bin ein Waschbaer',.95)]
  got=caption_candidates(rows,960,540,1.5,[{'start':1.,'end':2.,'text':'Ein Creeper kommt hoch'}])
  self.assertEqual(got[0]['detection'],'prominent_unmatched_text')
if __name__=='__main__':unittest.main()
