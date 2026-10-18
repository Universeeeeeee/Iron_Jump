import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import atomic_io03


class AtomicHandshakeChecks(unittest.TestCase):
    def test_success_has_complete_json_and_no_partial(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json';atomic_io03.write(p,{'finished':True});self.assertEqual(json.loads(p.read_text()),{'finished':True});self.assertFalse(p.with_name('roi.json.partial').exists())
    def test_mid_write_is_invisible_to_reader(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json';started=threading.Event();release=threading.Event();real_dump=json.dump;errors=[]
            def slow_dump(v,f,**kw):
                f.write(' ');f.flush();started.set();self.assertTrue(release.wait(2));real_dump(v,f,**kw)
            def produce():
                try:atomic_io03.write(p,{'done':True})
                except BaseException as e:errors.append(e)
            with patch.object(atomic_io03.json,'dump',side_effect=slow_dump):
                t=threading.Thread(target=produce);t.start();self.assertTrue(started.wait(2));self.assertFalse(p.exists());self.assertTrue(p.with_name('roi.json.partial').exists());release.set();t.join(2)
            self.assertFalse(t.is_alive());self.assertEqual(errors,[]);self.assertEqual(json.loads(p.read_text()),{'done':True})
    def test_partial_write_failure_keeps_evidence_without_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json'
            def fail(v,f,**kw):f.write('{');raise OSError('injected write failure')
            with patch.object(atomic_io03.json,'dump',side_effect=fail),self.assertRaises(OSError):atomic_io03.write(p,{})
            self.assertFalse(p.exists());self.assertEqual(p.with_name('roi.json.partial').read_text(),'{')
    def test_fsync_failure_is_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json'
            with patch.object(atomic_io03.os,'fsync',side_effect=OSError('injected sync failure')),self.assertRaises(OSError):atomic_io03.write(p,{'done':True})
            self.assertFalse(p.exists());self.assertTrue(p.with_name('roi.json.partial').exists())
    def test_rename_failure_is_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json'
            with patch.object(Path,'rename',side_effect=OSError('injected publish failure')),self.assertRaises(OSError):atomic_io03.write(p,{})
            self.assertFalse(p.exists());self.assertTrue(p.with_name('roi.json.partial').exists())
    def test_existing_result_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json';p.write_text('old evidence')
            with self.assertRaises(FileExistsError):atomic_io03.write(p,{})
            self.assertEqual(p.read_text(),'old evidence')
    def test_failed_partial_blocks_retry(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json';part=p.with_name('roi.json.partial');part.write_text('failed evidence')
            with self.assertRaises(FileExistsError):atomic_io03.write(p,{})
            self.assertEqual(part.read_text(),'failed evidence');self.assertFalse(p.exists())


if __name__=='__main__':unittest.main()


class WindowsPublicationChecks(unittest.TestCase):
    @unittest.skipUnless(__import__('os').name=='nt','NTFS rename collision contract')
    def test_destination_appearing_during_write_is_retained(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'roi.json';real_sync=atomic_io03.os.fsync
            def concurrent_final(fd):real_sync(fd);p.write_text('other evidence')
            with patch.object(atomic_io03.os,'fsync',side_effect=concurrent_final),self.assertRaises(FileExistsError):atomic_io03.write(p,{'new':True})
            self.assertEqual(p.read_text(),'other evidence');self.assertTrue(p.with_name('roi.json.partial').exists())
