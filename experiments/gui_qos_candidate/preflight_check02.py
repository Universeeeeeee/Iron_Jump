"""Read-only full source/input preflight and Windows API/tests; no replay."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from runtime_context import snapshot

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan02.json').read_text())
    assert not (HERE/'runs/gui02').exists()
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
    assert all(sha(Path(n))==v for n,v in plan['external_native_sha256'].items())
    assert sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
    context=snapshot('preflight',1);assert context['process']['success'] and context['thread']['success']
    for n in plan['sources']:
        if n.endswith('.py'):compile((HERE/n).read_text(),n,'exec')
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],capture_output=True)
    record=dict(returncode=result.returncode,stderr=result.stderr.decode(),source_input_library_hashes_pass=True,context=context,replay_started=False)
    with (HERE/'windows_tests02.json').open('x') as f:json.dump(record,f,indent=2)
    print(json.dumps(record));raise SystemExit(result.returncode)
