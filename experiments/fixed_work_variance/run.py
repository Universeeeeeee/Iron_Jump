"""Four prospectively fixed OFF/OFF pairs using the qualified work boundary."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text())
    assert all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    if len(sys.argv)>1:
        # Reuse the exact boundary implementation. Its source and imports are
        # independently bound; HERE only selects this new plan/output directory.
        old=HERE.parent/'fixed_work_accounting';sys.path.insert(0,str(old))
        spec=importlib.util.spec_from_file_location('qualified_boundary_runner',old/'run.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        runner.HERE=HERE;raise SystemExit(runner.child(sys.argv[1]))
    folder=HERE/'runs';folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir();status=dict(cases=[],errors=[])
    try:
        for name in plan['cases']:
            with (folder/(name+'.stdout')).open('xb') as out,(folder/(name+'.stderr')).open('xb') as err:
                child=subprocess.Popen([sys.executable,str(HERE/'run.py'),name],stdout=out,stderr=err)
                try:code=child.wait(timeout=480)
                except subprocess.TimeoutExpired:status['unconfirmed_pid']=child.pid;raise
            status['cases'].append(dict(name=name,exit_code=code))
            print(json.dumps(dict(case=name,exit_code=code)),flush=True)
            if code:raise RuntimeError('Failed case retained; abort remaining fixed cases: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (folder/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(bool(status['errors']))
