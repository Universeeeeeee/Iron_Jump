import unittest
from compare import compare

class Comparability(unittest.TestCase):
    def test_same_counts_different_frames_rejected(self):
        self.assertFalse(compare(dict(frames=[1,2],count=2),dict(frames=[1,3],count=2))['necessary_workload_identity_pass'])
    def test_reordered_work_rejected(self):
        self.assertFalse(compare(dict(frames=[1,2]),dict(frames=[2,1]))['necessary_workload_identity_pass'])
    def test_equal_work_does_not_certify_variance_or_overhead(self):
        r=compare(dict(frames=[1,2]),dict(frames=[1,2]));self.assertTrue(r['necessary_workload_identity_pass']);self.assertFalse(r['variance_estimate_available']);self.assertFalse(r['actual_load_disturbance_pass'])

if __name__=='__main__':unittest.main()
