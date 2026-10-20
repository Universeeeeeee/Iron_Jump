from types import SimpleNamespace
import unittest
from context import Phases,check
class Context(unittest.TestCase):
    def reader(self,role,n):return dict(role=role,ordinal=n,begin_ns=200,end_ns=210)
    def test_consumer_once_per_logical_phase(self):
        rows=[];p=Phases(rows,[dict(sample=10,offset_ns=0,phase='dense'),dict(sample=30,offset_ns=0,phase='mixed')],reader=self.reader)
        p.observe('consumer',9);p.observe('consumer',12);p.observe('consumer',13);p.observe('consumer',30)
        self.assertEqual([r['ordinal'] for r in rows],[10,30]);self.assertEqual(rows[0]['completed_sample'],12)
    def test_diagnostics_never_skip_original(self):
        rows=[];p=Phases(rows,[dict(sample=10,offset_ns=0,phase='dense')],reader=lambda *a:(_ for _ in ()).throw(OSError('injected')))
        calls=[];f=p.wrap(lambda *a:calls.append(1) or 17,'consumer')
        self.assertEqual(f(None,[(None,SimpleNamespace(sample_index=10))]),17);self.assertEqual(calls,[1]);self.assertIn('error',rows[0])
    def test_model_needs_rebased_source_clock(self):
        rows=[];clock=SimpleNamespace(history=[1],anchor_ns=0);p=Phases(rows,[dict(sample=10,offset_ns=0,phase='dense')],clock=lambda:clock,reader=self.reader)
        p.observe('model');self.assertEqual(rows,[]);clock.history.append(2);p.observe('model');self.assertEqual(len(rows),1)
    def test_incomplete_roles_rejected(self):
        with self.assertRaises(AssertionError):check([],'original')
