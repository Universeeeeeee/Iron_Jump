import unittest
import verify_recovery02
from test_waiter import WaiterChecks


class RecoveryBoundaryChecks(unittest.TestCase):
    def fixture(self):
        r,s,p,m=WaiterChecks().fixture();r['complete']['host_ns']=300;return r,s,p,m
    def test_equal_post_stop_reads_are_valid(self):
        r,s,p,m=self.fixture();r['oracle'].append(list(r['oracle'][-1]));r['complete']['heartbeat']=100
        v=verify_recovery02.inspect(r,s,p,m,__import__('pathlib').Path(__file__).resolve().parents[2]);self.assertFalse(v['recovery_boundary_correction']['original_recovered']);self.assertTrue(v['deterministic_waiter_control_pass'])
    def test_no_progress_after_capture_rejected(self):
        r,*_=self.fixture();r['complete']['heartbeat']=40;self.assertFalse(verify_recovery02.recovered(r))
    def test_acquisition_not_completed_rejected(self):
        r,*_=self.fixture();r['complete']['acquired']=1;self.assertFalse(verify_recovery02.recovered(r))
    def test_complete_before_end_rejected(self):
        r,*_=self.fixture();r['complete']['host_ns']=200;self.assertFalse(verify_recovery02.recovered(r))
    def test_other_frozen_failure_still_fails(self):
        r,s,p,m=self.fixture();s['1'][1]['native'][1]['frames'].pop()
        v=verify_recovery02.inspect(r,s,p,m,__import__('pathlib').Path(__file__).resolve().parents[2]);self.assertFalse(v['deterministic_waiter_control_pass'])


if __name__=='__main__':unittest.main()
