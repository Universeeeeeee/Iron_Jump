import unittest
from cpu_delivery_review01 import placement


class PlacementChecks(unittest.TestCase):
    def fixture(self):
        points=[dict(boundary='before_roi',host_before_ns=0,host_after_ns=1,group=0,logical=3),dict(boundary='after_9',host_before_ns=4,host_after_ns=5,group=0,logical=3)]
        return dict(points=points,topology=dict(error=0,records=[dict(group=0,logical=3,core=2,efficiency_class=0)])),dict(wall_begin_ns=2,wall_end_ns=6,blocks=[dict(raw_last=9,wall_end_ns=3)])
    def test_matching_topology(self):
        v=placement(*self.fixture());self.assertEqual(v[-1]['core'],2)
    def test_missing_topology_is_unknown(self):
        d,r=self.fixture();d['topology']['records']=[];self.assertIsNone(placement(d,r)[-1]['core'])
    def test_failed_api_is_unknown(self):
        d,r=self.fixture();d['topology']['error']=5;self.assertIsNone(placement(d,r)[-1]['efficiency_class'])
    def test_duplicate_topology_rejected(self):
        d,r=self.fixture();d['topology']['records']*=2
        with self.assertRaises(AssertionError):placement(d,r)
    def test_wrong_boundary_rejected(self):
        d,r=self.fixture();d['points'][-1]['boundary']='after_8'
        with self.assertRaises(AssertionError):placement(d,r)
    def test_before_block_boundary_rejected(self):
        d,r=self.fixture();d['points'][-1]['host_before_ns']=2
        with self.assertRaises(AssertionError):placement(d,r)
    def test_reversed_bracket_rejected(self):
        d,r=self.fixture();d['points'][-1]['host_after_ns']=3
        with self.assertRaises(AssertionError):placement(d,r)


if __name__=='__main__':unittest.main()
