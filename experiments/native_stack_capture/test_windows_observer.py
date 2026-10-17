"""Read-only handle ownership checks, using this synthetic test process only."""
import ctypes
import os
import sys
import threading
import unittest
from observe import Observer


@unittest.skipUnless(sys.platform=='win32','Windows native handles required')
class ObserverTests(unittest.TestCase):
    def test_pid_tid_mismatch_rejected(self):
        tid=ctypes.WinDLL('kernel32').GetCurrentThreadId()
        with self.assertRaises(ValueError):
            Observer([dict(pid=os.getpid()+1,tid=tid,role='gui')])

    def test_sdk_same_pid_as_gui_rejected(self):
        with self.assertRaises(ValueError):
            Observer([dict(pid=os.getpid(),tid=1,role='gui'),dict(pid=os.getpid(),tid=2,role='sdk')])

    def test_multiple_sdk_thread_handles_remain_separate(self):
        stop=threading.Event()
        threads=[threading.Thread(target=lambda:stop.wait(2)) for _ in range(2)]
        for thread in threads:thread.start()
        try:
            targets=[dict(pid=os.getpid(),tid=t.native_id,role='sdk',name='sdk_'+str(t.native_id)) for t in threads]
            observer=Observer(targets)
            try:
                rows=observer.snapshot()
                self.assertEqual({r['tid'] for r in rows},{t.native_id for t in threads})
                self.assertTrue(all(r['active'] and r['creation_100ns']>0 for r in rows))
            finally:observer.close()
        finally:
            stop.set()
            for thread in threads:thread.join()


if __name__=='__main__':unittest.main()
