import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from capture import capture

class Controller(unittest.TestCase):
    def scenario(self,start=0,stop=0,status=0,intervals=(10000,10000)):
        with tempfile.TemporaryDirectory() as tmp:
            h=Path(tmp)
            (h/'capture_plan02.json').write_text(json.dumps(dict(instance='test',sources={})))
            calls=[]
            def run(args,**kwargs):
                calls.append(args)
                code=start if '-start' in args else stop if '-stop' in args else status if '-status' in args else 0
                out=b'WPR is not recording' if '-status' in args else b''
                return subprocess.CompletedProcess(args,code,out,b'')
            values=iter(intervals);code=capture(h,run,lambda:next(values))
            return code,json.loads((h/'capture01.json').read_text()),calls,(h/'active.lock').exists()
    def test_start_failure_never_runs_target_or_claims_cleanup(self):
        code,r,calls,lock=self.scenario(start=1)
        self.assertEqual(code,1);self.assertFalse(r['target_started']);self.assertFalse(r['cleanup_confirmed']);self.assertTrue(lock)
        self.assertFalse(any('-stop' in a or a[0].endswith('python') for a in calls))
    def test_stop_failure_preserved(self):
        code,r,_,lock=self.scenario(stop=1)
        self.assertEqual(code,1);self.assertFalse(r['cleanup_confirmed']);self.assertTrue(lock)
    def test_unknown_status_not_cleanup(self):
        self.assertFalse(self.scenario(status=1)[1]['cleanup_confirmed'])
    def test_interval_change_not_cleanup(self):
        self.assertFalse(self.scenario(intervals=(10000,20000))[1]['cleanup_confirmed'])
    def test_confirmed_stop_and_independent_absence(self):
        self.assertEqual(self.scenario()[0],0)

if __name__=='__main__':unittest.main()
