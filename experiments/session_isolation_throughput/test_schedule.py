import unittest
import numpy as np
from analyze01 import scheduled_times
class Schedule(unittest.TestCase):
    def args(self):return [np.array([1,2,3]),np.array([10,20,30]),2,[dict(revision=1,armed=False,arm_pause_ns=0,anchor_ns=100,original_start_ns=10),dict(revision=2,armed=True,arm_pause_ns=50,anchor_ns=150,original_start_ns=10)]]
    def test_checked_sample_uses_prearm_epoch(self):self.assertEqual(scheduled_times(*self.args()).tolist(),[100,110,170])
    def test_gap_rejected(self):
        a=self.args();a[0]=np.array([1,2,4])
        with self.assertRaises(ValueError):scheduled_times(*a)
    def test_receipt_origin_must_match_preserved_history(self):
        a=self.args();a[1]+=1
        with self.assertRaises(ValueError):scheduled_times(*a)
    def test_wrong_rebase_rejected(self):
        a=self.args();a[3][1]['anchor_ns']=151
        with self.assertRaises(ValueError):scheduled_times(*a)
    def test_regressing_original_time_rejected(self):
        a=self.args();a[1][2]=19
        with self.assertRaises(ValueError):scheduled_times(*a)
