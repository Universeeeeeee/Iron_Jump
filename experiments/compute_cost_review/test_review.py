import unittest
from review import validate_blocks

class Blocks(unittest.TestCase):
    def fixture(self):return dict(raw_first=1,raw_after_last=3,frames=2,wall_begin_ns=0,wall_ns=21,thread_cpu_ns=20,blocks=[dict(raw_first=1,raw_last=1,wall_begin_ns=0,wall_end_ns=10,wall_ns=10,thread_cpu_ns=11),dict(raw_first=2,raw_last=2,wall_begin_ns=10,wall_end_ns=20,wall_ns=10,thread_cpu_ns=9)])
    def test_negative_residual_preserved(self):self.assertEqual(validate_blocks(self.fixture())['negative_wall_minus_cpu_blocks'],[0])
    def test_missing_frames_rejected(self):
        x=self.fixture();x['blocks'][1]['raw_first']=3
        with self.assertRaises(AssertionError):validate_blocks(x)
    def test_unaccounted_time_gap_rejected(self):
        x=self.fixture();x['blocks'][1]['wall_begin_ns']=11;x['blocks'][1]['wall_ns']=9
        with self.assertRaises(AssertionError):validate_blocks(x)
    def test_cpu_exceeds_total_rejected(self):
        x=self.fixture();x['thread_cpu_ns']=19
        with self.assertRaises(AssertionError):validate_blocks(x)

if __name__=='__main__':unittest.main()
