import unittest
from analyze02 import decide

class Decision(unittest.TestCase):
    def test_increase(self):self.assertTrue(decide([1.2,1.3])['same_direction_large_transition'])
    def test_decrease(self):self.assertTrue(decide([.7,.8])['same_direction_large_transition'])
    def test_small(self):self.assertFalse(decide([1.01,1.02])['same_direction_large_transition'])
    def test_discordant(self):self.assertFalse(decide([1.3,.7])['same_direction_large_transition'])
    def test_missing(self):
        with self.assertRaises(ValueError):decide([1.3])
