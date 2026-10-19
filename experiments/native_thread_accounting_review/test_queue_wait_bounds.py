import unittest
from qt_wait_queue_bounds import bounds


def row(host, completed, received):
    return [host, completed, 0, received-completed, None, received]


class QueueWaitBounds(unittest.TestCase):
    def test_a_timestamp_before_wait_does_not_bound_read_completion(self):
        rows = [row(0,0,10), row(9,1,100), row(30,5,120), row(40,10,130)]
        result = bounds({'sampler':rows}, 10, 20)
        # Row at9 could finish after the wait. Only row0 is bracketed before it.
        self.assertEqual(result['before']['index'], 0)
        self.assertEqual(result['unfinished_batch_prefix_lag_lower_bound'], 5)

    def test_no_extrapolation_without_both_sides(self):
        self.assertFalse(bounds({'sampler':[row(0,0,10)]}, 10, 20)['available'])
        self.assertFalse(bounds({'sampler':[row(30,0,10),row(40,1,20)]}, 10, 20)['available'])

    def test_each_producer_supplies_its_own_completion_bracket(self):
        a = [row(0,0,50), row(8,1,80), row(30,10,100)]
        b = [row(1,0,70), row(9,2,90), row(25,8,95)]
        result = bounds({'consumer':a,'sampler':b}, 10, 20)
        self.assertEqual(result['before']['source'], 'sampler')
        self.assertEqual(result['before']['read_end_upper_ns'], 9)
        self.assertEqual(result['unfinished_batch_prefix_lag_lower_bound'], 62)
