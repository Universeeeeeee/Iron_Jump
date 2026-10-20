import unittest
from boundary import verify

class BoundaryTests(unittest.TestCase):
    def test_original_requires_no_proxy(self):verify(dict(mode='original',restored=True,installed=False,proxy=None),'original')
    def test_process_requires_cleanup(self):
        value=dict(mode='process',restored=True,installed=True,proxy=dict(complete=True,errors=[],model_closed=True,child_alive=False,shared_memory_unlinked=True))
        verify(value,'process')
    def test_process_rejects_live_child(self):
        value=dict(mode='process',restored=True,installed=True,proxy=dict(complete=True,errors=[],model_closed=True,child_alive=True,shared_memory_unlinked=False))
        with self.assertRaises(AssertionError):verify(value,'process')

if __name__=='__main__':unittest.main()
