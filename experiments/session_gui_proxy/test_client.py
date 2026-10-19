from pathlib import Path
from types import SimpleNamespace
import unittest
from qtpy.QtCore import QCoreApplication
from client import SessionClient

APP=QCoreApplication.instance() or QCoreApplication([])
class Queue:
    def __init__(self):self.messages=[]
    def enqueue(self,value):self.messages.append(value)

class AsyncControls(unittest.TestCase):
    def client(self):
        c=SessionClient(Path('.'),Path('.'));c.writer=Queue();c.state.phase='ready';c.state.ready_key='original-key';return c
    def test_start_pending_not_running_until_confirmation(self):
        c=self.client();self.assertTrue(c.start(acknowledge_quality=True));self.assertFalse(c.is_running);self.assertTrue(c.start_pending)
        self.assertFalse(c.start(acknowledge_quality=True));self.assertEqual(len(c.writer.messages),1)
        c.process=SimpleNamespace(pid=7)
        c._packet(dict(sequence=1,pid=7,kind='started',payload={}))
        self.assertTrue(c.is_running);self.assertFalse(c.start_pending)
    def test_no_degraded_ack_is_not_queued(self):
        c=self.client()
        with self.assertRaises(ValueError):c.start()
        self.assertEqual(c.writer.messages,[])
    def test_remote_mutable_engine_not_faked(self):
        with self.assertRaises(NotImplementedError):_ = self.client().engine
