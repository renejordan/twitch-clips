"""Two free speech models compare the full source audio before subtitle rendering."""
import gc
import hashlib
import json
from pathlib import Path
import re
from difflib import SequenceMatcher
from tiktok14_autoreview import transcript_distance,tokens
from tiktok14_services import ServiceError,QualityRejected

SMALL_REV='536b0662742c02347bc0e980a01041f333bce120'
TURBO_REV='0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'

def validate_speech(primary,secondary,audio):
 p=primary['words'];s=secondary['words']
 if len(p)<3 or len(s)<3:raise QualityRejected('qa_speech_insufficient')
 first=' '.join(w['text'] for w in p);second=' '.join(w['text'] for w in s)
 distance=transcript_distance(first,second)
 # A small aggregate error can still change the meaning (e.g. a negation).
 # Only punctuation/case/contractions normalize away; no lexical substitution
 # or omitted word is automatically rendered as if independently confirmed.
 if distance!=0:raise QualityRejected('qa_transcripts_disagree')
 if primary['uncertain_segments']:raise QualityRejected('qa_primary_segment_uncertain')
 if sum(w['probability'] for w in p)/len(p)<.8:raise QualityRejected('qa_primary_confidence_low')
 # Confidence values are not calibrated accuracy probabilities. Confirm an
 # isolated uncertain word by exact cross-model text AND compatible timing.
 a=[tokens(w['text']) for w in p];b=[tokens(w['text']) for w in s]
 confirmed=set()
 for match in SequenceMatcher(None,[str(x) for x in a],[str(x) for x in b],autojunk=False).get_matching_blocks():
  for offset in range(match.size):
   first=p[match.a+offset];second=s[match.b+offset]
   aligned=('start' not in first or 'start' not in second or abs(first['start']-second['start'])<=.8)
   if aligned and first['probability']>=.15 and second['probability']>=.15:confirmed.add(match.a+offset)
 if any(w['probability']<.55 and i not in confirmed for i,w in enumerate(p)):
  raise QualityRejected('qa_uncertain_word_unconfirmed')
 if not .002<=audio['rms']<=.5 or audio['clipped_fraction']>=.01:raise QualityRejected('qa_audio_quality_failed')
 return distance

def transcribe_pair(path,out,model_dir):
 from faster_whisper import WhisperModel
 from faster_whisper.audio import decode_audio
 import numpy as np
 folder=Path(model_dir);out=Path(out)
 samples=decode_audio(str(path),sampling_rate=16000)
 if not len(samples):raise ServiceError('qa_audio_missing')
 audio={'rms':float(np.sqrt(np.mean(np.square(samples,dtype=np.float64)))),
  'clipped_fraction':float(np.mean(np.abs(samples)>=.999))}
 results=[]
 for name in ('turbo','small'):
  model=WhisperModel(str(folder/name),device='cpu',compute_type='int8',cpu_threads=4)
  segments,_=model.transcribe(samples,language='de',beam_size=5,
   temperature=(0.,.2,.4,.6,.8,1.),
   word_timestamps=True,condition_on_previous_text=False,vad_filter=True,hallucination_silence_threshold=1.)
  words=[];uncertain=[]
  for segment in segments:
   if segment.no_speech_prob>.6 or segment.avg_logprob<-.9 or segment.compression_ratio>2.4:
    uncertain.append({'start':float(segment.start),'end':float(segment.end),
     'no_speech_prob':float(segment.no_speech_prob),'avg_logprob':float(segment.avg_logprob)})
   for w in segment.words or []:
    if w.word.strip():words.append({'start':float(w.start),'end':float(w.end),'text':w.word.strip(),'probability':float(w.probability)})
  results.append({'model':name,'words':words,'uncertain_segments':uncertain})
  del model;gc.collect()
 primary,secondary=results
 comparison={'primary':primary,'secondary':secondary,'audio':audio,
  'normalized_token_distance':transcript_distance(' '.join(w['text'] for w in primary['words']),
   ' '.join(w['text'] for w in secondary['words']))}
 (out/'asr-comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 distance=validate_speech(primary,secondary,audio)
 result={'model':'whisper-large-v3-turbo','revision':TURBO_REV,'language':'de',
  'words':primary['words'],'secondary_model':'whisper-small','secondary_revision':SMALL_REV,
  'secondary_words':secondary['words'],'normalized_token_distance':distance,
  'editorial_accuracy':'automated_model_agreement_not_human_verified','audio':audio,
  'requires_correction':False}
 target=out/'transcript.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 return [(w['start'],w['end'],w['text']) for w in primary['words']],result
