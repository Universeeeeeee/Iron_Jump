import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from run_gate import require_gate

class Gate(unittest.TestCase):
    def test_bound_sources_and_tests(self):
        with tempfile.TemporaryDirectory() as d:
            h=Path(d);(h/'code.py').write_text('pass');sha=lambda n:hashlib.sha256((h/n).read_bytes()).hexdigest()
            (h/'plan02.json').write_text(json.dumps(dict(launch_authorized_by_this_plan=True,sources={'code.py':sha('code.py')})))
            (h/'windows_tests02.json').write_text('{}')
            with self.assertRaises(FileNotFoundError):require_gate(h)
            gate=dict(passed=True,plan_sha256=sha('plan02.json'),tests_sha256=sha('windows_tests02.json'))
            (h/'preflight02.json').write_text(json.dumps(gate));require_gate(h)
            (h/'code.py').write_text('changed')
            with self.assertRaises(ValueError):require_gate(h)
