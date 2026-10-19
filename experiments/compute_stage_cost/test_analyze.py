import unittest
from analyze import summarize

class Summary(unittest.TestCase):
    def row(self):return dict(block=0,wall_ns=10,thread_cpu_ns=11,operations=1,calls={'feed':1})
    def test_negative_residual_retained(self):self.assertEqual(summarize([self.row()])['formal']['negative_wall_minus_cpu_blocks'],[0])
    def test_duplicate_block_rejected(self):
        with self.assertRaises(AssertionError):summarize([self.row(),self.row()])
    def test_inconsistent_count_rejected(self):
        r=self.row();r['operations']=2
        with self.assertRaises(AssertionError):summarize([r])

if __name__=='__main__':unittest.main()
