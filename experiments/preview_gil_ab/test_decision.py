import unittest
from decision import decide


class FrozenDecision(unittest.TestCase):
    def fixture(self):
        pairs=[dict(original=f'a{i}',bridge=f'b{i}') for i in range(4)]
        plan=dict(pairs=pairs,cases=[dict(id=n) for p in pairs for n in p.values()],decision=dict(input_lateness_max_ms=100,
            severe_observed_queue_at_least=1000,severe_scheduled_latency_at_least_ms=1000,candidate_queue_upper_max=250,
            candidate_scheduled_latency_max_ms=250,minimum_severe_pair_latency_reduction=.5,minimum_severe_original_windows=3))
        rows={}
        for p in pairs:
            common=dict(complete=True,semantics_pass=True,native_SDK_pass=True,input_lateness_ms=10)
            rows[p['original']]=dict(common,observed_queue_lower=1500,queue_upper=1550,scheduled_max_ms=1700)
            rows[p['bridge']]=dict(common,observed_queue_lower=70,queue_upper=140,scheduled_max_ms=180)
        return rows,plan
    def test_one_slow_first_window_cannot_pass(self):
        rows,p=self.fixture()
        for i in (1,2,3):rows[f'a{i}'].update(observed_queue_lower=80,scheduled_max_ms=190)
        r=decide(rows,p);self.assertFalse(r['advance']);self.assertEqual(r['reason'],'severe_baseline_not_reproduced')
    def test_mediocre_candidate_or_quality_failure_rejected(self):
        rows,p=self.fixture();rows['b2']['queue_upper']=251
        self.assertFalse(decide(rows,p)['advance'])
        rows,p=self.fixture();rows['b0']['input_lateness_ms']=101
        self.assertEqual(decide(rows,p)['reason'],'protocol_or_input_quality_failed')
    def test_complete_severe_improvement_still_not_formal_fix(self):
        rows,p=self.fixture();r=decide(rows,p)
        self.assertTrue(r['advance']);self.assertFalse(r['formal_fix_verified'])
    def test_missing_window_rejected(self):
        rows,p=self.fixture();rows.pop('a0')
        with self.assertRaises(AssertionError):decide(rows,p)
