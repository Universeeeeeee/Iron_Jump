import unittest
from qos import configure

class Fake:
    def __init__(self):self.value=dict(version=1,control_mask=0,state_mask=0);self.calls=0;self.fail=False;self.ignore=False
    def read(self):return dict(self.value)
    def set(self,value):
        self.calls+=1
        if self.fail:raise OSError('Injected setter failure')
        if not self.ignore:self.value=dict(value)

class Controls(unittest.TestCase):
    def test_default_untouched(self):
        a=Fake();configure(a,'default');self.assertEqual(a.calls,0)
    def test_only_execution_bit_changes(self):
        a=Fake();a.value.update(control_mask=2,state_mask=2);v=configure(a,'optout');self.assertEqual(v['after'],dict(version=1,control_mask=3,state_mask=2))
    def test_setter_failure_aborts(self):
        a=Fake();a.fail=True
        with self.assertRaises(OSError):configure(a,'optout')
    def test_unconfirmed_setter_aborts(self):
        a=Fake();a.ignore=True
        with self.assertRaises(ValueError):configure(a,'optout')
    def test_unexpected_baseline_aborts(self):
        a=Fake();a.value['control_mask']=1
        with self.assertRaises(ValueError):configure(a,'optout')
    def test_unknown_variant_aborts(self):
        with self.assertRaises(ValueError):configure(Fake(),'on')
