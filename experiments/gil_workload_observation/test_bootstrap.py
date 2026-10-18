"""Exercise the real entry from a foreign cwd, before the old replay adds ROOT."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class BootstrapTests(unittest.TestCase):
    def test_repository_import_before_replay_from_foreign_cwd(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'repo';here=root/'experiments/observation';old=root/'experiments/gil_gui_calibration';outside=base/'outside'
            for p in (here,old,root/'vision',outside):p.mkdir(parents=True)
            shutil.copyfile(Path(__file__).parent/'entry01.py',here/'entry01.py')
            (root/'vision/__init__.py').write_text("marker='temporary-repository'\n")
            (old/'winapi.py').write_text("def anchor():return {'test':True}\n")
            (old/'atomic_io03.py').write_text("import json\ndef write(p,v):\n    with p.open('x') as f:json.dump(v,f)\n")
            (here/'workload.py').write_text("class Audit:\n    def install(self):\n        import vision\n        assert vision.marker=='temporary-repository'\n    def finish(self):return {'marker':'temporary-repository'}\n")
            (old/'entry02.py').write_text("from pathlib import Path\nimport sys\np=Path(sys.argv[sys.argv.index('--output')+1]);p.mkdir();(p/'measurement.json').write_text('{}');raise SystemExit(0)\n")
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            p=subprocess.run([sys.executable,str(here/'entry01.py'),'--output',str(base/'capture')],cwd=outside,env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            result=json.loads((base/'capture/workload01.json').read_text());self.assertEqual(result['marker'],'temporary-repository');self.assertTrue(result['replay_serialized'])


if __name__=='__main__':unittest.main()
