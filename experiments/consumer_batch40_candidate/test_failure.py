import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from local_failure import preserve
class FailureEvidence(unittest.TestCase):
    def test_actual_prefix_and_report_retained_without_cleanup_claim(self):
        with tempfile.TemporaryDirectory() as d:
            f=SimpleNamespace(sample_index=7,frame_index=2,received_monotonic_ns=100,dropped_frames_before=0,contact_bits=b'\x01\x00',valid_bits=b'\x01\x01',wire_payload=b'\xfe',stream_id='saved',quality_flags=())
            c=SimpleNamespace(folder=Path(d),source=SimpleNamespace(delivered=[f],reader=SimpleNamespace(is_alive=lambda:True)),reports=[dict(accepted=1)])
            preserve(c);m=json.loads((Path(d)/'failed_capture/metadata.json').read_text());self.assertTrue(m['prefix_only']);self.assertFalse(m['cleanup_confirmed'])
            with np.load(Path(d)/'failed_capture/raw_prefix.npz') as z:self.assertEqual(z['sample_indices'].tolist(),[7]);self.assertEqual(z['wire'].tolist(),[[254]])
            self.assertEqual(json.loads((Path(d)/'failed_capture/reports.json').read_text()),c.reports)
            with self.assertRaises(FileExistsError):preserve(c)
    def test_before_source_creation_is_explicit_empty_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            preserve(SimpleNamespace(folder=Path(d),source=None,reports=[]));m=json.loads((Path(d)/'failed_capture/metadata.json').read_text());self.assertEqual(m['frame_count'],0);self.assertFalse(m['cleanup_confirmed'])
