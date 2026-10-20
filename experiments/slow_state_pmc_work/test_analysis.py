import unittest
from analyze import phase_bound,compare
class Analysis(unittest.TestCase):
    def test_edge_is_retained(self):
        a=dict(tid=1,creation=2,qpc=10,kernel=0,user=0,cycles=0);b=dict(a,qpc=20,user=1,cycles=5)
        r=phase_bound(a,b,[dict(begin=9,end=21,values=[120,50,5])],10)
        self.assertEqual(r['retired_instruction_outer'],120);self.assertEqual(r['outside_marker_running_ns'],200000000)
    def test_identity_and_missing_boundary_rejected(self):
        a=dict(tid=1,creation=2,qpc=10,kernel=0,user=0,cycles=0)
        with self.assertRaises(AssertionError):phase_bound(a,dict(a,tid=2,qpc=20),[],10)
        with self.assertRaises(AssertionError):phase_bound(a,dict(a,qpc=20),[],10)
    def test_no_fast_state_no_comparison(self):
        self.assertFalse(compare([{}],[],{})['available'])
    def test_all_pairs_must_meet_rules(self):
        rule=dict(comparable_instruction_fraction=.05,minimum_wall_ratio=1.3)
        slow=[dict(case='a',instructions=100,wall_ns=150),dict(case='b',instructions=120,wall_ns=150)]
        fast=[dict(case='c',instructions=100,wall_ns=100)]
        r=compare(slow,fast,rule);self.assertFalse(r['all_pairs_comparable_retired_work_and_slower']);self.assertEqual(len(r['all_cross_state_pairs']),2)
if __name__=='__main__':unittest.main()
