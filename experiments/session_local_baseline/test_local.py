import os
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from qtpy.QtCore import QCoreApplication
from local import LocalSession
APP=QCoreApplication.instance() or QCoreApplication([])
class LocalBaseline(unittest.TestCase):
    def ready(self):return dict(method='tracking_start',code=0,gui_pid=os.getpid(),sdk_pid=os.getpid()+1,observed_ns=7)
    def test_no_source_release_before_prepare(self):
        c=LocalSession('.',Path('.'));c.sdk_ready(self.ready());self.assertIsNone(c.source);self.assertEqual(c.sdk_info,self.ready())
    def test_latched_real_reply_releases_prepared_source(self):
        c=LocalSession('.',Path('.'));c.sdk_ready(self.ready());c.source=SimpleNamespace(sdk_ready=threading.Event());c.state.phase='prepared';c._enable_source();self.assertTrue(c.source.sdk_ready.is_set())
    def test_failed_reply_never_releases_source(self):
        c=LocalSession('.',Path('.'));v=self.ready();v['code']=-1
        with self.assertRaises(ValueError):c.sdk_ready(v)
        self.assertIsNone(c.sdk_info)
    def test_wrong_parent_identity_rejected(self):
        c=LocalSession('.',Path('.'));v=self.ready();v['gui_pid']+=1
        with self.assertRaises(ValueError):c.sdk_ready(v)
    def test_queued_start_does_not_fake_running_state(self):
        c=LocalSession('.',Path('.'));calls=[];c.controller=SimpleNamespace(is_running=False,start=lambda **kw:calls.append(kw));c.state.phase='ready'
        self.assertTrue(c.start(acknowledge_quality=True,quality_key='key'));self.assertFalse(c.is_running);self.assertTrue(c.start_pending);self.assertEqual(len(calls),1)
    def test_original_is_running_is_authoritative(self):
        c=LocalSession('.',Path('.'));c.controller=SimpleNamespace(is_running=True);self.assertTrue(c.is_running);self.assertFalse(c.start(acknowledge_quality=True))
