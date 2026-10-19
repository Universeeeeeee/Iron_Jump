import unittest
from analyze import pair_events,overlap

class Events(unittest.TestCase):
    def test_pair(self):
        x=pair_events(dict(overflow=False,rows=[[10,1,0,2,1,7,0,0],[20,2,1,2,1,7,5,0]]));self.assertEqual(x[0]['collected'],5)
    def test_missing_stop_rejected(self):
        with self.assertRaises(AssertionError):pair_events(dict(overflow=False,rows=[[10,1,0,2,1,7,0,0]]))
    def test_overflow_rejected(self):
        with self.assertRaises(AssertionError):pair_events(dict(overflow=True,rows=[]))
    def test_boundary_overlap_clipped(self):self.assertEqual(overlap(dict(wall_begin_ns=15,wall_end_ns=25),dict(begin_ns=10,end_ns=20)),5)

if __name__=='__main__':unittest.main()
