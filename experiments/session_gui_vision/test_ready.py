from pathlib import Path
import unittest
from qtpy.QtCore import QCoreApplication
from client import SessionClient

APP=QCoreApplication.instance() or QCoreApplication([])
class Writer:
    def __init__(self):self.messages=[]
    def enqueue(self,value):self.messages.append(value)

class ReadyGate(unittest.TestCase):
    def test_sdk_ready_before_actor_prepared_is_latched_not_sent(self):
        c=SessionClient(Path('.'),Path('.'));c.writer=Writer()
        info=dict(method='tracking_start',code=0,sdk_pid=4,gui_pid=2,observed_ns=1)
        c.sdk_ready(info);self.assertEqual(c.writer.messages,[])
        c.state.phase='prepared';c._enable_source();c._enable_source()
        self.assertEqual([v['kind'] for v in c.writer.messages],['source_ready'])
        self.assertEqual(c.writer.messages[0]['info'],info)
    def test_failed_sdk_reply_cannot_release_source(self):
        c=SessionClient(Path('.'),Path('.'));c.writer=Writer()
        with self.assertRaises(ValueError):c.sdk_ready(dict(method='tracking_start',code=-1,sdk_pid=4))
        self.assertEqual(c.writer.messages,[])
