import hashlib
import json
import multiprocessing
from pathlib import Path
import pickle
import tempfile
import threading
import unittest
from outbox import Outbox,OutboxError

class Memory:
    def __init__(self):self.sent=[]
    def send_bytes(self,packet):self.sent.append(packet)

class Blocked(Memory):
    def __init__(self):super().__init__();self.entered=threading.Event();self.release=threading.Event()
    def send_bytes(self,packet):
        self.entered.set()
        if not self.release.wait(5):raise TimeoutError('Test release missing')
        super().send_bytes(packet)

class Outputs(unittest.TestCase):
    def test_fifo_detaches_original_values(self):
        c=Memory();box=Outbox(c);message=dict(sequence=1,payload=[1]);box.enqueue(message);message['payload'][0]=9
        box.enqueue(dict(sequence=2,payload=[2]));self.assertTrue(box.finish())
        self.assertEqual([pickle.loads(p)['payload'] for p in c.sent],[[1],[2]])
        self.assertFalse(box.snapshot()['parent_application_receipt_confirmed'])
    def test_inflight_counts_toward_limit_and_failure_is_sticky(self):
        c=Blocked();box=Outbox(c,max_messages=2,max_bytes=10000)
        try:
            box.enqueue(dict(sequence=1));self.assertTrue(c.entered.wait(2));box.enqueue(dict(sequence=2))
            with self.assertRaises(OutboxError):box.enqueue(dict(sequence=3))
            self.assertEqual(box.snapshot()['accepted_resident_messages'],2);self.assertFalse(box.finish(.01))
            with tempfile.TemporaryDirectory() as d:
                box.preserve(Path(d)/'fault');record=json.loads((Path(d)/'fault/state.json').read_text())
                self.assertEqual(len(record['unconfirmed_files']),2)
                for name,digest in record['unconfirmed_files'].items():self.assertEqual(hashlib.sha256((Path(d)/'fault'/name).read_bytes()).hexdigest(),digest)
        finally:c.release.set();self.assertFalse(box.finish(2))
        self.assertFalse(box.snapshot()['writer_alive'])
        self.assertEqual(box.snapshot()['failure']['reason'],'message_limit')
    def test_inflight_bytes_count(self):
        c=Blocked();first=dict(sequence=1,payload='a'*100);second=dict(sequence=2,payload='b'*100)
        limit=len(pickle.dumps(first,protocol=5))+len(pickle.dumps(second,protocol=5))-1
        box=Outbox(c,max_messages=100,max_bytes=limit)
        try:
            box.enqueue(first);self.assertTrue(c.entered.wait(2))
            with self.assertRaises(OutboxError):box.enqueue(second)
            self.assertLessEqual(box.snapshot()['accepted_resident_bytes'],limit)
        finally:c.release.set();self.assertFalse(box.finish(2))
    def test_oversized_output_rejected(self):
        box=Outbox(Memory(),max_bytes=8)
        with self.assertRaises(OutboxError):box.enqueue(dict(sequence=1,payload='oversize'))
        self.assertFalse(box.finish());self.assertEqual(box.snapshot()['accepted'],0)
    def test_bad_sequence_latches_failure(self):
        box=Outbox(Memory())
        with self.assertRaises(OutboxError):box.enqueue(dict(sequence=2))
        self.assertFalse(box.finish());self.assertEqual(box.snapshot()['failure']['reason'],'sequence_mismatch')
    def test_serialization_failure_latches(self):
        box=Outbox(Memory())
        with self.assertRaises(OutboxError):box.enqueue(dict(sequence=1,payload=lambda:0))
        self.assertFalse(box.finish());self.assertTrue(box.snapshot()['failure']['reason'].startswith('serialization_failed:'))
    def test_finish_timeout_never_becomes_success(self):
        c=Blocked();box=Outbox(c)
        try:
            box.enqueue(dict(sequence=1));self.assertTrue(c.entered.wait(2));self.assertFalse(box.finish(.01))
            self.assertEqual(box.snapshot()['failure']['reason'],'writer_stop_unconfirmed')
        finally:c.release.set();self.assertFalse(box.finish(2))
    def test_native_pipe_order(self):
        reader,writer=multiprocessing.Pipe(duplex=False);box=Outbox(writer)
        try:
            for i in range(1,9):box.enqueue(dict(sequence=i,value=i*2))
            for i in range(1,9):self.assertTrue(reader.poll(2));self.assertEqual(reader.recv(),dict(sequence=i,value=i*2))
            self.assertTrue(box.finish())
        finally:reader.close();writer.close();box.finish()
    def test_native_peer_disconnect_is_failure(self):
        reader,writer=multiprocessing.Pipe(duplex=False);reader.close();box=Outbox(writer)
        try:
            box.enqueue(dict(sequence=1));self.assertFalse(box.finish())
            self.assertTrue(box.snapshot()['failure']['reason'].startswith('send_failed:'))
            self.assertEqual(box.snapshot()['pending_sequences'],[1])
        finally:writer.close()
