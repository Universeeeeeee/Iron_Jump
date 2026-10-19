import unittest
from analyze import paired

class DirectionTests(unittest.TestCase):
    def test_consistent_large_change(self):self.assertTrue(paired([(10,5),(12,6),(8,4),(6,3)])['directional_threshold_met'])
    def test_one_regression_rejects(self):self.assertFalse(paired([(10,4),(10,4),(10,4),(10,11)])['directional_threshold_met'])
    def test_small_change_rejects(self):self.assertFalse(paired([(10,9)]*4)['directional_threshold_met'])
    def test_partial_pairs_rejected(self):
        with self.assertRaises(ValueError):paired([(10,5)]*3)
    def test_nonpositive_rejected(self):
        with self.assertRaises(ValueError):paired([(10,5)]*3+[(10,0)])
