"""One functional GUI/SDK smoke, no observer or performance acceptance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


here=Path(__file__).resolve().parent;root=here.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
case=here/'runs/functional_smoke01';case.mkdir(parents=True,exist_ok=False)
lock=case/'active.lock';lock.mkdir();child=None;record=dict(errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
try:
    plan=read(here/'smoke_plan01.json');frozen=read(here/'frozen_sources.json')['files']
    def unchanged():
        return all(sha(root/n)==h for n,h in frozen.items()) and all(sha(root/n)==h for n,h in plan['baseline_files'].items()) and all(sha(Path(plan['input_root'])/n)==h for n,h in plan['input_sha256'].items()) and all(sha(Path(plan['oracle_root'])/n)==h for n,h in plan['oracle_sha256'].items())
    assert unchanged()
    command=[sys.executable,str(here/'entry01.py'),'--input',plan['input_root'],'--output',str(case/'smoke01'),'--mode','walk','--variant','A','--probe','P','--load','fixed']
    record['command']=command
    with (case/'gui.log').open('xb') as log:
        child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT);record['target_pid']=child.pid
        child.wait(timeout=150)
    record['target_returncode']=child.returncode
    assert child.returncode==0,'GUI smoke failed; never replace the window'
    import semantics01
    m,*_=semantics01.verify(case/'smoke01')
    assert m['sdk']['stop_success'] and not m['errors'] and not m['sdk_errors']
    assert unchanged()
    record.update(functional_smoke_pass=True,full_semantics_exact=True,original_painter_sha256=m['renderer_sha256'],sdk=m['sdk'],pose_draws=m['pose_draws'],camera=m['camera'],threads=m['threads'])
except BaseException as exc:record['errors'].append(repr(exc))
finally:
    record['target_still_running']=child is not None and child.poll() is None
    record['lock_retained']=lock.is_dir();record['plan_sha256']=sha(here/'smoke_plan01.json');record['frozen_sources_sha256']=sha(here/'frozen_sources.json')
    with (case/'result01.json').open('x') as f:json.dump(record,f,indent=2)
print(json.dumps(record));raise SystemExit(bool(record['errors']))
