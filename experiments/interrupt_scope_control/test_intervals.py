import unittest
from intervals import union,overlap
class Intervals(unittest.TestCase):
    def test_nested_interrupt_not_double_counted(self):
        self.assertEqual(union([(0,10),(2,4),(5,12)]),[(0,12)])
    def test_only_time_on_matching_cpu_running_window(self):
        self.assertEqual(overlap([(2,6),(4,8)],[(0,5),(7,10)]),4)
    def test_negative_interval_is_invalid(self):
        with self.assertRaises(AssertionError):union([(3,2)])
    def test_empty_is_not_invented_time(self):self.assertEqual(overlap([],[(0,10)]),0)
if __name__=='__main__':unittest.main()
