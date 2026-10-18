import unittest
from gc_review import pair_events


class GCEventChecks(unittest.TestCase):
    def fixture(self):return dict(overflow=False,events=[[1,10,0,2,1,33],[5,12,1,2,1,33]])
    def test_pair_preserves_clock_and_identity(self):
        v=pair_events(self.fixture());self.assertEqual(v[0]['wall_ns'],4);self.assertEqual(v[0]['tid'],33)
    def test_overflow_rejected(self):
        v=self.fixture();v['overflow']=True
        with self.assertRaises(ValueError):pair_events(v)
    def test_missing_stop_rejected(self):
        v=self.fixture();v['events'].pop()
        with self.assertRaises(ValueError):pair_events(v)
    def test_wrong_thread_rejected(self):
        v=self.fixture();v['events'][1][-1]=99
        with self.assertRaises(ValueError):pair_events(v)
    def test_backward_counter_rejected(self):
        v=self.fixture();v['events'][1][1]=9
        with self.assertRaises(ValueError):pair_events(v)
    def test_bad_generation_pair_rejected(self):
        v=self.fixture();v['events'][1][3]=1
        with self.assertRaises(ValueError):pair_events(v)


if __name__=='__main__':unittest.main()
