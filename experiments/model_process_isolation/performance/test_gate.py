import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from gate import require_gate

class Gates(unittest.TestCase):
    def test_missing_failed_and_stale_proof(self):
        with tempfile.TemporaryDirectory() as d:
            h=Path(d);(h/'plan01.json').write_text('{}');(h/'windows_tests01.json').write_text('{}')
            with self.assertRaises(FileNotFoundError):require_gate(h)
            digest=hashlib.sha256(b'{}').hexdigest();proof=dict(passed=True,plan_sha256=digest,test_record_sha256=digest)
            (h/'preflight_passed01.json').write_text(json.dumps(proof));require_gate(h)
            proof['passed']=False;(h/'preflight_passed01.json').write_text(json.dumps(proof))
            with self.assertRaises(ValueError):require_gate(h)
            proof['passed']=True;(h/'preflight_passed01.json').write_text(json.dumps(proof));(h/'windows_tests01.json').write_text('changed')
            with self.assertRaises(ValueError):require_gate(h)
