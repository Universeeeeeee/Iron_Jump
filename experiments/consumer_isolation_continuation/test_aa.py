import unittest
from analyze02 import aa_variance
class AA(unittest.TestCase):
    def test_variability_estimate_never_passes_old_observer_gate(self):
        v=aa_variance([dict(scheduled_max_ms=x) for x in (100,101,99,100)])
        self.assertGreater(v['log_sample_sd'],0);self.assertTrue(v['old_3pct_1pct_gate_still_failed'])
    def test_missing_and_nonpositive_cases_rejected(self):
        with self.assertRaises(ValueError):aa_variance([dict(scheduled_max_ms=1)])
        with self.assertRaises(ValueError):aa_variance([dict(scheduled_max_ms=x) for x in (1,1,0,1)])
