import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from preflight_gate import require_gate

class PreflightTests(unittest.TestCase):
    def files(self,p):
        for n in ('plan01.json','windows_tests01.json','delivery_review01.json'):(p/n).write_text('{}')
        h=hashlib.sha256(b'{}').hexdigest();proof=dict(passed=True,windows_tests_passed=True,observed_delivery_and_semantics_pass=True,plan_sha256=h,test_record_sha256=h,delivery_review_sha256=h)
        (p/'preflight_passed01.json').write_text(json.dumps(proof));return proof
    def test_no_proof_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):require_gate(Path(tmp))
    def test_failed_tests_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);proof=self.files(p);proof['windows_tests_passed']=False;(p/'preflight_passed01.json').write_text(json.dumps(proof))
            with self.assertRaises(ValueError):require_gate(p)
    def test_changed_plan_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.files(p);(p/'plan01.json').write_text('{"changed":true}')
            with self.assertRaises(ValueError):require_gate(p)
    def test_exact_passed_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);self.files(p);self.assertTrue(require_gate(p)['passed'])
