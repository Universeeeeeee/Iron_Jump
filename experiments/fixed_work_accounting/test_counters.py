import sys
import time
import unittest
from counters import snapshot,validate

class Boundaries(unittest.TestCase):
    def fixture(self):
        return dict(process_before=dict(pid=1,creation_100ns=1,begin_ns=0,end_ns=1,user_100ns=0,kernel_100ns=0,cycles=0),process_after=dict(pid=1,creation_100ns=1,begin_ns=20,end_ns=21,user_100ns=2,kernel_100ns=0,cycles=5),consumer=dict(begin_ns=2,end_ns=10,thread_cpu_ns=50),model=dict(begin_ns=3,end_ns=18,work_done_ns=19,thread_cpu_ns=50,close_begin_ns=23,close_end_ns=30),close_release_ns=22)
    def test_complete_bounds(self):self.assertTrue(validate(self.fixture())['accounting_pass'])
    def test_early_close_rejected(self):
        r=self.fixture();r['model']['close_begin_ns']=18;self.assertFalse(validate(r)['accounting_pass'])
    def test_unfinished_model_rejected(self):
        r=self.fixture();r['model']['end_ns']=22;self.assertFalse(validate(r)['accounting_pass'])
    def test_changed_process_identity_rejected(self):
        r=self.fixture();r['process_after']['creation_100ns']=2;self.assertFalse(validate(r)['accounting_pass'])
    def test_backward_cycles_rejected(self):
        r=self.fixture();r['process_after']['cycles']=-1;self.assertFalse(validate(r)['accounting_pass'])
    @unittest.skipUnless(sys.platform=='win32','Windows process APIs required')
    def test_actual_process_counters_advance(self):
        a=snapshot(time.perf_counter_ns);sum(i*i for i in range(200000));b=snapshot(time.perf_counter_ns)
        self.assertEqual(a['creation_100ns'],b['creation_100ns']);self.assertEqual(a['pid'],b['pid']);self.assertGreater(b['cycles'],a['cycles']);self.assertGreaterEqual(b['kernel_100ns']+b['user_100ns'],a['kernel_100ns']+a['user_100ns'])

if __name__=='__main__':unittest.main()
