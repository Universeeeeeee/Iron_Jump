import copy
import unittest
from verify import check

class ScheduleTests(unittest.TestCase):
    def fixture(self,variant='concurrent'):
        plan=dict(model_calls=2,frame_ids=[1],raw_first=10,raw_after_last=15,progress_frames=[2,5])
        begin=1 if variant=='concurrent' else 10
        r=dict(variant=variant,complete=True,errors=[],full_original_chain_exact=True,worker_alive=False,consumer=dict(tid=1,begin_ns=0,end_ns=10,thread_cpu_ns=8,frames=5),model=dict(tid=2,ready_ns=-1,begin_ns=begin,end_ns=begin+12,close_begin_ns=30,closed=True,errors=[],calls=[dict(ordinal=i,frame_id=1,logical_ms=1000+50*i,begin_ns=begin+5*i,end_ns=begin+5*i+4) for i in range(2)]),model_result_sha256=['a','b'],process_accounting=dict(accounting_pass=True),consumer_progress=[dict(frames=2,raw_last=11,host_ns=4,thread_cpu_ns=3),dict(frames=5,raw_last=14,host_ns=9,thread_cpu_ns=7)])
        return plan,r
    def test_both_schedules(self):
        for variant in ('concurrent','serial'):self.assertTrue(check(*self.fixture(variant))['pass_all'])
    def test_serial_overlap_rejected(self):
        p,r=self.fixture();r['variant']='serial';self.assertFalse(check(p,r)['pass_all'])
    def test_concurrent_without_overlap_rejected(self):
        p,r=self.fixture('serial');r['variant']='concurrent';self.assertFalse(check(p,r)['pass_all'])
    def test_missing_call_rejected(self):
        p,r=self.fixture();r['model']['calls'].pop();self.assertFalse(check(p,r)['pass_all'])
    def test_progress_missing_rejected(self):
        p,r=self.fixture();r['consumer_progress'].pop();self.assertFalse(check(p,r)['pass_all'])
    def test_model_not_ready_rejected(self):
        p,r=self.fixture();r['model']['ready_ns']=5;self.assertFalse(check(p,r)['pass_all'])
    def test_cpu_regression_rejected(self):
        p,r=self.fixture();r['consumer_progress'][1]['thread_cpu_ns']=1;self.assertFalse(check(p,r)['pass_all'])
