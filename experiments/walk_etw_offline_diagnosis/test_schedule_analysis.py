"""Measurement correctness checks: partitioning, missing evidence and bad clocks."""
import unittest

import numpy as np

from analyze_schedule import DT, reconstruct, summarize, validate_clock


def fixture():
    cs = np.zeros(8, dtype=DT)
    cs['qpc'] = [0, 10, 40, 60, 90, 100, 120, 130]
    ids = np.zeros((8, 6), dtype=np.uint32)
    ids[::2, 0] = 1
    ids[1::2, 1] = 1
    cs['payload'][1::2, 14] = [5, 1, 2, 5]
    return cs, ids


class ScheduleMeasurementTest(unittest.TestCase):
    def test_partition_and_boundary_clipping(self):
        cs, ids = fixture()
        segments, pauses = reconstruct(cs, ids, np.array([25, 110]), 1, 1)
        result = summarize(segments, pauses, 0, 130)
        self.assertEqual(result['seconds'], {'Running': 50e-9, 'Ready': 55e-9,
                                           'Waiting': 15e-9, 'Transition': 10e-9, 'Unknown': 0})
        self.assertEqual(summarize(segments, pauses, 20, 30)['seconds']['Waiting'], 5e-9)

    def test_missing_ready_is_unknown_not_assumed_waiting(self):
        cs, ids = fixture()
        segments, pauses = reconstruct(cs, ids, np.array([110]), 1, 1)
        result = summarize(segments, pauses, 10, 40)
        self.assertEqual(result['seconds']['Unknown'], 30e-9)
        self.assertEqual(result['seconds']['Waiting'], 0)

    def test_impossible_migration_rejected(self):
        cs, ids = fixture()
        cs['cpu'][1] = 1
        with self.assertRaises(AssertionError):
            reconstruct(cs, ids, np.array([25, 110]), 1, 1)

    def test_clock_disagreement_rejected(self):
        meta = {'qpc_frequency': 10000000, 'clock_type': 1,
                'clock_samples': [{'qpc': 10, 'utc_filetime_100ns': 1010}]}
        native = {'clock_brackets': [{'before': {'perf_before_ns': 999999999,
                   'perf_after_ns': 1000000000, 'utc_filetime_100ns': 1010}}]}
        with self.assertRaises(AssertionError):
            validate_clock(meta, native)


if __name__ == '__main__':
    unittest.main()
