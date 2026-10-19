import ast
import hashlib
import inspect
from pathlib import Path
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from candidate import runtime_mask_equal,transformed,prepare

class Equality(unittest.TestCase):
    def test_every_single_bit_difference(self):
        base=np.zeros(768,dtype=bool)
        self.assertTrue(runtime_mask_equal(base,base.copy()))
        for index in range(768):
            other=base.copy();other[index]=True
            self.assertEqual(runtime_mask_equal(base,other),np.array_equal(base,other))
    def test_random_masks_inputs_unchanged(self):
        rng=np.random.default_rng(20261019)
        for _ in range(200):
            a=rng.integers(0,2,768,dtype=np.uint8).astype(bool);b=a.copy() if rng.integers(0,2) else rng.integers(0,2,768,dtype=np.uint8).astype(bool);before=(a.tobytes(),b.tobytes())
            self.assertEqual(runtime_mask_equal(a,b),np.array_equal(a,b));self.assertEqual(before,(a.tobytes(),b.tobytes()))
    def test_noncanonical_true_bytes_fall_back(self):
        a=np.ones(768,dtype=bool);b=np.full(768,2,dtype=np.uint8).view(bool)
        self.assertNotEqual(a.tobytes(),b.tobytes());self.assertTrue(runtime_mask_equal(a,b))
    def test_unsupported_shapes_dtypes_none_use_original(self):
        original=np.array_equal
        for a,b in ((np.zeros(768,dtype=bool),None),(np.ones(500,dtype=bool),np.ones(500,dtype=bool)),(np.ones(768,dtype=np.uint8),np.ones(768,dtype=np.uint8)),(np.ones((8,96),dtype=bool),np.ones((8,96),dtype=bool)),(np.ones(1536,dtype=bool)[::2],np.ones(768,dtype=bool))):
            with patch('candidate.np.array_equal',wraps=original) as fallback:
                self.assertEqual(runtime_mask_equal(a,b),original(a,b));fallback.assert_called_once()
    def test_canonical_boundary_does_not_call_numpy_equal(self):
        with patch('candidate.np.array_equal',side_effect=AssertionError('Unexpected original boundary')):
            self.assertTrue(runtime_mask_equal(np.ones(768,dtype=bool),np.ones(768,dtype=bool)))

class SourceScope(unittest.TestCase):
    def test_prepared_method_preserves_result_without_installing_class(self):
        def on_frame(self):
            flagged=self.flagged
            return np.array_equal(flagged,self._runtime_suspicious_mask)
        digest=hashlib.sha256(textwrap.dedent(inspect.getsource(on_frame)).encode()).hexdigest()
        replacement=prepare(on_frame,digest);obj=SimpleNamespace(flagged=np.ones(768,dtype=bool),_runtime_suspicious_mask=np.ones(768,dtype=bool))
        self.assertEqual(replacement(obj),on_frame(obj))
        with self.assertRaises(ValueError):prepare(on_frame,'wrong-source')
    def test_exactly_one_expression_changed(self):
        root=Path(__file__).resolve().parents[2];tree=ast.parse((root/'engine/device_quality_session.py').read_text());cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='DeviceQualitySession');fn=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='on_frame');source=ast.unparse(fn);changed=transformed(source)
        for node in ast.walk(changed):
            if isinstance(node,ast.Name) and node.id=='_diagnostic_runtime_mask_equal':
                # Replace the new function expression to compare complete bodies.
                node.id='np.array_equal'
        old=ast.parse(source)
        for node in ast.walk(old):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='np' and node.func.attr=='array_equal':node.func=ast.Name(id='np.array_equal',ctx=ast.Load())
        self.assertEqual(ast.dump(changed,include_attributes=False),ast.dump(old,include_attributes=False))
    def test_unexpected_source_refused(self):
        with self.assertRaises(ValueError):transformed('def on_frame(self, frame): return frame')

if __name__=='__main__':unittest.main()
