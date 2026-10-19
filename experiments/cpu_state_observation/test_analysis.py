import copy
import unittest
from analyze import phase

class Intervals(unittest.TestCase):
    def fixture(self):
        rows=[dict(ordinal=i,begin_ns=i*100,end_ns=i*100+2,values={k:dict(valid=True,value=120) for k in ['performance_pct','busy_pct','queue']},power=dict(valid=True,ac=1)) for i in range(4)]
        return rows,dict(max_interval_ns=150,max_collection_bracket_ns=10,min_whole_intervals_per_phase=2)
    def test_whole_intervals_only(self):
        r,p=self.fixture();s=phase(r,50,302,p);self.assertEqual(s['ordinals'],[2,3]);self.assertTrue(s['coverage_pass'])
    def test_invalid_data(self):
        r,p=self.fixture();r[2]['values']['performance_pct']['valid']=False;self.assertFalse(phase(r,50,302,p)['coverage_pass'])
    def test_long_collection(self):
        r,p=self.fixture();r[2]['end_ns']=220;self.assertFalse(phase(r,50,302,p)['coverage_pass'])
    def test_no_clamp_above_nominal(self):
        r,p=self.fixture();self.assertEqual(phase(r,0,302,p)['median_values']['performance_pct'],120)
