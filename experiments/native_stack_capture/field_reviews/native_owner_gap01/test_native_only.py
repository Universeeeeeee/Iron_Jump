import copy
from pathlib import Path
import unittest
import verify

verify.ROOT=Path(__file__).resolve().parents[4]


class NativeOnlyOracle(unittest.TestCase):
    def fixture(self):
        anchor=dict(frequency=10**9,qpc_before=0,qpc_after=0,perf_before_ns=0,perf_after_ns=0)
        counter=dict(pid=10,tid=22,creation_100ns=3,active=True,start=anchor,end=anchor)
        record=dict(anchors=[anchor],before=[counter],after=[copy.deepcopy(counter)],ready=dict(pid=10,tids=dict(native=22)),oracle=[[0,1,2,1,22,7,2],[120,121,2,1,22,7,2],[302,303,4,0,0,8,4]],external_begin_ns=90,external_end_ns=130,complete=dict(completed=True,heartbeat=8,host_ns=300),errors=[],target_returncode=0,observer_returncode=0,target_still_running=False,observer_still_running=False)
        rows=[dict(kind='init',schema=1,error=None,pid=10,qpc_frequency=10**9,qpc_end=80),dict(kind='sample',ordinal=0,pid=10,qpc_begin=100,qpc_end=110,traces=[dict(pid=10,os_thread_id=22,owns_gil=True,frames=[])]),dict(kind='complete',pid=10,samples_written=1,qpc=120)]
        return record,rows,dict(count=1,eligible_floor=1,clock_uncertainty_ns_max=1000,phase_margin_ns=10)

    def check(self,r,s,p):return verify.inspect(r,s,p)['native_only_counterexample_pass']

    def test_control_passes_but_field_attribution_stays_false(self):
        r,s,p=self.fixture();result=verify.inspect(r,s,p)
        self.assertTrue(result['native_only_counterexample_pass']);self.assertTrue(result['checks']['original_field_protocol_still_rejects'])
        self.assertFalse(result['field_attribution_ready']);self.assertFalse(result['actual_load_disturbance_pass'])

    def test_wrong_owner_native_id_rejected(self):
        r,s,p=self.fixture();s[1]['traces'][0]['os_thread_id']=23;self.assertFalse(self.check(r,s,p))

    def test_nonempty_python_frames_not_native_only(self):
        r,s,p=self.fixture();s[1]['traces'][0]['frames']=[dict(name='f',filename='f.py',line=1)];self.assertFalse(self.check(r,s,p))

    def test_heartbeat_contradiction_rejected(self):
        r,s,p=self.fixture();r['oracle'][1][5]=8;self.assertFalse(self.check(r,s,p))

    def test_oracle_thread_change_rejected(self):
        r,s,p=self.fixture();r['oracle'][1][4]=23;self.assertFalse(self.check(r,s,p))

    def test_lifecycle_change_rejected(self):
        r,s,p=self.fixture();r['after'][0]['creation_100ns']=4;self.assertFalse(self.check(r,s,p))

    def test_wrong_completion_pid_rejected(self):
        r,s,p=self.fixture();s[-1]['pid']=11;self.assertFalse(self.check(r,s,p))

    def test_no_recovery_rejected(self):
        r,s,p=self.fixture();r['complete']['heartbeat']=7;self.assertFalse(self.check(r,s,p))

    def test_fixture_margin_violation_rejected(self):
        r,s,p=self.fixture();p['phase_margin_ns']=120;self.assertFalse(self.check(r,s,p))


if __name__=='__main__':unittest.main()
