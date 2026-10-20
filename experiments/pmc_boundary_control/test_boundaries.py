import unittest
from analyze import bound
class Boundaries(unittest.TestCase):
    def test_outer_bounds_retain_marker_overhead(self):
        row=dict(begin=dict(qpc_before=10),end=dict(qpc_after=20))
        spans=[dict(cpu=0,begin=9,end=21,values=[120,50,5])]
        self.assertEqual(bound(row,spans)['instructions'],120)
    def test_missing_boundary_is_not_zero_work(self):
        with self.assertRaises(AssertionError):bound(dict(begin=dict(qpc_before=10),end=dict(qpc_after=20)),[])
    def test_partial_coverage_rejected(self):
        with self.assertRaises(AssertionError):bound(dict(begin=dict(qpc_before=10),end=dict(qpc_after=20)),[dict(cpu=0,begin=11,end=19,values=[2,3,4])])
if __name__=='__main__':unittest.main()
