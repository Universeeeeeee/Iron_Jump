import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('fixed_pair_statistics',Path(__file__).parent/'pilot_stats.py');stats=importlib.util.module_from_spec(spec);spec.loader.exec_module(stats)

class Pilot(unittest.TestCase):
    def values(self,n):return dict(wall_ns=n,cpu_ns=n,cycles=n)
    def test_fixed_pair_count(self):
        with self.assertRaises(AssertionError):stats.describe([(self.values(100),self.values(100))])
    def test_outlier_never_dropped(self):
        r=stats.describe([(self.values(100),self.values(x)) for x in (100,100,100,140)]);self.assertEqual(len(r['endpoints']['cpu_ns']['all_raw_relative_changes']),4);self.assertFalse(r['endpoints']['cpu_ns']['raw_abs_15pct_checks'][-1]);self.assertFalse(r['actual_load_disturbance_pass'])
    def test_zero_retained_without_epsilon(self):
        r=stats.describe([(self.values(0),self.values(100))]*4);self.assertFalse(r['endpoints']['cycles']['available']);self.assertIsNone(r['planning'])

if __name__=='__main__':unittest.main()
