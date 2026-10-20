import json,unittest
from pathlib import Path
class CapacityTests(unittest.TestCase):
 def setUp(self):self.v=json.loads((Path(__file__).parent/'result01.json').read_text())
 def test_consumer_below_arrival_after_visual_isolation(self):
  p=self.v['cases']['cold01_process'];self.assertLess(p['effective_service_fps'],p['arrival_fps']);self.assertGreater(p['retained_peak_lower'],1000)
 def test_required_margin_is_material(self):
  p=self.v['cases']['cold01_process'];self.assertGreater(p['required_throughput_increase_for_250'],.15);self.assertGreater(self.v['minimum_gap_to_close']['process_cold_required_ms_reduction_per_frame'],.15)
 def test_no_false_function_or_fix_claim(self):
  self.assertFalse(self.v['formal_fix_verified']);self.assertFalse(self.v['field_fix_verified']);self.assertIn('exact responsible function',self.v['localization']['unknown'])
if __name__=='__main__':unittest.main()
