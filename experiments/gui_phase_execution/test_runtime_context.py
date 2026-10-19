import unittest
from runtime_context import wrap

class BoundedReads(unittest.TestCase):
    def test_only_two_reads_and_identical_outputs(self):
        rows=[];calls=[]
        def original(n,*,offset):calls.append(n);return n+offset
        function=wrap(original,'model',rows,lambda role,n:dict(role=role,ordinal=n))
        self.assertEqual([function(n,offset=2) for n in range(150)],list(range(2,152)))
        self.assertEqual(calls,list(range(150)));self.assertEqual([r['ordinal'] for r in rows],[1,100])
    def test_original_exception_propagates(self):
        def original():raise RuntimeError('original')
        function=wrap(original,'consumer',[],lambda *a:{})
        with self.assertRaisesRegex(RuntimeError,'original'):function()
    def test_read_failure_not_silent(self):
        def fail(*args):raise OSError('read failed')
        function=wrap(lambda:1,'gui',[],fail)
        with self.assertRaises(OSError):function()
