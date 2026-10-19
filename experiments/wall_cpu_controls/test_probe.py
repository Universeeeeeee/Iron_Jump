import copy
import unittest
from probe import delta

class Boundaries(unittest.TestCase):
    def pair(self):
        a=dict(pid=1,tid=2,before_ns=0,after_ns=10,thread_time_before_ns=0,thread_time_after_ns=10)
        for kind in ('thread','process'):a[kind]=dict(creation_100ns=3,exit_100ns=0,kernel_100ns=0,user_100ns=0,cycles=0)
        b=copy.deepcopy(a);b.update(before_ns=100,after_ns=110,thread_time_before_ns=20,thread_time_after_ns=30)
        for kind in ('thread','process'):b[kind].update(user_100ns=1,cycles=10)
        return a,b
    def test_bounds(self):self.assertEqual(delta(*self.pair())['wall_ms_bounds'],[90/1e6,110/1e6])
    def test_identity(self):
        a,b=self.pair();b['tid']=3
        with self.assertRaises(ValueError):delta(a,b)
    def test_lifetime(self):
        a,b=self.pair();b['process']['creation_100ns']=4
        with self.assertRaises(ValueError):delta(a,b)
    def test_regression(self):
        a,b=self.pair();b['thread']['cycles']=-1
        with self.assertRaises(ValueError):delta(a,b)
    def test_slow_read(self):
        a,b=self.pair();b['after_ns']=2000000
        with self.assertRaises(ValueError):delta(a,b)
    def test_overlapping_boundaries(self):
        a,b=self.pair();b['before_ns']=5
        with self.assertRaises(ValueError):delta(a,b)
