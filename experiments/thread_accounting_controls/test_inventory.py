import copy
import unittest
from inventory import summarize

class Checks(unittest.TestCase):
    def pair(self):
        r=dict(pid=1,tid=2,creation_100ns=3,exit_100ns=0,kernel_100ns=0,user_100ns=0,cycles=0,before_ns=1,after_ns=2)
        a=dict(before_ns=0,after_ns=3,enumerated_tids=[2],rows=[r]);b=copy.deepcopy(a);b.update(before_ns=10,after_ns=13);b['rows'][0].update(before_ns=11,after_ns=12,cycles=5,user_100ns=10);return a,b
    def test_stable_does_not_prove_coverage(self):
        r=summarize(*self.pair());self.assertTrue(r['retained_threads_pass']);self.assertFalse(r['whole_process_lifetime_coverage_proven'])
    def test_exit(self):
        a,b=self.pair();b['rows'][0]['exit_100ns']=9;self.assertIn('retained_thread_exited',summarize(a,b)['reasons'])
    def test_new_thread(self):
        a,b=self.pair();b['enumerated_tids'].append(4);self.assertFalse(summarize(a,b)['retained_threads_pass'])
    def test_reuse(self):
        a,b=self.pair();b['rows'][0]['creation_100ns']=4;self.assertIn('identity_changed',summarize(a,b)['reasons'])
    def test_regression(self):
        a,b=self.pair();b['rows'][0]['cycles']=-1;self.assertIn('counter_regressed',summarize(a,b)['reasons'])
    def test_group_width(self):
        a,b=self.pair();b['after_ns']=20000000;self.assertIn('group_read_width',summarize(a,b)['reasons'])
