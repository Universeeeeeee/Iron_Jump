import unittest
from analyze import p95,compare_pairs

class Endpoints(unittest.TestCase):
    def test_nearest_rank_p95(self):self.assertEqual(p95(list(range(1,21))),19)
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):p95([])
    def test_complete_fixed_pairs_required(self):
        with self.assertRaises(ValueError):compare_pairs([])
    def test_large_regression_preserved(self):
        a=dict(max_latency_ms=100,p95_latency_ms=90);pairs=[(a,dict(max_latency_ms=v,p95_latency_ms=v)) for v in (50,50,50,300)]
        r=compare_pairs(pairs);self.assertEqual(r['max_latency_ms']['candidate_minus_original_ms'],[-50,-50,-50,200])

if __name__=='__main__':unittest.main()
