import hashlib,json,pickle,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from report_artifact import read_report,report_reference
from outbox import Outbox

class ReportArtifactTests(unittest.TestCase):
 def test_report_larger_than_ipc_bound_is_delivered_by_reference(self):
  from client import LiveSessionProcess
  report={'visual_timeline':'x'*(9*1024*1024),'walking_summary':{'event_publications':[{'contact_id':1}]}}
  with tempfile.TemporaryDirectory() as temporary:
   folder=Path(temporary);(folder/'actor').mkdir();(folder/'actor/report.json').write_text(json.dumps(report),encoding='utf-8')
   reference=report_reference(folder/'actor');message=dict(sequence=1,pid=7,kind='report_value',payload=dict(report_reference=reference))
   self.assertGreater(reference['bytes'],8*1024*1024);self.assertLess(len(pickle.dumps(message)),1024)
   packets=[];box=Outbox(SimpleNamespace(send_bytes=packets.append));box.enqueue(message);self.assertTrue(box.finish(2));self.assertEqual(box.max_bytes,8*1024*1024)
   client=SimpleNamespace(sequence=0,process=SimpleNamespace(pid=7),folder=folder,report=None)
   LiveSessionProcess._packet(client,pickle.loads(packets[0]));self.assertEqual(client.report,report)
 def test_modified_report_is_rejected(self):
  with tempfile.TemporaryDirectory() as temporary:
   folder=Path(temporary);path=folder/'report.json';path.write_bytes(b'{"a":1}');reference=report_reference(folder);path.write_bytes(b'{"a":2}')
   with self.assertRaises(ValueError):read_report(folder,reference)
 def test_truncated_report_is_rejected(self):
  with tempfile.TemporaryDirectory() as temporary:
   folder=Path(temporary);path=folder/'report.json';path.write_bytes(b'{"a":1}');reference=report_reference(folder);path.write_bytes(b'{}')
   with self.assertRaises(ValueError):read_report(folder,reference)
 def test_missing_report_is_not_completion(self):
  with tempfile.TemporaryDirectory() as temporary:
   with self.assertRaises(FileNotFoundError):read_report(Path(temporary),dict(file='report.json',bytes=2,sha256='x'))
 def test_paths_and_out_of_bound_sizes_are_rejected(self):
  with tempfile.TemporaryDirectory() as temporary:
   folder=Path(temporary)
   for reference in (dict(file='../report.json',bytes=2),dict(file='report.json',bytes=64*1024*1024+1)):
    with self.assertRaises(ValueError):read_report(folder,reference)
 def test_small_report_bound_is_enforced(self):
  with tempfile.TemporaryDirectory() as temporary:
   folder=Path(temporary);(folder/'report.json').write_bytes(b'{}')
   with patch('report_artifact.MAX_REPORT_BYTES',1):
    with self.assertRaises(ValueError):report_reference(folder)

if __name__=='__main__':unittest.main()
