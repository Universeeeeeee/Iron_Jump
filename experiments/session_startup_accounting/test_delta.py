import unittest
from delta import interval
class Delta(unittest.TestCase):
    def pair(self):
        def row(t,cpu):return dict(valid=True,capture_begin_ns=t,capture_end_ns=t+1,value=dict(pid=1,tid=2,begin_ns=t,end_ns=t+1,process=dict(creation_100ns=1,user_100ns=cpu*2,kernel_100ns=0,cycles=cpu*3),thread=dict(creation_100ns=2,user_100ns=cpu,kernel_100ns=0,cycles=cpu)))
        return row(1,10),row(100,20)
    def test_process_includes_workers_no_waiting_subtraction(self):
        r=interval(*self.pair());self.assertEqual(r['process']['cpu_ms'],.002);self.assertEqual(r['thread']['cpu_ms'],.001);self.assertNotIn('waiting_ms',r)
    def test_identity_and_regression_rejected(self):
        a,b=self.pair();b['value']['thread']['creation_100ns']=3
        with self.assertRaises(AssertionError):interval(a,b)
        a,b=self.pair();b['value']['process']['cycles']=0
        with self.assertRaises(AssertionError):interval(a,b)
