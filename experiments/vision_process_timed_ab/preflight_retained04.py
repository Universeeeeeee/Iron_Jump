"""Rehash the complete plan03 cohort before offline analysis; starts no target."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan04.json').read_text());assert not (HERE/'result04.json').exists()
    assert all(sha(HERE/name)==digest for name,digest in plan['sources'].items())
    source=Path(plan['retained_window_path']);manifest=json.loads((HERE/plan['retained_manifest_file']).read_text())
    assert sha(HERE/plan['retained_manifest_file'])==plan['retained_manifest_sha256'] and all(sha(source/name)==digest for name,digest in manifest['files'].items())
    assert sha(source/'plan03.json')==plan['retained_plan_sha256'] and sha(Path(plan['input_root'])/'raw_frames.npz')==plan['input_sha256']['raw_frames.npz']
    run=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],capture_output=True,text=True)
    evidence=dict(returncode=run.returncode,output=run.stdout+run.stderr,target_started=False,target_retried=False)
    with (HERE/'retained_tests04.json').open('x') as target:json.dump(evidence,target,indent=2)
    assert run.returncode==0
    proof=dict(passed=True,plan_sha256=sha(HERE/'plan04.json'),tests_sha256=sha(HERE/'retained_tests04.json'),target_started=False,target_retried=False)
    with (HERE/'preflight_retained04.json').open('x') as target:json.dump(proof,target,indent=2)
    print(json.dumps(proof))
