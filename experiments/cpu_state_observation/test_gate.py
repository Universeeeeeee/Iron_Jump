import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cohort

class GateTests(unittest.TestCase):
    def test_bound_gate_and_failures(self):
        with tempfile.TemporaryDirectory() as d,patch.object(cohort,'HERE',Path(d)):
            p=Path(d);(p/'plan01.json').write_text(json.dumps(dict(sources={},dependency_sources={})))
            with self.assertRaises(FileNotFoundError):cohort.require_gate()
            gate=dict(passed=True,plan_sha256=hashlib.sha256((p/'plan01.json').read_bytes()).hexdigest())
            (p/'preflight_passed01.json').write_text(json.dumps(gate));cohort.require_gate()
            gate['passed']=False;(p/'preflight_passed01.json').write_text(json.dumps(gate))
            with self.assertRaises(AssertionError):cohort.require_gate()
            gate['passed']=True;(p/'preflight_passed01.json').write_text(json.dumps(gate));(p/'plan01.json').write_text('{}')
            with self.assertRaises(AssertionError):cohort.require_gate()
