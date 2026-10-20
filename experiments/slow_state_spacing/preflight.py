import hashlib
import json
from pathlib import Path
import subprocess
import sys
from spacing import SystemReader,busy

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=json.loads((HERE/'plan01.json').read_text());assert not (HERE/'runs').exists()
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in p['dependency_sources'].items())
    assert all(sha(Path(p['input_root'])/n)==v for n,v in p['input_sha256'].items())
    assert all(sha(Path(p['media_root'])/n)==v for n,v in p['media_sha256'].items())
    assert sha(Path(p['model_path']))==p['model_sha256']
    assert sha(Path('D:/conda/python311.dll'))==p['python_dll_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==p['numpy_pyd_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/cv2/cv2.pyd'))==p['cv2_sha256']
    root=Path(p['replay_root']);base=json.loads((root/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    assert all(sha(root/n)==v for n,v in base.items())
    r=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_rules.py'],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    reader=SystemReader();samples=[reader.read() for _ in range(2)]
    assert all(v['end_ns']>=v['begin_ns'] for v in samples)
    assert all(samples[1][key]>=samples[0][key] for key in ('idle_100ns','kernel_including_idle_100ns','user_100ns'))
    result=dict(passed=True,tests_output=r.stdout+r.stderr,native_read_own_process_samples=samples,
        plan_sha256=sha(HERE/'plan01.json'),full_source_input_library_hashes_match=True,application_started=False,
        limitation='Native reads work; no observer-equivalence, hardfault, GHz orper-core idle qualification.')
    with (HERE/'preflight01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
