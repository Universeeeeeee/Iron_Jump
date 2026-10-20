"""Freeze and test the timed cohort without starting Qt, SDK, media or model work."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan03.json').read_text(encoding='utf-8'));assert not (HERE/'runs').exists()
    assert all(sha(HERE/name)==digest for name,digest in plan['sources'].items())
    assert all(sha(ROOT/name)==digest for name,digest in plan['existing_sources'].items())
    assert sha(ROOT/plan['formal_baseline_manifest'])==plan['formal_baseline_manifest_sha256']
    formal=json.loads((ROOT/plan['formal_baseline_manifest']).read_text())['baseline_files'];assert all(sha(ROOT/name)==digest for name,digest in formal.items())
    assert all(sha(Path(plan['input_root'])/name)==digest for name,digest in plan['input_sha256'].items())
    assert all(sha(Path(name))==digest for name,digest in plan['external_native_sha256'].items())
    assert sha(Path(plan['model_path']))==plan['model_sha256'] and sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
    for name in plan['sources']:
        if name.endswith('.py'):compile((HERE/name).read_text(encoding='utf-8'),name,'exec')
    run=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],capture_output=True,text=True)
    tests=dict(returncode=run.returncode,output=run.stdout+run.stderr,source_input_native_hashes_match=True,workload_started=False)
    with (HERE/'windows_tests01.json').open('x') as target:json.dump(tests,target,indent=2)
    assert run.returncode==0
    proof=dict(passed=True,plan_sha256=sha(HERE/'plan03.json'),tests_sha256=sha(HERE/'windows_tests01.json'),workload_started=False)
    with (HERE/'preflight_passed01.json').open('x') as target:json.dump(proof,target,indent=2)
    print(json.dumps(proof))
