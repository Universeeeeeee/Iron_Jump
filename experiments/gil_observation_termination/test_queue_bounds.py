import unittest
from queue_bounds import bound_deque


class QueuePeakTests(unittest.TestCase):
    def test_hidden_peak_not_replaced_by_sample_max(self):
        r=bound_deque([(0,0,0),(10,3,0)],1,3)
        self.assertEqual(r['combined_observed_deque_peak_lower_bound'],0);self.assertEqual(r['continuous_deque_peak_upper_bound'],3)
    def test_initial_unobserved_enqueues_included(self):
        self.assertEqual(bound_deque([(10,12,0)],10,12)['continuous_deque_peak_upper_bound'],3)
    def test_dequeue_prefix_regression_rejected(self):
        with self.assertRaises(ValueError):bound_deque([(0,3,0),(1,4,2),(2,4,0)],1,4)
    def test_missing_final_empty_witness_rejected(self):
        with self.assertRaises(ValueError):bound_deque([(0,3,1)],1,3)
    def test_both_observation_families_contribute(self):
        r=bound_deque([(0,0,0),(1,4,4),(2,5,3),(3,5,0)],1,5)
        self.assertEqual(r['combined_observed_deque_peak_lower_bound'],4);self.assertEqual(r['continuous_deque_peak_upper_bound'],5)
    def test_exhaustive_small_fifo_paths_and_observation_subsets(self):
        def paths(e,d,points):
            if e==d==4:yield points;return
            if e<4:yield from paths(e+1,d,points+[(e+1,d)])
            if d<e:yield from paths(e,d+1,points+[(e,d+1)])
        for path in paths(0,0,[(0,0)]):
            actual=max(e-d for e,d in path)
            for mask in range(1<<(len(path)-2)):
                chosen=[0]+[i+1 for i in range(len(path)-2) if mask&(1<<i)]+[len(path)-1]
                r=bound_deque([(i,path[i][0],path[i][0]-path[i][1]) for i in chosen],1,4)
                self.assertLessEqual(r['combined_observed_deque_peak_lower_bound'],actual);self.assertGreaterEqual(r['continuous_deque_peak_upper_bound'],actual)


if __name__=='__main__':unittest.main()
