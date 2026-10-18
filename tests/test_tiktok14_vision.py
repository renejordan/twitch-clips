import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_vision import scene_candidates
class VisionSamplingTests(unittest.TestCase):
 def test_brief_late_scene_change_is_not_lost_between_uniform_samples(self):
  log=''
  for time,score in [(1,.2),(7.41,.9),(7.45,.85),(19.8,.8),(24.5,.4),(28,.3),(91,.99)]:
   log+=f'[metadata] frame:1 pts:100 pts_time:{time}\n[metadata] lavfi.scene_score={score}\n'
  moments=scene_candidates(log,30)
  self.assertEqual(len(moments),4)
  self.assertIn(7.41,moments);self.assertIn(19.8,moments)
  self.assertNotIn(7.45,moments);self.assertNotIn(91,moments)
if __name__=='__main__':unittest.main()
