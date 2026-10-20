"""Hash and test gate; never starts Qt, SDK, media decoding or the model."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text());assert not (HERE/'runs01').exists() and not (HERE/'active.lock').exists()
    assert all(sha(HERE/name)==digest for name,digest in plan['sources'].items())
    assert all(sha(ROOT/name)==digest for name,digest in plan['existing_sources'].items())
    assert all(sha(Path(plan['input_root'])/name)==digest for name,digest in plan['input_sha256'].items())
    assert sha(Path(plan['model_path']))==plan['model_sha256']
    assert all(sha(Path(name))==digest for name,digest in plan['external_native_sha256'].items())
    assert sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
    for name in plan['sources']:
        if name.endswith('.py'):compile((HERE/name).read_text(encoding='utf-8'),name,'exec')
    commands=[['D:/conda/python.exe','-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],
              ['D:/conda/python.exe','-m','unittest','discover','-s',str(ROOT/'experiments/session_gui_vision'),'-p','test_*.py']]
    outputs=[]
    for command in commands:
        run=subprocess.run(command,capture_output=True);outputs.append(dict(command=command,returncode=run.returncode,stdout=run.stdout.decode(errors='replace'),stderr=run.stderr.decode(errors='replace')))
        assert run.returncode==0
    with (HERE/'windows_tests01.json').open('x') as target:json.dump(outputs,target,indent=2)
    proof=dict(passed=True,plan_sha256=sha(HERE/'plan01.json'),tests_sha256=sha(HERE/'windows_tests01.json'),workload_started=False)
    with (HERE/'preflight_passed01.json').open('x') as target:json.dump(proof,target,indent=2)
    print(json.dumps(proof))
