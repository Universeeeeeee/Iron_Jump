"""Measurement tests: uncertainty windows must remain explicit and disjoint."""
import unittest
import numpy as np
from align import union, aggregate, schedule


class AlignmentTests(unittest.TestCase):
    def test_union_does_not_double_count_overlapping_brackets(self):
        self.assertEqual(union([(2, 5), (1, 3), (5, 6), (8, 9), (7, 7)]), [[1, 6], [8, 9]])

    def test_state_totals_use_union_and_preserve_unknown(self):
        segments = np.array([(0, 10, 'Running', -1), (10, 20, 'Unknown', 6),
                             (20, 30, 'Ready', 6)], dtype=schedule.SDT)
        pauses = np.array([(10, 30, 5, 6)], dtype=schedule.PDT)
        result = aggregate(segments, pauses, union([(0, 15), (10, 25)]))
        self.assertAlmostEqual(sum(result['seconds'].values()), 25e-9)
        self.assertAlmostEqual(result['fraction']['Unknown'], .4)
        self.assertAlmostEqual(result['fraction']['Ready'], .2)
        self.assertEqual(result['seconds']['Waiting'], 0)

    def test_inner_interval_can_be_empty(self):
        # Both endpoints lie in one 64-sample witness bracket; no exact duration.
        self.assertEqual(union([(200, 100)]), [])
        self.assertEqual(union([(100, 200)]), [[100, 200]])


if __name__ == '__main__':
    unittest.main()
