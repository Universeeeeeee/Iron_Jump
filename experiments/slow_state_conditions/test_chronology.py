import unittest
from chronology import utc_bounds, prefix_equal, FILETIME_EPOCH_NS


class ClockAndIdentity(unittest.TestCase):
    def test_each_endpoint_retains_its_own_wall_clock_bracket(self):
        first=dict(filetime_100ns=200000000,perf_before_ns=100,perf_after_ns=200)
        second=dict(filetime_100ns=200001010,perf_before_ns=100100,perf_after_ns=100200)
        self.assertEqual(utc_bounds(150,first),[20000000000-FILETIME_EPOCH_NS-50,20000000000-FILETIME_EPOCH_NS+50])
        a=utc_bounds(100150,second)
        self.assertEqual(a[1]-a[0],100)
        # These endpoints have different UTC/perf offsets. Do not pretend a
        # single exact UTC translation applies throughout the interval.
        self.assertNotEqual(a[0]-100150,utc_bounds(150,first)[0]-150)

    def test_missing_bracket_or_reversed_interval_is_rejected(self):
        with self.assertRaises(KeyError):utc_bounds(1,dict(perf_ns=1))
        with self.assertRaises(AssertionError):utc_bounds(1,dict(filetime_100ns=1,perf_before_ns=3,perf_after_ns=2))

    def test_later_matching_input_does_not_extend_equal_prefix(self):
        self.assertEqual(prefix_equal([1,2,3,4],[1,2,9,4]),2)
