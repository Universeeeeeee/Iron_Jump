"""Exactly one prospective OFF/OFF feasibility pair; never replace a failure."""
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text());stage=HERE/'runs/off01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir()
    status=dict(cases=[],errors=[],complete=False,lock_retained=True,actual_load_disturbance_pass=False)
    try:
        for name in plan['cases']:
            with (stage/(name+'.stdout')).open('xb') as out,(stage/(name+'.stderr')).open('xb') as err:
                code=subprocess.run([sys.executable,str(HERE/'case.py'),name],stdout=out,stderr=err).returncode
            status['cases'].append(dict(name=name,exit_code=code))
            if code:raise RuntimeError('Failed case retained: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(bool(status['errors']))
