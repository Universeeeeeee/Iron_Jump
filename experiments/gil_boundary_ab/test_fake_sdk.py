import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

class SimulatedSDK(unittest.TestCase):
    def test_original_settings_and_tracking_protocol(self):
        methods=['set_fov','set_auto_focus','set_exposure_compensation','set_anti_flicker','set_wdr']
        commands=[dict(method=n,args=[0]) for n in methods]+[dict(method='tracking_start',args=[1]),dict(method='tracking_stop',args=[])]
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'backend.json'
            p=subprocess.run([sys.executable,str(Path(__file__).parent/'fake_sdk.py'),str(output)],input=''.join(json.dumps(x)+'\n' for x in commands),capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr);record=json.loads(output.read_text());self.assertEqual(record['backend'],'simulated_native_SDK');self.assertTrue(record['no_native_device_opened']);self.assertEqual(record['calls']['close'],1)
            replies=[json.loads(x[len('IRON_CAMERA_CONTROL '):]) for x in p.stdout.splitlines() if x.startswith('IRON_CAMERA_CONTROL ')]
            self.assertFalse([r for r in replies if 'error' in r]);self.assertTrue(any(r.get('stopped') for r in replies));self.assertEqual([(r['method'],r['result']) for r in replies if 'method' in r],[(x['method'],0) for x in commands])

if __name__=='__main__':unittest.main()
