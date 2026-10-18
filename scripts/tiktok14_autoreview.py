"""Local, evidence-based model review. No service credentials or paid API."""
import datetime as dt
import hashlib
import json
import math
import re

VISION_MODEL='qwen3-vl-4b-q4km'
PRIMARY='whisper-large-v3-turbo'
SECONDARY='whisper-small'
CHECKS=('subtitles_accuracy','frame_composition','full_clip_payoff','audio_intelligibility','gaming_context')
PRACTICAL_POLICY='ranked_practical_v1'
PRACTICAL_CHECKS=('clip_selection','frame_composition','caption_rendering','audio_track','gaming_context')

def digest_json(value):
 return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def tokens(text):return re.findall(r'[^\W_]+',text.casefold().replace("'",'').replace('’',''),flags=re.UNICODE)

def transcript_distance(first,second):
 a,b=tokens(first),tokens(second)
 if not a or not b:return 1.
 row=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  nxt=[i]
  for j,y in enumerate(b,1):nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
  row=nxt
 return row[-1]/max(len(a),len(b))

def finite(value):return type(value) in (int,float) and math.isfinite(value)

def coverage_error(times,duration,hashes,fast=False):
 if (not isinstance(times,list) or len(times)<(3 if fast else 8) or not all(finite(x) for x in times) or
     times!=sorted(set(times)) or not 0<=times[0]<=.6 or not duration-.6<=times[-1]<=duration or
     max(b-a for a,b in zip(times,times[1:]))>(duration/2+.6 if fast else 8)):return True
 return (not isinstance(hashes,list) or len(hashes)!=len(times) or
         any(not re.fullmatch('[a-f0-9]{64}',str(value)) for value in hashes))

def visual_error(data,duration,practical=False,preserve_overlays=False):
 if not isinstance(data,dict):return 'visual_response_invalid'
 required=('gameplay_visible','safe_for_general_audience') if practical else ('gameplay_visible','complete_payoff','standalone_understandable','safe_for_general_audience','sustained_watchability')
 for key in required:
  if data.get(key) is not True:return 'visual_'+key
 for key in (('browser_chrome','nested_rebroadcast') if preserve_overlays else ('browser_chrome','nested_rebroadcast','existing_captions')):
  if data.get(key) is not False:return 'visual_'+key
 if data.get('frame_problem')!='none':return 'visual_composition_problem'
 if practical:return None
 for key in ('hook_score','payoff_score'):
  if type(data.get(key)) is not int or not 3<=data[key]<=5:return 'visual_'+key
 for key in ('setup','payoff'):
  if not isinstance(data.get(key),str) or not 20<=len(data[key])<=1500:return 'visual_narrative_missing'
 if not finite(data.get('payoff_timestamp')) or not 0<=data['payoff_timestamp']<=duration:return 'visual_payoff_time_invalid'
 return None

def automated_receipt(item,evidence,current):
 practical=evidence.get('quality_policy')==PRACTICAL_POLICY
 fast=practical and evidence.get('review_method')=='sampled_frames_and_full_decode'
 title_only=evidence.get('caption_mode')=='title_only'
 checks={
  'subtitles_accuracy':('No word subtitles rendered; uncertain speech is retained only as diagnostic evidence.' if title_only else f"Two full audio transcriptions compared; normalized token distance {evidence['transcript_distance']:.4f}. No human accuracy assertion."),
  'frame_composition':evidence['final_visual']['evidence'],
  'full_clip_payoff':evidence['source_visual']['setup']+' '+evidence['source_visual']['payoff'],
  'audio_intelligibility':f"Decoded full audio; RMS {evidence['audio_rms']:.4f}, clipping fraction {evidence['clipped_fraction']:.5f}. No human listening claim.",
  'gaming_context':evidence['source_visual']['payoff']}
 if practical:
  checks={'clip_selection':'Ranked recent Twitch clip from the permitted gaming sources; no minimum narrative score required.',
   'frame_composition':checks['frame_composition'],'caption_rendering':checks['subtitles_accuracy'],
   'audio_track':checks['audio_intelligibility'],
   'gaming_context':'Actual sampled gameplay and source metadata checked.'}
  if fast:checks['caption_rendering']='No generated word subtitles. Original source overlays are preserved without claiming their accuracy.'
 return {'version':3 if practical else 2,'decision':'approved','method':'automated_local_models',
  'reviewer':'local-model-review-v2','reviewed_at':current.isoformat(),
  'media_sha256':item['sha256'],'transcript_sha256':item['transcript_sha256'],
  'source_sha256':item['source_sha256'],'evidence_sha256':digest_json(evidence),
  'evidence':evidence,'checks':{key:{'result':'pass','evidence':checks[key]} for key in (PRACTICAL_CHECKS if practical else CHECKS)}}

def automated_review_error(item,review,current):
 try:
  reviewed=dt.datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
  if reviewed.tzinfo is None or not 0<=(current-reviewed).total_seconds()<=72*3600:return 'review_timestamp_invalid'
  if review.get('method')!='automated_local_models' or review.get('decision')!='approved':return 'automatic_review_method_invalid'
  if 'watched_full_video' in review:return 'automatic_review_human_claim_forbidden'
  for field,reference in [('media_sha256','sha256'),('transcript_sha256','transcript_sha256'),('source_sha256','source_sha256')]:
   if not re.fullmatch('[a-f0-9]{64}',str(item.get(reference,''))) or review.get(field)!=item[reference]:return 'review_not_bound_to_media'
  e=review['evidence']
  practical=review.get('version')==3
  if practical != (e.get('quality_policy')==PRACTICAL_POLICY):return 'automatic_quality_policy_invalid'
  fast=practical and e.get('review_method')=='sampled_frames_and_full_decode'
  if not isinstance(e,dict) or review.get('evidence_sha256')!=digest_json(e):return 'automatic_evidence_hash_mismatch'
  if e.get('source_sha256')!=item['source_sha256'] or e.get('decoded_full_video') is not True:return 'automatic_source_evidence_missing'
  if e.get('media_sha256')!=item['sha256'] or e.get('transcript_sha256')!=item['transcript_sha256']:return 'automatic_output_evidence_mismatch'
  if e.get('vision_model')!=VISION_MODEL:return 'automatic_models_unverified'
  if fast:
   if e.get('asr_used') is not False or e.get('primary_model') is not None or e.get('secondary_model') is not None:return 'automatic_models_unverified'
  elif e.get('primary_model')!=PRIMARY or e.get('secondary_model')!=SECONDARY:return 'automatic_models_unverified'
  duration=e['duration'];times=e['timestamps']
  if not finite(duration) or not 15<=duration<=60:return 'automatic_duration_invalid'
  if coverage_error(times,duration,e.get('source_frame_hashes'),fast):return 'automatic_temporal_coverage_missing'
  if coverage_error(e.get('final_timestamps'),duration,e.get('final_frame_hashes'),fast):return 'automatic_final_coverage_missing'
  if not re.fullmatch('[a-f0-9]{64}',str(e.get('reviewed_source_sha256',''))):return 'automatic_source_evidence_missing'
  scan=e.get('caption_scan',{})
  if fast:
   if scan.get('method')!='original_overlays_preserved_no_generated_word_subtitles':return 'automatic_caption_scan_missing'
  elif (scan.get('method')!='full_duration_2fps_ocr_and_speech_alignment' or
      type(scan.get('frames')) is not int or scan['frames']<int(duration*2)-1):return 'automatic_caption_scan_missing'
  from tiktok14_caption_scan import text_groups,MAX_TEXT_STATES
  groups=text_groups(scan.get('detections',[]) if fast else scan['detections'])
  regions=scan.get('region_reviews',[]) if fast else scan['region_reviews']
  classification=scan.get('classifications',{}) if fast else scan['classifications']
  if not isinstance(regions,list) or len(regions)!=len(groups) or len(groups)>MAX_TEXT_STATES:return 'automatic_caption_semantics_missing'
  for index,region in enumerate(regions):
   key=f'region_{index}'
   if (region.get('region')!=key or region.get('kind') not in ('game_hud_or_chat','dialogue_subtitles') or
       classification.get(key)!=region['kind'] or any(not re.fullmatch('[a-f0-9]{64}',str(region.get(field,'')))
        for field in ('source_frame_sha256','crop_sha256'))):return 'automatic_caption_semantics_missing'
  if visual_error(e['source_visual'],duration,practical=practical,preserve_overlays=fast):return 'automatic_visual_check_failed'
  mode=e.get('caption_mode');word_count=e.get('rendered_word_count')
  if mode not in ('verified_words','title_only') or type(word_count) is not int:return 'automatic_caption_mode_invalid'
  if e.get('headline')!=f"Gaming-Moment mit {item.get('streamer')}":return 'automatic_title_invalid'
  f=e['final_visual']
  text_ok=(word_count>=3 and f.get('legible_subtitles') is True if mode=='verified_words' else
   word_count==0 and (fast or f.get('legible_subtitles') is False) and f.get('legible_title') is True and f.get('caption_quality') in (('readable_title_only','readable_single') if fast else ('readable_title_only',)))
  if fast and (mode!='title_only' or word_count!=0):return 'automatic_caption_mode_invalid'
  if (f.get('composition_usable') is not True or not text_ok or (not practical and f.get('event_retained') is not True) or
      f.get('browser_chrome') is not False or f.get('nested_rebroadcast') is not False or
      not isinstance(f.get('evidence'),str) or len(f['evidence'])<20):return 'automatic_final_composition_failed'
  distance=e['transcript_distance']
  if fast:
   if distance is not None:return 'automatic_transcripts_disagree'
  elif not finite(distance) or not 0<=distance<=1 or (mode=='verified_words' and distance!=0):return 'automatic_transcripts_disagree'
  rms=e['audio_rms'];clipped=e['clipped_fraction']
  if not finite(rms) or not .002<=rms<=.5 or not finite(clipped) or not 0<=clipped<.01:return 'automatic_audio_check_failed'
  for key in (PRACTICAL_CHECKS if practical else CHECKS):
   check=review['checks'][key]
   if check.get('result')!='pass' or not isinstance(check.get('evidence'),str) or len(check['evidence'])<12:return 'editorial_check_missing'
  if item.get('rights_status')!='user_declared_source_list':return 'source_rights_declaration_missing'
 except (ValueError,KeyError,TypeError,AttributeError,OverflowError):return 'automatic_review_invalid'
 return None
