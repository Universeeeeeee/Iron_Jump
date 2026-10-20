import unittest
from decision import decide

def row(latency=100,queue=100,upper=100,video=800,inferences=400,complete=True):
    return dict(complete=complete,input_lateness_ms=10,scheduled_max_ms=latency,observed_queue_lower=queue,queue_upper=upper,
        work=dict(video=video,inferences=inferences),context_comparable=True)

class DecisionTests(unittest.TestCase):
    def plan(self):
        return dict(aa_cases=['a1','a2','a3','a4'],pairs=[dict(original='o1',process='p1')],decision=dict(input_lateness_max_ms=100,
            aa_relative_range_max=.03,severe_observed_queue_at_least=1000,severe_scheduled_latency_at_least_ms=1000,minimum_severe_original_windows=1,
            candidate_queue_upper_max=250,candidate_scheduled_latency_max_ms=250,minimum_severe_pair_latency_reduction=.5))
    def test_unstable_aa_blocks_advance(self):
        rows={n:row() for n in ('a1','a2','a3','a4')};rows['a1']=row(200);rows.update(o1=row(2000,1200,1300),p1=row(200,100,200))
        self.assertEqual(decide(rows,self.plan())['reason'],'aa_variability_exceeds_gate')
    def test_stable_aa_and_severe_bounded_pair_advances(self):
        rows={n:row(100+i/10,100+i/10,100) for i,n in enumerate(('a1','a2','a3','a4'))};rows.update(o1=row(2000,1200,1300),p1=row(200,100,200))
        self.assertTrue(decide(rows,self.plan())['advance'])
    def test_fast_original_cannot_substitute(self):
        rows={n:row() for n in ('a1','a2','a3','a4')};rows.update(o1=row(200,100,200),p1=row(100,50,100))
        self.assertEqual(decide(rows,self.plan())['reason'],'severe_baseline_not_reproduced')

if __name__=='__main__':unittest.main()
