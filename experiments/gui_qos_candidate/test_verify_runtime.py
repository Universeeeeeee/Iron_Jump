import unittest
from verify_runtime import verify_runtime

class RuntimeGate(unittest.TestCase):
    def fixture(self):
        policy=dict(version=1,control_mask=1,state_mask=0)
        rows=[dict(role=role,ordinal=n,tid=tid,pid=1,session_id=1,priority_class=16384,begin_ns=0,end_ns=1,process=dict(policy,success=True),thread=dict(success=True),foreground_pid=1) for role,tid in [('consumer',2),('model',3),('gui',1)] for n in [1,100]]
        return dict(configuration=dict(variant='optout',after=policy),at_end=policy,original_method_unchanged=True,original_module_unchanged=True,context=dict(session_id=1),runtime_context=rows)
    def test_valid(self):self.assertTrue(verify_runtime(self.fixture(),'optout',1)['verified'])
    def test_priority_drift(self):
        r=self.fixture();r['runtime_context'][0]['priority_class']=32
        with self.assertRaises(ValueError):verify_runtime(r,'optout',1)
    def test_missing_role(self):
        r=self.fixture();r['runtime_context'].pop()
        with self.assertRaises(ValueError):verify_runtime(r,'optout',1)
    def test_policy_read_failed(self):
        r=self.fixture();r['runtime_context'][0]['thread']['success']=False
        with self.assertRaises(ValueError):verify_runtime(r,'optout',1)
    def test_slow_read(self):
        r=self.fixture();r['runtime_context'][0]['end_ns']=50000001
        with self.assertRaises(ValueError):verify_runtime(r,'optout',1)
