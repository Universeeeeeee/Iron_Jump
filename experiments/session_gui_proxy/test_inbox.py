import threading
import unittest
from inbox import Inbox

class Buffers(unittest.TestCase):
    def test_fifo_bound(self):
        box=Inbox(max_messages=2,max_bytes=4);self.assertTrue(box.put(b'ab'));self.assertTrue(box.put(b'cd'))
        self.assertEqual(box.snapshot()['queued_bytes'],4);self.assertEqual(box.take(),[b'ab',b'cd'])
    def test_oversized_rejected(self):
        with self.assertRaises(ValueError):Inbox(max_bytes=1).put(b'ab')
    def test_close_wakes_receiver_without_dropping_queued_value(self):
        box=Inbox(max_messages=1);box.put(b'a');started=threading.Event();done=[]
        def put():started.set();done.append(box.put(b'b'))
        t=threading.Thread(target=put);t.start();self.assertTrue(started.wait(1));box.close();t.join(1)
        self.assertFalse(t.is_alive());self.assertEqual(done,[False]);self.assertEqual(box.take(),[b'a'])
        self.assertEqual(box.snapshot()['incoming_bytes'],1)
