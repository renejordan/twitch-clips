import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from tiktok14_quality import context_headline, social_caption, mobile_title_lines


class PresentationTests(unittest.TestCase):
    def test_caption_has_relevant_tags_without_source_label(self):
        caption=social_caption({'original_title':'0,0000083% Double Spawner 🤯',
            'streamer':'castcrafter','category':'Minecraft'})
        self.assertNotIn('Quelle',caption)
        self.assertIn('#minecraft',caption)
        self.assertIn('#castcrafter',caption)
        self.assertEqual(len([w for w in caption.split() if w.startswith('#')]),5)

    def test_title_keeps_german_text_and_removes_unsupported_emoji(self):
        self.assertEqual(context_headline('Überraschung: 0,0000083% 🤯','castcrafter',plain=True),
            'Überraschung: 0,0000083%')

    def test_title_wraps_long_words_inside_mobile_width_without_losing_text(self):
        class Font:
            def getlength(self,text):return len(text)*40
        text='W'*52
        lines=mobile_title_lines(text,Font())
        self.assertEqual(''.join(lines),text)
        self.assertLessEqual(len(lines),3)
        self.assertTrue(all(Font().getlength(line)<=760 for line in lines))

    def test_non_game_category_gets_german_gaming_tag(self):
        self.assertIn('#gamingde',social_caption({'original_title':'Ein guter Clip',
            'streamer':'papaplatte','category':'Unknown'}))

    def test_valid_truncated_title_does_not_request_endless_refresh(self):
        from tiktok14_cloud import title_refresh_needed
        headline=context_headline('Oh '+'W'*80,'castcrafter',plain=True)
        self.assertFalse(title_refresh_needed({'media_review':{'evidence':{'headline':headline}}}))
