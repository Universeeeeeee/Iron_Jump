import unittest
from analyze import compare

class CandidateDecision(unittest.TestCase):
    def pair(self,consumer=8,whole=10):return (dict(consumer_wall_ms=10,whole_wall_ms_bounds=[10,10]),dict(consumer_wall_ms=consumer,whole_wall_ms_bounds=[whole,whole]))
    def test_positive(self):self.assertTrue(compare([self.pair()]*4)['practical_gate_pass'])
    def test_total_work_regression_rejects(self):self.assertFalse(compare([self.pair(whole=11)]*4)['practical_gate_pass'])
    def test_one_bad_pair_rejects(self):self.assertFalse(compare([self.pair()]*3+[self.pair(consumer=11)])['practical_gate_pass'])
    def test_small_gain_rejects(self):self.assertFalse(compare([self.pair(consumer=9.5)]*4)['practical_gate_pass'])
    def test_incomplete_rejects(self):
        with self.assertRaises(ValueError):compare([self.pair()]*3)
