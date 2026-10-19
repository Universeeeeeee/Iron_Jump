import copy
import unittest
from verify import compare

class Bundle(unittest.TestCase):
    def fixture(self):
        plan=dict(model_calls=2,frame_ids=[7,8],raw_first=1,raw_after_last=3)
        value=dict(complete=True,errors=[],full_original_chain_exact=True,worker_alive=False,report_sha256='report',frame_evidence=[7,8],model_result_sha256=['x','y'],consumer=dict(tid=1,frames=2,begin_ns=10,end_ns=20),
                   model=dict(tid=2,closed=True,errors=[],begin_ns=11,end_ns=18,close_begin_ns=21,close_end_ns=30,calls=[dict(ordinal=i,frame_id=7+i,logical_ms=1000+50*i,begin_ns=11+i*3,end_ns=13+i*3) for i in range(2)]))
        return plan,value,copy.deepcopy(value)
    def test_matching_bundle_never_certifies_overhead(self):
        p,a,b=self.fixture();r=compare(p,a,b);self.assertTrue(r['fixed_bundle_identity_pass']);self.assertFalse(r['actual_load_disturbance_pass'])
    def test_same_count_different_model_content_rejected(self):
        p,a,b=self.fixture();b['model_result_sha256'][0]='different';self.assertFalse(compare(p,a,b)['fixed_bundle_identity_pass'])
    def test_wrong_frame_order_rejected(self):
        p,a,b=self.fixture();b['model']['calls'][0]['frame_id']=8;self.assertFalse(compare(p,a,b)['fixed_bundle_identity_pass'])
    def test_close_overlap_retained_separately(self):
        p,a,b=self.fixture();b['model']['close_begin_ns']=18;self.assertFalse(compare(p,a,b)['model_close_outside_consumer'])
    def test_missing_concurrency_rejected(self):
        p,a,b=self.fixture();b['consumer']['end_ns']=11;self.assertFalse(compare(p,a,b)['fixed_bundle_identity_pass'])
    def test_unconfirmed_worker_rejected(self):
        p,a,b=self.fixture();b['worker_alive']=True;self.assertFalse(compare(p,a,b)['fixed_bundle_identity_pass'])

if __name__=='__main__':unittest.main()
