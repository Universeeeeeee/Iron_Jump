import tempfile
from pathlib import Path
import sys
import unittest
from launch import capture

class CaptureTests(unittest.TestCase):
    def test_info_stderr_is_not_process_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case';r,t=capture([sys.executable,'-c',"import sys;sys.stderr.write('INFO: model ready\\n')"],p,10)
            self.assertTrue(r['complete']);self.assertEqual((p/'stderr.log').read_text(),'INFO: model ready\n')
    def test_nonzero_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            r,t=capture([sys.executable,'-c','raise SystemExit(7)'],Path(tmp)/'case',10)
            self.assertFalse(r['complete']);self.assertEqual(r['returncode'],7);self.assertFalse(r['target_still_running'])
    def test_timeout_keeps_live_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case';r,t=capture([sys.executable,'-c','import time;time.sleep(.2)'],p,.01)
            try:
                self.assertTrue(r['observation_timeout']);self.assertTrue(r['target_still_running']);self.assertFalse(r['complete']);saved=(p/'result.json').read_bytes()
            finally:t.wait(timeout=10)
            self.assertEqual((p/'result.json').read_bytes(),saved)
    def test_existing_window_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'case';p.mkdir()
            with self.assertRaises(FileExistsError):capture([sys.executable,'-c','pass'],p,10)
