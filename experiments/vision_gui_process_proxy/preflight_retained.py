"""Validate immutable retained-window bindings without starting a target."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan03.json').read_text());assert not (HERE/'result03.json').exists()
    assert all(sha(HERE/name)==digest for name,digest in plan['sources'].items())
    source=Path(plan['retained_window_path']);manifest=json.loads((HERE/plan['retained_manifest_file']).read_text())
    assert sha(HERE/plan['retained_manifest_file'])==plan['retained_manifest_sha256']
    assert all(sha(source/name)==digest for name,digest in manifest['files'].items())
    assert sha(source/'plan02.json')==plan['retained_plan_sha256']
    run=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],capture_output=True)
    evidence=dict(returncode=run.returncode,stdout=run.stdout.decode(errors='replace'),stderr=run.stderr.decode(errors='replace'),target_started=False,target_retried=False)
    with (HERE/'retained_tests03.json').open('x') as target:json.dump(evidence,target,indent=2)
    assert run.returncode==0
    proof=dict(passed=True,plan_sha256=sha(HERE/'plan03.json'),tests_sha256=sha(HERE/'retained_tests03.json'),target_started=False,target_retried=False)
    with (HERE/'preflight_retained03.json').open('x') as target:json.dump(proof,target,indent=2)
    print(json.dumps(proof))
