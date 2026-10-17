"""Ensure the synthetic progress stream brackets the external observer's end."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from align_clock import mapping
from external_report import work_bounds
from observe import observe

HERE=Path(__file__).resolve().parent


@unittest.skipUnless(sys.platform=='win32','Windows native fixture required')
class FixtureTests(unittest.TestCase):
    def test_progress_saved_after_observer_end(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);stop=root/'stop'
            child=subprocess.Popen([sys.executable,str(HERE/'external_fixture.py'),'sdk',str(root/'fixture'),str(stop)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                targets=json.loads(child.stdout.readline())['targets']
                time.sleep(.1)
                counters=observe(targets,.2)
                ending=time.perf_counter_ns()
                stop.touch()
                stdout,stderr=child.communicate(timeout=5)
                self.assertEqual(child.returncode,0,stderr)
                fixture=json.loads((root/'fixture/progress.json').read_text())
                self.assertGreaterEqual(fixture['history'][-1]['host_before_ns'],ending)
                anchors=fixture['anchors']+[r[k] for g in ['before','after'] for r in counters[g] for k in ['start','end']]
                clock=mapping(anchors)
                for before,after in zip(counters['before'],counters['after']):
                    bounded=work_bounds(fixture['history'],before['name'],before,after,clock)
                    self.assertLessEqual(bounded['lower'],bounded['upper'])
            finally:
                if child.poll() is None:
                    stop.touch();child.communicate(timeout=5)


if __name__=='__main__':unittest.main()
