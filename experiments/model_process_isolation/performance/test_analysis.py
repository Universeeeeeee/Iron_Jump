import unittest
from analyze import compare

class Decision(unittest.TestCase):
    def pair(self,consumer=7,whole=10):return dict(consumer_wall_ms=10,whole_wall_ms=10),dict(consumer_wall_ms=consumer,whole_wall_ms=whole)
    def test_pass(self):self.assertTrue(compare([self.pair()]*4)['advance'])
    def test_small_gain(self):self.assertFalse(compare([self.pair(consumer=9)]*4)['advance'])
    def test_adverse_pair(self):self.assertFalse(compare([self.pair()]*3+[self.pair(consumer=11)])['advance'])
    def test_whole_work_regression(self):self.assertFalse(compare([self.pair(whole=11)]*4)['advance'])
    def test_incomplete(self):
        with self.assertRaises(ValueError):compare([self.pair()]*3)
