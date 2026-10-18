import unittest
import verify


class PerturbationChecks(unittest.TestCase):
    def fixture(self):
        x=dict(case_pass=True,wall_ns=100,thread_cpu_ns=90,cycles=200,blocks=[dict(raw_first=1,wall_ns=100)])
        return x,dict(x),dict(relative_limit=.15)
    def test_equal_pass_is_offline_only(self):
        v=verify.pair_result(*self.fixture());self.assertTrue(v['offline_contact_chain_pair_pass']);self.assertFalse(v['actual_load_disturbance_pass'])
    def test_wall_limit_fails(self):
        a,b,p=self.fixture();b['wall_ns']=116;self.assertFalse(verify.pair_result(a,b,p)['offline_contact_chain_pair_pass'])
    def test_cycles_limit_fails(self):
        a,b,p=self.fixture();b['cycles']=232;self.assertFalse(verify.pair_result(a,b,p)['offline_contact_chain_pair_pass'])
    def test_failed_case_cannot_pass(self):
        a,b,p=self.fixture();b['case_pass']=False;self.assertFalse(verify.pair_result(a,b,p)['offline_contact_chain_pair_pass'])
    def test_block_slowdown_cannot_hide_in_total(self):
        a,b,p=self.fixture();b['blocks']=[dict(raw_first=1,wall_ns=116)];self.assertFalse(verify.pair_result(a,b,p)['offline_contact_chain_pair_pass'])
    def test_large_speedup_also_outside_fixed_limit(self):
        a,b,p=self.fixture();b['wall_ns']=84;self.assertFalse(verify.pair_result(a,b,p)['offline_contact_chain_pair_pass'])
    def test_missing_samples_rejected(self):self.assertFalse(verify.protocol([],10,20,40))
    def test_error_row_not_sample(self):self.assertFalse(verify.protocol([dict(kind='error')],10,20,1))


if __name__=='__main__':unittest.main()


class StreamChecks(unittest.TestCase):
    def fixture(self):
        return [dict(kind='init',schema=4,error=None,pid=10,qpc_end=1,synthetic_probe_enabled=False,activity_flags_valid=False),dict(kind='sample',ordinal=0,pid=10,qpc_begin=2,suspended_qpc=3,resume_returned_qpc=4,qpc_end=5,resolve_begin_qpc=6,resolve_end_qpc=7,oracle_reads=[None]*4,activity_flags_valid=False,traces=[dict(pid=10,owns_gil=True)],native=[dict(tid=20,context_ip=100,frames=[dict(address=100)],stopped_by='StackWalk64 ended; closure unverified')]),dict(kind='complete',pid=10,samples_written=1,qpc=8)]
    def test_disabled_probes_and_valid_stream(self):self.assertTrue(verify.protocol(self.fixture(),10,20,1))
    def test_unexpected_synthetic_probes_rejected(self):
        r=self.fixture();r[1]['oracle_reads'][0]={};self.assertFalse(verify.protocol(r,10,20,1))
    def test_wrong_requested_thread_rejected(self):self.assertFalse(verify.protocol(self.fixture(),10,99,1))
    def test_frame_cap_rejected(self):
        r=self.fixture();r[1]['native'][0]['stopped_by']='frame cap; incomplete';self.assertFalse(verify.protocol(r,10,20,1))
