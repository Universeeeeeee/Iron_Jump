import ast
from pathlib import Path
import unittest
from measure import transform

class Endpoints(unittest.TestCase):
    def test_original_measure_retains_same_timer_calls(self):
        root=Path(__file__).resolve().parents[2];tree=ast.parse((root/'experiments/walk_compute_offline_diagnosis/replay.py').read_text());cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Trial');fn=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='measure');source=ast.unparse(fn);changed=transform(source)
        calls=lambda x:[ast.dump(n,include_attributes=False) for n in ast.walk(x) if isinstance(n,ast.Call)]
        self.assertEqual(calls(ast.parse(source)),calls(changed))
    def test_unrecognized_method_rejected(self):
        with self.assertRaises(AssertionError):transform('def measure(self, stage): return []')

if __name__=='__main__':unittest.main()
