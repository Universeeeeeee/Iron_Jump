import json,unittest
from pathlib import Path
class SynthesisTests(unittest.TestCase):
 def setUp(self):self.value=json.loads((Path(__file__).parent/'result01.json').read_text())
 def test_no_false_completion(self):
  self.assertFalse(self.value['root_function_identified']);self.assertFalse(self.value['formal_fix_verified']);self.assertFalse(self.value['field_fix_verified'])
 def test_old_pmc_and_fast_process_limits_remain(self):
  text=json.dumps(self.value);self.assertIn('83.5967',text);self.assertIn('rejected in fast state',text)
 def test_next_gate_is_production_then_field(self):
  self.assertIn('live USB frames delivered in order',self.value['next_minimal_validation']['requirements'][0])
if __name__=='__main__':unittest.main()
