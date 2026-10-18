"""Locate existing dialogue captions from actual frames and matching source speech."""
import json
from pathlib import Path
import re
import subprocess
from difflib import SequenceMatcher
from tiktok14_autoreview import tokens
from tiktok14_services import ServiceError
from tiktok14_vision import clean_environment


def caption_candidates(ocr,width,height,moment,words):
 nearby={token for word in words if abs((word['start']+word['end'])/2-moment)<=2 for token in tokens(word['text'])}
 found=[]
 for points,text,confidence in ocr or []:
  if confidence<.7:continue
  left=min(p[0] for p in points)/width;right=max(p[0] for p in points)/width
  top=min(p[1] for p in points)/height;bottom=max(p[1] for p in points)/height
  if not (.2<(left+right)/2<.8 and .58<top<.94 and .023<bottom-top<.12):continue
  recognized=tokens(text)
  if not recognized or len(recognized)>12:continue
  matches=sum(any(token==ref or (len(token)>=5 and len(ref)>=5 and
   SequenceMatcher(None,token,ref).ratio()>.8) for ref in nearby) for token in recognized)
  if matches/len(recognized)>=.6 and sum(len(t) for t in recognized)>=4:
   found.append({'at':moment,'box':[left,top,right,bottom],'text':text,'confidence':float(confidence)})
 return found

def scan_captions(source,out,words,ffmpeg='ffmpeg'):
 from rapidocr_onnxruntime import RapidOCR
 import cv2
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 result=subprocess.run([ffmpeg,'-y','-v','error','-i',str(source),'-vf','fps=2,scale=960:-2',
  '-frames:v','120',str(out/'scan-%03d.jpg')],env=clean_environment(),capture_output=True,timeout=90)
 if result.returncode:raise ServiceError('qa_caption_frames_failed')
 engine=RapidOCR(intra_op_num_threads=4,inter_op_num_threads=1)
 found=[]
 for index,path in enumerate(sorted(out.glob('scan-*.jpg'))):
  image=cv2.imread(str(path))
  if image is None:raise ServiceError('qa_caption_frame_unreadable')
  height,width=image.shape[:2];cut=int(height*.55)
  rows,_=engine(image[cut:])
  shifted=[([[float(x),float(y+cut)] for x,y in pts],text,float(conf)) for pts,text,conf in rows or []]
  found.extend(caption_candidates(shifted,width,height,index*.5,words))
 report={'method':'full_duration_2fps_ocr_aligned_to_speech','frames':index+1 if 'index' in locals() else 0,
  'detections':found,'crop_bottom_from':max(.55,min((d['box'][1] for d in found),default=1.)-.025) if found else None}
 (out/'caption-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 return report
