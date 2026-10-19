"""Reuse the frozen owner-specific WPR controller, with no CPU sampling changes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text());assert all(sha(ROOT/n)==v for n,v in plan['sources'].items())
    stage=HERE/'runs/control01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir();record=dict(errors=[])
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    spec=importlib.util.spec_from_file_location('owned_lifecycle_controller',ROOT/'experiments/native_stack_capture/record.py');controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller);controller.HERE=HERE
    try:
        record['interval_before']=profile_interval()
        controller.main(SimpleNamespace(mode='lifecycle',output=stage/'window',seconds=3.,targets=None))
        record['interval_after']=profile_interval();assert record['interval_after']==record['interval_before']
        status=subprocess.run(['wpr','-status'],capture_output=True);record['wpr_status']=dict(returncode=status.returncode,stdout=status.stdout.decode(errors='replace'),stderr=status.stderr.decode(errors='replace'))
        assert status.returncode==0 and b'WPR is not recording' in status.stdout
        record['complete']=True
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(record,f,indent=2)
    print(json.dumps(record));raise SystemExit(bool(record['errors']))
