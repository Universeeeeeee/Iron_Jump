import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((HERE/'plan01.json').read_text());assert not (HERE/'runs').exists()
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in p['dependency_sources'].items())
    for folder,entries in [(p['input_root'],p['input_sha256']),(p['media_root'],p['media_sha256'])]:
        assert all(sha(Path(folder)/n)==v for n,v in entries.items())
    assert sha(Path(p['model_path']))==p['model_sha256']
    assert sha(Path('D:/conda/python311.dll'))==p['python_dll_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==p['numpy_pyd_sha256']
    for name in p['sources']:
        if name.endswith('.py'):compile((HERE/name).read_text(encoding='utf-8'),name,'exec')
    with (HERE/'preflight01.json').open('x') as f:json.dump(dict(passed=True,plan_sha256=sha(HERE/'plan01.json'),source_and_inputs_match=True,target_started=False),f,indent=2)
    print('Source/input checks passed;actual context remains a runtimegate')
