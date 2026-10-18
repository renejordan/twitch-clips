"""Actual source and rendered media review; sampled vision plus full dual-ASR audio."""
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

from tiktok14_autoreview import PRIMARY,SECONDARY,VISION_MODEL,visual_error
from tiktok14_services import ServiceError,QualityRejected
from tiktok14_speech import transcribe_pair
from tiktok14_caption_scan import scan_captions,classify_captions
from tiktok14_vision import Vision,frame_samples,SOURCE_PROMPT,FINAL_PROMPT,sha


def source_review(namespace,clip,source,model_dir):
 out=namespace['OUT'];duration=namespace['probe'](source)
 if not 15<=duration<=60:raise QualityRejected('qa_duration_invalid')
 source_hash=sha(source)
 words,speech=transcribe_pair(source,out,model_dir)
 namespace['_qa_transcript']=(source_hash,words,speech)
 caption_report=scan_captions(source,out/'qa-captions',speech['words'])
 if caption_report['frames']<int(duration*2)-1:raise ServiceError('qa_caption_coverage_failed')
 with Vision(model_dir) as vision:
  if vision.model_id!=VISION_MODEL:raise ServiceError('qa_required_model_missing')
  caption_report=classify_captions(caption_report,out/'qa-captions',vision)
  clean_source=source
  bottom=caption_report['crop_bottom_from']
  if bottom is not None:
   if not .75<=bottom<1:raise QualityRejected('qa_captions_overlap_action_area')
   clean_source=out/'clean-source.mp4'
   namespace['run'](['ffmpeg','-y','-v','error','-i',str(source),'-vf',f'crop=iw:trunc(ih*{bottom:.6f}/2)*2:0',
    '-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-c:a','copy',str(clean_source)],timeout=180)
  namespace['_qa_clean_source']=clean_source
  frames,times=frame_samples(clean_source,out/'qa-source',duration)
  visual=vision.ask(SOURCE_PROMPT,frames,times,' '.join(w[2] for w in words))
 (out/'source-visual.json').write_text(json.dumps(visual,ensure_ascii=False,indent=2),encoding='utf-8')
 error=visual_error(visual,duration)
 if error:raise QualityRejected('qa_'+error)
 return {'source_sha256':source_hash,'duration':duration,'timestamps':times,
  'caption_mode':speech['caption_mode'],'rendered_word_count':len(words),
  'headline':f"Gaming-Moment mit {clip['channel_login']}",
  'source_visual':visual,'source_frame_hashes':[sha(path) for path in frames],
  'primary_model':PRIMARY,'secondary_model':SECONDARY,'vision_model':VISION_MODEL,
  'transcript_distance':speech['normalized_token_distance'],'audio_rms':speech['audio']['rms'],
  'clipped_fraction':speech['audio']['clipped_fraction'],'frames':frames,
  'caption_scan':caption_report,'reviewed_source_sha256':sha(clean_source)}

def stable_face_box(frames):
 """Find a stable corner face, never infer identity or blindly crop the center."""
 import cv2
 detectors=[(cv2.CascadeClassifier(cv2.data.haarcascades+name),profile) for name,profile in
  [('haarcascade_frontalface_default.xml',False),('haarcascade_frontalface_alt2.xml',False),('haarcascade_profileface.xml',True)]]
 detections=[]
 for index,path in enumerate(frames):
  image=cv2.imread(str(path))
  if image is None:raise ServiceError('qa_crop_frame_unavailable')
  image=cv2.resize(image,None,fx=2,fy=2);height,width=image.shape[:2]
  gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
  for detector,profile in detectors:
   for flip in ([False,True] if profile else [False]):
    found=detector.detectMultiScale(cv2.flip(gray,1) if flip else gray,scaleFactor=1.08,minNeighbors=3,minSize=(35,35))
    for x,y,w,h in found:
     if flip:x=width-x-w
     if (x+w/2)/width<.25 or (x+w/2)/width>.75:
      detections.append((index,(x/width,y/height,w/width,h/height),not profile))
 # A profile-only cluster may be a microphone or game HUD. Require at least
 # one independent frontal detection and stable recurrence across the clip.
 groups=[]
 for _,anchor,frontal in detections:
  if not frontal:continue
  cx=anchor[0]+anchor[2]/2;cy=anchor[1]+anchor[3]/2
  matched={}
  for index,box,_ in detections:
   if abs(box[0]+box[2]/2-cx)<.045 and abs(box[1]+box[3]/2-cy)<.06:matched[index]=box
  if len(matched)>=max(3,math.ceil(len(frames)*.5)):groups.append(list(matched.values()))
 if not groups:return None
 boxes=max(groups,key=len)
 centers=[(x+w/2,y+h/2) for x,y,w,h in boxes]
 cx=statistics.median(c[0] for c in centers);cy=statistics.median(c[1] for c in centers)
 if any(abs(x-cx)>.08 or abs(y-cy)>.1 for x,y in centers):return None
 h=min(1,statistics.median(b[3] for b in boxes)*2.2)
 w=min(1,max(statistics.median(b[2] for b in boxes)*2.5,h*(1080/500)*height/width))
 left=max(0,min(1-w,cx-w/2));top=max(0,min(1-h,cy-h/2))
 return left,top,w,h

def filter_path(path):return str(Path(path).resolve()).replace('\\','/').replace(':','\\:').replace("'", "\\'")

def portrait_render(namespace,clip,source,box):
 import av,os,textwrap
 out=namespace['OUT'];source_hash,words,speech=namespace['_qa_transcript']
 with av.open(str(source)) as container:
  stream=container.streams.video[0];width,height=stream.width,stream.height
 duration=namespace['probe'](source)
 x=y=0;w=width;h=height
 if box and width>height:
  x,y,w,h=[int(value*scale)//2*2 for value,scale in zip(box,(width,height,width,height))]
  if min(w,h)<40:box=None
 else:box=None
 namespace['write_subs'](words,0,duration,out/'subs.ass')
 (out/'headline.txt').write_text('\n'.join(textwrap.wrap(f"Gaming-Moment mit {clip['channel_login']}",26)[:2]),encoding='utf-8')
 font='C:/Windows/Fonts/arialbd.ttf' if os.name=='nt' else '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
 font=filter_path(font);headline=filter_path(out/'headline.txt');subs=filter_path(out/'subs.ass')
 filters=(f'[0:v]split=3[b][g][f];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];'
  f'[g]crop={height}:{height}:(iw-ow)/2:0,scale=1080:1080[game];'
  f'[f]crop={w}:{h}:{x}:{y},scale=1080:500:force_original_aspect_ratio=increase,crop=1080:500[face];'
  f'[bg][game]overlay=0:700[a];[a][face]overlay=0:50,'
  f"drawtext=fontfile='{font}':textfile='{headline}':fontsize=48:fontcolor=white:borderw=3:bordercolor=black:box=1:boxcolor=black@0.65:x=(w-text_w)/2:y=575,"
  f"ass=filename='{subs}',format=yuv420p[v]")
 if not box:
  side=min(width,height)
  gameplay=(f'crop={side}:{side}:(iw-ow)/2:(ih-oh)/2,scale=1080:1080' if width>height else 'scale=1080:1350:force_original_aspect_ratio=decrease')
  filters=('[0:v]split=2[b][g];[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg];'
   f'[g]{gameplay},setsar=1[game];[bg][game]overlay=(W-w)/2:(H-h)/2,'
   f"drawtext=fontfile='{font}':textfile='{headline}':fontsize=48:fontcolor=white:borderw=3:bordercolor=black:box=1:boxcolor=black@0.65:x=(w-text_w)/2:y=240,"
   f"ass=filename='{subs}',format=yuv420p[v]")
 movie=out/'tiktok.mp4';cover=out/'cover.jpg'
 namespace['run'](['ffmpeg','-y','-v','error','-i',str(source),'-filter_complex',filters,'-map','[v]','-map','0:a:0?',
  '-c:v','libx264','-preset','veryfast','-threads','2','-crf','23','-r','30','-c:a','aac','-b:a','160k','-movflags','+faststart',str(movie)],timeout=360)
 namespace['run'](['ffmpeg','-y','-v','error','-ss','1','-i',str(movie),'-frames:v','1',str(cover)],timeout=30)
 if namespace['probe'](movie,size=True)!='1080x1920':raise ServiceError('qa_portrait_format_failed')
 return movie,cover,bool(words)

def final_review(namespace,clip,movie,report,model_dir):
 namespace['run'](['ffmpeg','-v','error','-i',str(movie),'-f','null','-'],timeout=120)
 frames,times=frame_samples(movie,namespace['OUT']/'qa-final',report['duration'],count=10,hook_detail=False,
  extra_times=[report['source_visual']['payoff_timestamp']])
 context=json.dumps({'source_event_hypothesis':report['source_visual']['setup']+' '+report['source_visual']['payoff'],
  'caption_mode':report['caption_mode'],'expected_title':report['headline']})
 with Vision(model_dir) as vision:final=vision.ask(FINAL_PROMPT,frames,times,context)
 text_ok=(final.get('legible_subtitles') is True if report['caption_mode']=='verified_words' else final.get('caption_quality')=='readable_title_only')
 if (final.get('composition_usable') is not True or not text_ok or
  final.get('browser_chrome') is not False or final.get('nested_rebroadcast') is not False or final.get('event_retained') is not True):
  raise QualityRejected('qa_final_composition_failed')
 evidence={key:value for key,value in report.items() if key!='frames'}
 evidence.update(final_visual=final,final_timestamps=times,final_frame_hashes=[sha(path) for path in frames],
  decoded_full_video=True,media_sha256=sha(movie),transcript_sha256=sha(namespace['OUT']/'transcript.json'))
 clip['_qa_evidence']=evidence
 target=namespace['OUT']/'qa-evidence.json'
 target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 return evidence

def main():
 import argparse,sys
 parser=argparse.ArgumentParser(description=__doc__)
 for name in ('source','clip','output','models'):parser.add_argument('--'+name,required=True)
 args=parser.parse_args()
 out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
 result=out/'qa-result.json'
 try:
  from tiktok14_cloud import producer_namespace
  ns=producer_namespace();ns['OUT']=out
  clip=json.loads(Path(args.clip).read_text(encoding='utf-8'))
  report=source_review(ns,clip,Path(args.source).resolve(),args.models)
  movie,cover,_=portrait_render(ns,clip,ns['_qa_clean_source'],stable_face_box(report['frames']))
  final_review(ns,clip,movie,report,args.models)
  for path,name in ((ns['_qa_clean_source'],'source-frames.jpg'),(movie,'final-frames.jpg')):
   ns['run'](['ffmpeg','-y','-v','error','-i',str(path),'-vf','fps=1/5,scale=270:-2,tile=3x4','-frames:v','1',str(out/name)],timeout=60)
  result.write_text(json.dumps({'status':'passed'}),encoding='utf-8');return 0
 except QualityRejected as error:
  result.write_text(json.dumps({'status':'rejected','reason':str(error)}),encoding='utf-8');return 2
 except ServiceError as error:
  import re
  reason=str(error) if re.fullmatch('[a-z_]+',str(error)) else 'qa_operation_failed'
  result.write_text(json.dumps({'status':'technical_failure','reason':reason}),encoding='utf-8');return 1
 except Exception:
  result.write_text(json.dumps({'status':'technical_failure','reason':'qa_operation_failed'}),encoding='utf-8');return 1

if __name__=='__main__':raise SystemExit(main())
