import unittest
from analyze import compare

C=dict(minimum_geometric_consumer_reduction=.15,minimum_geometric_native_throughput_gain=.10,maximum_geometric_whole_work_regression=.05,minimum_slow_default_windows=3,slow_preparation_wall_ms_min=4300)
class Decisions(unittest.TestCase):
    def pair(self,cpu=8,native=2.4,whole=10,prep=5000):
        return (dict(consumer_wall_ms=10,native_billion_adds_per_second=2,whole_wall_ms=10,preparation_wall_ms=prep),dict(consumer_wall_ms=cpu,native_billion_adds_per_second=native,whole_wall_ms=whole))
    def test_joint_gain(self):self.assertTrue(compare([self.pair()]*4,C)['advance'])
    def test_native_no_gain(self):self.assertFalse(compare([self.pair(native=2)]*4,C)['advance'])
    def test_small_consumer_gain(self):self.assertFalse(compare([self.pair(cpu=9)]*4,C)['advance'])
    def test_one_adverse_pair(self):self.assertFalse(compare([self.pair()]*3+[self.pair(cpu=11)],C)['advance'])
    def test_total_work_regression(self):self.assertFalse(compare([self.pair(whole=11)]*4,C)['advance'])
    def test_fast_baselines(self):self.assertFalse(compare([self.pair(prep=3000)]*4,C)['advance'])
    def test_incomplete(self):
        with self.assertRaises(ValueError):compare([self.pair()]*3,C)
