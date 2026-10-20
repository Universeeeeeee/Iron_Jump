import unittest
from collections import Counter
from native_worker import wrap_method


class WorkerContract(unittest.TestCase):
    def test_same_return_and_exception_objects_preserved(self):
        token=object();fault=RuntimeError('original')
        class Target:
            def call(self,fail=False):
                if fail:raise fault
                return token
        calls=Counter();original=wrap_method(Target,'call',calls)
        try:
            self.assertIs(Target().call(),token)
            with self.assertRaises(RuntimeError) as caught:Target().call(True)
            self.assertIs(caught.exception,fault);self.assertEqual(calls['call'],1)
        finally:Target.call=original
