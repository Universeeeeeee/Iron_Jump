import unittest
from review import delta
class Counters(unittest.TestCase):
    def test_distinct_hardware_values_preserved(self):
        self.assertEqual(delta([3,5,7],[10,25,8]),[7,20,1])
    def test_reset_not_silently_unwrapped(self):
        with self.assertRaises(AssertionError):delta([10,5,7],[9,25,8])
    def test_missing_counter_rejected(self):
        with self.assertRaises(AssertionError):delta([1,2],[3,4])
if __name__=='__main__':unittest.main()
