import unittest
from state_review02 import spans

class SpanTests(unittest.TestCase):
    def test_clips_and_unions_nested_calls(self):
        rows=[dict(begin_ns=0,end_ns=8),dict(begin_ns=2,end_ns=4),dict(begin_ns=8,end_ns=15)]
        r=spans(rows,1,10)
        self.assertEqual(r['union_wall_ms'],9/1e6)
        self.assertEqual(r['overlap_calls'],3)
        self.assertEqual(r['fully_contained_calls'],1)
    def test_boundary_only_is_not_overlap(self):
        r=spans([dict(begin_ns=0,end_ns=1),dict(begin_ns=3,end_ns=4)],1,3)
        self.assertEqual(r['union_wall_ms'],0)
        self.assertIsNone(r['median_full_wall_ms'])
    def test_invalid_interval(self):
        with self.assertRaises(ValueError):spans([],2,1)
