import copy
import unittest
from verify import inspect

class Verification(unittest.TestCase):
    def fixture(self):
        return dict(calls=[dict(frame_id=1,media_sample_s=1.,logical_ms=1000,jpeg_sha256='j',pixels_sha256='p',shape=[1,1,3],decoded_ns=1,begin_ns=2,end_ns=3,has_pose=True,result_content_sha256='r')],errors=[],close_confirmed=True,complete_calls=True)
    def test_equal_control_not_overhead_qualification(self):
        x=self.fixture();r=inspect(dict(frame_ids=[1]),x,x);self.assertTrue(r['controlled_model_identity_pass']);self.assertFalse(r['actual_load_disturbance_pass'])
    def test_changed_result_with_same_count_rejected(self):
        a=self.fixture();b=copy.deepcopy(a);b['calls'][0]['result_content_sha256']='wrong';self.assertFalse(inspect(dict(frame_ids=[1]),a,b)['controlled_model_identity_pass'])
    def test_wrong_frame_rejected(self):
        a=self.fixture();b=copy.deepcopy(a);b['calls'][0]['frame_id']=2;self.assertFalse(inspect(dict(frame_ids=[1]),a,b)['controlled_model_identity_pass'])
    def test_unconfirmed_close_rejected(self):
        a=self.fixture();b=copy.deepcopy(a);b['close_confirmed']=False;self.assertFalse(inspect(dict(frame_ids=[1]),a,b)['controlled_model_identity_pass'])

if __name__=='__main__':unittest.main()
