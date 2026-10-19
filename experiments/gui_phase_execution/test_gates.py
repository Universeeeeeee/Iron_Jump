import copy
import unittest
from context_gate import check_context
from decision import decide

class Context(unittest.TestCase):
    def fixture(self):return dict(session_id=1,priority_class=16384,qpa='windows',process=dict(success=True,version=1,control_mask=0,state_mask=0),thread=dict(success=True,version=1,control_mask=0,state_mask=0))
    def test_expected(self):self.assertTrue(check_context(self.fixture(),1))
    def test_session_zero(self):
        r=self.fixture();r['session_id']=0
        with self.assertRaises(ValueError):check_context(r)
    def test_priority_not_silently_corrected(self):
        r=self.fixture();r['priority_class']=32
        with self.assertRaises(ValueError):check_context(r)
    def test_session_changed(self):
        with self.assertRaises(ValueError):check_context(self.fixture(),2)
    def test_existing_policy(self):
        r=self.fixture();r['process']['control_mask']=1
        with self.assertRaises(ValueError):check_context(r)

class Decision(unittest.TestCase):
    def pair(self):
        a=dict(qualified=True,observed_queue_lower=1200,queue_upper=1250,max_latency_ms=1500,scheduled_max_ms=1501,input_lateness_ms=50)
        b=dict(qualified=True,observed_queue_lower=80,queue_upper=120,max_latency_ms=150,scheduled_max_ms=151,input_lateness_ms=50)
        return a,b
    def test_positive(self):self.assertTrue(decide([self.pair() for _ in range(4)])['advance'])
    def test_no_reproduction(self):
        pairs=[self.pair() for _ in range(4)]
        for a,b in pairs:a['observed_queue_lower']=0
        self.assertFalse(decide(pairs)['advance'])
    def test_late_input(self):
        p=[self.pair() for _ in range(4)];p[0][1]['input_lateness_ms']=151;self.assertFalse(decide(p)['advance'])
    def test_failed_window(self):
        p=[self.pair() for _ in range(4)];p[0][1]['qualified']=False;self.assertFalse(decide(p)['advance'])
    def test_residual_latency(self):
        p=[self.pair() for _ in range(4)];p[0][1]['scheduled_max_ms']=300;self.assertFalse(decide(p)['advance'])
    def test_residual_queue(self):
        p=[self.pair() for _ in range(4)];p[0][1]['queue_upper']=251;self.assertFalse(decide(p)['advance'])
    def test_incomplete(self):
        with self.assertRaises(ValueError):decide([self.pair()])
