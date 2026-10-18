import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SinglePipelineTests(unittest.TestCase):
    def test_retired_auto20_has_no_automatic_trigger_and_cannot_produce(self):
        workflow = (ROOT / '.github/workflows/tiktok.yml').read_text(encoding='utf-8')
        triggers = workflow.split('permissions:', 1)[0]
        self.assertNotIn('  schedule:', triggers)
        self.assertNotIn('  push:', triggers)
        self.assertIn('  workflow_dispatch:', triggers)
        self.assertIn('  auto20:\n    if: ${{ false }}', workflow)

if __name__ == '__main__':
    unittest.main()
