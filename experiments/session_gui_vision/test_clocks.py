import unittest
from clocks import SourceClock,validate_anchors

class Clocks(unittest.TestCase):
    def anchor(self):return dict(frequency=1000000,perf_before_ns=999000,perf_after_ns=1003000,qpc_before=1000,qpc_after=1002)
    def first(self):return dict(revision=1,armed=False,arm_pause_ns=0,anchor_ns=100,original_start_ns=7)
    def test_history_and_live_origin_not_confused(self):
        c=SourceClock('.');c.apply(self.first());c.apply(dict(revision=2,armed=True,arm_pause_ns=5,anchor_ns=105,original_start_ns=7))
        self.assertEqual(c.original_start_ns,7);self.assertEqual(c.anchor_ns,105)
    def test_bad_rebase_rejected(self):
        c=SourceClock('.');c.apply(self.first())
        with self.assertRaises(ValueError):c.apply(dict(revision=2,armed=True,arm_pause_ns=5,anchor_ns=106,original_start_ns=7))
    def test_missing_initial_epoch(self):
        with self.assertRaises(ValueError):SourceClock('.').apply(dict(revision=2))
    def test_qpc_clock_domain(self):self.assertTrue(validate_anchors([self.anchor() for _ in range(6)])['all_six_brackets_pass'])
    def test_clock_offset_not_fitted_away(self):
        a=[self.anchor() for _ in range(6)];a[0]['perf_before_ns']+=1000000000;a[0]['perf_after_ns']+=1000000000
        with self.assertRaises(ValueError):validate_anchors(a)
    def test_wide_bracket_rejected(self):
        a=[self.anchor() for _ in range(6)];a[0]['perf_after_ns']+=1000001
        with self.assertRaises(ValueError):validate_anchors(a)
