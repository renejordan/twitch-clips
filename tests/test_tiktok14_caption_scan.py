import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_caption_scan import caption_candidates
class CaptionScanTests(unittest.TestCase):
 def test_only_lower_center_text_matching_the_real_speech_is_a_caption(self):
  words=[{'start':1.,'end':2.,'text':'Oh mein Gott'}]
  box=lambda x,y,w,h:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]
  rows=[(box(250,430,400,30),'Oh mein Gott',.95),
   (box(250,320,400,30),'Respawn',.95),(box(0,430,100,30),'Oh mein Gott',.95),
   (box(250,490,400,10),'Oh mein Gott',.95)]
  got=caption_candidates(rows,960,540,1.5,words)
  self.assertEqual(len(got),1);self.assertEqual(got[0]['text'],'Oh mein Gott')
if __name__=='__main__':unittest.main()
