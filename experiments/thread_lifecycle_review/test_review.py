import unittest
from review import lifetimes

class LifecycleTests(unittest.TestCase):
    def test_true_lifetime(self):
        r=lifetimes([(1,1),(5,2)])[0];self.assertTrue(r['actual_creation'] and r['actual_exit'])
    def test_rundown_is_censored(self):
        r=lifetimes([(1,3),(5,4)])[0];self.assertFalse(r['actual_creation']);self.assertFalse(r['actual_exit'])
    def test_reuse_is_two_lifetimes(self):self.assertEqual(len(lifetimes([(1,1),(2,2),(3,1),(4,2)])),2)
    def test_unanchored_end(self):
        with self.assertRaises(ValueError):lifetimes([(1,2)])
    def test_duplicate_start(self):
        with self.assertRaises(ValueError):lifetimes([(1,1),(2,1)])
    def test_open_end_is_unknown(self):self.assertIsNone(lifetimes([(1,1)])[0]['end'])
