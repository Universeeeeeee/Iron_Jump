import unittest
from analyze_walk import queue_bound


class QueueBoundTests(unittest.TestCase):
 def test_continuous_upper_uses_next_enqueue_and_previous_dequeue(self):
  rows=[[10,-1,0,2,1,1,9,2,0,'pending',None,None,0],[20,1,9,1,11,2,19,1,0,'pending',None,None,0],[30,3,29,0,None,3,29,0,0,'empty',None,None,0]]
  self.assertEqual(queue_bound(rows,0,3),(True,3))
 def test_inflight_batch_is_included_even_when_deque_is_empty(self):
  rows=[[10,-1,0,0,None,199,9,200,200,'batch',0,199,200],[20,-1,0,0,None,299,19,300,300,'batch',0,299,300],[30,299,29,0,None,299,29,0,0,'empty',None,None,0]]
  self.assertEqual(queue_bound(rows,0,299),(True,300))
 def test_forty_inflight_frames_can_change_250_frame_verdict(self):
  rows=[[10,-1,0,210,1,249,9,250,40,'batch',0,39,40],[20,-1,0,220,1,259,19,260,40,'batch',0,39,40],[30,259,29,0,None,259,29,0,0,'empty',None,None,0]]
  valid,upper=queue_bound(rows,0,259)
  self.assertTrue(valid);self.assertEqual(upper,260);self.assertGreater(upper,250)
 def test_dequeued_but_uncompleted_final_witness_fails(self):
  self.assertFalse(queue_bound([[10,-1,0,0,None,39,9,40,40,'batch',0,39,40]],0,39)[0])
 def test_inconsistent_completed_witness_fails(self):
  self.assertFalse(queue_bound([[10,39,9,0,None,39,9,40,40,'batch',0,39,40]],0,39)[0])
 def test_missing_final_empty_witness_fails(self):
  self.assertEqual(queue_bound([[10,-1,0,2,1,1,9,2,0,'pending',None,None,0]],0,3),(False,2))


if __name__=='__main__':unittest.main()
