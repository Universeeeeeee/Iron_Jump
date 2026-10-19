import unittest
from delivery import verify_child

class Delivery(unittest.TestCase):
    def fixture(self):
        outer=[dict(begin_ns=i*3,end_ns=i*3+3) for i in range(220)]
        calls=[dict(ordinal=i,slot=i%2,timestamp_ms=1000+50*i,begin_ns=i*3+1,end_ns=i*3+2) for i in range(220)]
        a=dict(pid=2,creation_100ns=1,kernel_100ns=0,user_100ns=0,cycles=0,end_ns=0)
        b=dict(pid=2,creation_100ns=1,kernel_100ns=1,user_100ns=2,cycles=3,begin_ns=660)
        parent=dict(model=dict(ready_ns=0,calls=outer),consumer=dict(begin_ns=0,end_ns=300))
        child=dict(pid=2,tid=3,ready_ns=0,closed=True,errors=[],calls=calls,frame_sha256=['a','b'],process_before=a,process_after=b)
        return parent,child
    def test_actual_work_pass(self):self.assertTrue(verify_child(*self.fixture(),['a','b'],1)['actual_model_overlap'])
    def test_same_pid_rejected(self):
        p,c=self.fixture();c['pid']=1
        with self.assertRaises(ValueError):verify_child(p,c,['a','b'],1)
    def test_changed_pixels_rejected(self):
        p,c=self.fixture()
        with self.assertRaises(ValueError):verify_child(p,c,['wrong','b'],1)
    def test_missing_call_rejected(self):
        p,c=self.fixture();c['calls'].pop()
        with self.assertRaises(ValueError):verify_child(p,c,['a','b'],1)
    def test_outside_parent_bracket_rejected(self):
        p,c=self.fixture();c['calls'][0]['end_ns']=100
        with self.assertRaises(ValueError):verify_child(p,c,['a','b'],1)
