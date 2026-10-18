"""Keep the live journal small without forgetting any completed source identity.

The branch's Git history retains previous full records. Seven days in the live
file exceed both the 72-hour source lifetime and the 24-hour publishing budget.
"""
import datetime as dt
import re
from tiktok14_publish import parse_timestamp
from tiktok14_services import ServiceError

def compact(state,current):
 used=state.get('used_ids',[])
 if not isinstance(used,list) or any(not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9_-]{4,100}',x) for x in used):
  raise ServiceError('invalid_permanent_dedup_history')
 used=set(used);changed=False;cutoff=current-dt.timedelta(days=7)
 for collection,counter in [('attempts','archived_verified_count'),('rejected','archived_rejected_count'),('rejected_sends','archived_rejected_send_count')]:
  kept=[];removed=0
  for row in state.get(collection,[]):
   identity=str(row.get('clip_id',''))
   removable=collection!='attempts' or row.get('status')=='verified_public'
   try:
    moment=max(parse_timestamp(row[key]) for key in ('reserved_at','sent_at','created_at') if row.get(key))
   except (ValueError,TypeError):removable=False;moment=current
   if removable and moment<cutoff and re.fullmatch('[A-Za-z0-9_-]{4,100}',identity):
    used.add(identity);removed+=1
   else:kept.append(row)
  if removed:
   state[collection]=kept;state[counter]=state.get(counter,0)+removed;changed=True
 if changed:state['used_ids']=sorted(used)
 return changed
