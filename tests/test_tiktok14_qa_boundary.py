"""Exercise failures at the process boundary; no actual model or network needed."""
import hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_media import automated_render
from tiktok14_services import QualityRejected,ProductionInterrupted

class QABoundaryTests(unittest.TestCase):
 def invoke(self,status,returncode,reason=None,wrong_hash=False):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source.mp4';source.write_bytes(b'source')
   def child(command,**kwargs):
    self.assertNotIn('GH_TOKEN',kwargs['env']);self.assertNotIn('BUFFER_API_KEY',kwargs['env'])
    out=Path(command[command.index('--output')+1])
    (out/'qa-result.json').write_text(json.dumps({'status':status,'reason':reason}))
    for name in ('tiktok.mp4','cover.jpg','transcript.json','source-frames.jpg','final-frames.jpg'):(out/name).write_bytes(b'fixture')
    (out/'qa-evidence.json').write_text(json.dumps({'source_sha256':'0'*64 if wrong_hash else hashlib.sha256(source.read_bytes()).hexdigest()}))
    return subprocess.CompletedProcess(command,returncode)
   clip={'id':'12345'}
   with patch.dict(os.environ,GH_TOKEN='secret',BUFFER_API_KEY='secret'),patch('tiktok14_media.subprocess.run',side_effect=child):
    return automated_render({'OUT':root},clip,source,root/'models')
 def test_rejected_content_has_a_separate_repeatable_reason(self):
  with self.assertRaisesRegex(QualityRejected,'qa_visual_browser_chrome'):self.invoke('rejected',2,'qa_visual_browser_chrome')
 def test_success_exit_without_passed_result_cannot_approve(self):
  with self.assertRaises(ProductionInterrupted):self.invoke('technical_failure',0)
 def test_wrong_source_hash_cannot_approve(self):
  with self.assertRaises(ProductionInterrupted):self.invoke('passed',0,wrong_hash=True)
 def test_nonzero_exit_cannot_approve_even_with_passed_json(self):
  with self.assertRaises(ProductionInterrupted):self.invoke('passed',1)
if __name__=='__main__':unittest.main()
