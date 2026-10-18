import datetime as dt,json,subprocess
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import tiktok14_cloud as cloud
from tiktok14_media import metadata_decision
from test_tiktok14_worker import NOW
class DiscoveryTests(unittest.TestCase):
 def test_smaller_clip_is_not_excluded_by_legacy_hundred_view_argument(self):
  ns=cloud.producer_namespace()
  info={'id':'123456','webpage_url':'https://clips.twitch.tv/ValidClipSlug',
   'channel':'Trymacs','creators':['Trymacs'],'extractor_key':'TwitchClips',
   'timestamp':NOW.timestamp()-3600,'duration':30,'view_count':12,'categories':['Minecraft'],'title':'Actual gameplay moment'}
  ns['run']=lambda *a,**k:subprocess.CompletedProcess([],0,json.dumps(info),'')
  self.assertEqual(ns['inspect_original']('trymacs',info['webpage_url'],NOW,100)['view_count'],12)
 def test_daily_and_weekly_lists_are_combined_and_deduplicated(self):
  ns=cloud.producer_namespace();urls=[]
  def run(command,**kw):
   url=command[-1];urls.append(url);label='Fresh' if '24hr' in url else 'Week'
   return subprocess.CompletedProcess([],0,json.dumps({'entries':[{'url':'https://clips.twitch.tv/'+label}]}),'')
  ns['run']=run
  rows=ns['channel_urls']('trymacs')
  self.assertEqual(len(rows),2);self.assertTrue(any('range=24hr' in u for u in urls));self.assertTrue(any('range=7d' in u for u in urls))
 def test_fresh_lower_view_clip_may_reach_actual_media_review(self):
  info={'channel':'Trymacs','creators':['Trymacs'],'extractor_key':'TwitchClips',
   'timestamp':NOW.timestamp()-3600,'duration':30,'view_count':150,'categories':['Minecraft'],'title':'Actual gameplay moment'}
  self.assertEqual(metadata_decision(info,'trymacs',NOW)[1],'qualified_metadata')
  self.assertEqual(metadata_decision(dict(info,view_count=99),'trymacs',NOW)[1],'views_below_100')
 def test_valid_older_clip_reaches_media_review_without_an_arbitrary_8000_view_gate(self):
  info={'channel':'Trymacs','creators':['Trymacs'],'extractor_key':'TwitchClips',
   'timestamp':NOW.timestamp()-60*3600,'duration':30,'view_count':700,'categories':['Fortnite'],'title':'Visible clutch moment'}
  self.assertEqual(metadata_decision(info,'trymacs',NOW)[1],'qualified_metadata')
  self.assertEqual(metadata_decision(dict(info,timestamp=NOW.timestamp()-73*3600),'trymacs',NOW)[1],'age_outside_72h')
if __name__=='__main__':unittest.main()
