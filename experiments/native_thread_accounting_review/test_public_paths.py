import unittest
from opencv_paths import public_entries
class PublicPaths(unittest.TestCase):
    def test_only_exact_module_and_halfopen_range(self):
        entries=[dict(name='cv2.resize',unwind_range=[10,20])]
        self.assertEqual(public_entries([dict(module='cv2.pyd',rva=10)],entries),['cv2.resize'])
        self.assertEqual(public_entries([dict(module='cv2.pyd',rva=20)],entries),[])
        self.assertEqual(public_entries([dict(module='other.dll',rva=15)],entries),[])
    def test_private_worker_does_not_gain_a_python_caller(self):
        self.assertEqual(public_entries([dict(module='cv2.pyd',rva=100)], [dict(name='cv2.resize',unwind_range=[10,20])]),[])
