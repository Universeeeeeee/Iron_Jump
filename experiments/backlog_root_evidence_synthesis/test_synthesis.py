import json,unittest
from pathlib import Path
class SynthesisTests(unittest.TestCase):
 def setUp(self):self.value=json.loads((Path(__file__).parent/'result01.json').read_text())
 def test_no_false_completion(self):
  self.assertFalse(self.value['root_function_identified']);self.assertFalse(self.value['formal_fix_verified']);self.assertFalse(self.value['field_fix_verified'])
 def test_old_pmc_and_fast_process_limits_remain(self):
  text=json.dumps(self.value);self.assertIn('83.5967',text);self.assertIn('rejected in fast state',text)
 def test_next_gate_targets_isolated_early_phase(self):
  self.assertIn('0.056ms/frame',self.value['next_minimal_validation']['decisions']['next_candidate'])
if __name__=='__main__':unittest.main()
