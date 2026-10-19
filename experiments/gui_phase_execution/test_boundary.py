import unittest
from pathlib import Path
from boundary import Boundaries

class BoundaryTests(unittest.TestCase):
    def fixture(self):
        calls=[];timer=iter(range(100))
        def reader(folder,label):calls.append(label);return dict(label=label)
        return Boundaries(Path('.'),reader,lambda:next(timer)),calls
    def test_order_and_returns(self):
        b,calls=self.fixture()
        def original(obj,value):calls.append('open');return value
        self.assertEqual(b.opened(original)(object(),42),42)
        self.assertEqual(calls,['before_open','open','after_open'])
        self.assertEqual([r['label'] for r in b.rows],['before_open','original_open','after_open'])
    def test_failure_does_not_fake_after_stage(self):
        b,calls=self.fixture()
        def original(obj):raise ValueError('open error')
        with self.assertRaises(ValueError):b.opened(original)(object())
        self.assertEqual(calls,['before_open']);self.assertFalse(b.rows[-1]['success'])
    def test_reopen_rejected(self):
        b,calls=self.fixture();f=b.opened(lambda obj:1);f(None)
        with self.assertRaises(RuntimeError):f(None)
    def test_close_failure_preserved(self):
        b,calls=self.fixture()
        def original(obj):raise RuntimeError('close error')
        with self.assertRaises(RuntimeError):b.closed(original)(None)
        self.assertEqual(calls,[]);self.assertFalse(b.rows[-1]['success'])
    def test_close_once(self):
        b,calls=self.fixture();f=b.closed(lambda obj:3);self.assertEqual(f(None),3)
        self.assertEqual(calls,['after_close'])
        with self.assertRaises(RuntimeError):f(None)
    def test_base_patch_preserves_outer_audit_and_subclass_lookup(self):
        b,calls=self.fixture()
        class Base:
            def open(self):calls.append('real_open');return 7
            def close(self):calls.append('real_close')
        class Preview(Base):pass
        b.install(Base);inside=Base.open
        def audit(obj):
            calls.append('audit_begin');value=inside(obj);calls.append('audit_end');return value
        Base.open=audit
        self.assertEqual(Preview().open(),7)
        self.assertEqual(calls,['audit_begin','before_open','real_open','after_open','audit_end'])
