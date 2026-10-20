import threading,unittest
from types import SimpleNamespace
from queue_probe import QueueProbe


class QueueProbeTests(unittest.TestCase):
 def test_issue_only_batch_is_forwarded_without_frame_fields(self):
  seen=[];probe=QueueProbe(1,False);issue=SimpleNamespace(code='fault')
  probe.consume(None,[(True,issue)],lambda inbox,items:seen.extend(items))
  self.assertEqual(seen,[(True,issue)])
 def test_frame_batch_updates_completed_sample(self):
  frame=SimpleNamespace(sample_index=7,received_monotonic_ns=100)
  inbox=SimpleNamespace(_lock=threading.Lock(),_pending=[],quality=SimpleNamespace(latest_received_frame=frame))
  probe=QueueProbe(7,False);probe.consume(inbox,[(False,frame)],lambda inbox,items:None)
  self.assertEqual(probe.state,(7,100,None));self.assertEqual(inbox.last_consumed_sample,7)


if __name__=='__main__':unittest.main()
