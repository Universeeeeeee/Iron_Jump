import ast
from pathlib import Path
import unittest
class BatchTests(unittest.TestCase):
 def test_only_frozen_batch_size_is_40(self):
  import json
  p=json.loads((Path(__file__).parent/'plan02.json').read_text());self.assertEqual(p['batch_size'],40)
 def test_actor_keeps_four_ms_deadline_and_zero_pending_interval(self):
  text=(Path(__file__).parent/'actor_context.py').read_text();self.assertIn("time.perf_counter()+.004",text);self.assertIn("interval=0 if pending else 5",text)
if __name__=='__main__':unittest.main()
