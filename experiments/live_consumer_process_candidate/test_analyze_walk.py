import unittest
from analyze_walk import queue_bound


class QueueBoundTests(unittest.TestCase):
 def test_continuous_upper_uses_next_enqueue_and_previous_dequeue(self):
  rows=[[10,-1,0,2,1,1,9,2,0,'pending',None,None,0],[20,1,9,1,11,2,19,1,0,'pending',None,None,0],[30,3,29,0,None,3,29,0,0,'empty',None,None,0]]
  self.assertEqual(queue_bound(rows,0,3),(True,3))
 def test_missing_final_empty_witness_fails(self):
  self.assertEqual(queue_bound([[10,-1,0,2,1,1,9,2,0,'pending',None,None,0]],0,3),(False,2))


if __name__=='__main__':unittest.main()
