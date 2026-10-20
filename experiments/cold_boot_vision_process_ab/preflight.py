import hashlib,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
 p=json.loads((HERE/'plan02.json').read_text(encoding='utf-8'));assert not (HERE/'runs').exists()
 assert all(sha(HERE/n)==v for n,v in p['sources'].items()) and all(sha(ROOT/n)==v for n,v in p['existing_sources'].items())
 assert all(sha(Path(p['input_root'])/n)==v for n,v in p['input_sha256'].items()) and sha(Path(p['model_path']))==p['model_sha256']
 assert sha(ROOT/p['formal_baseline_manifest'])==p['formal_baseline_manifest_sha256']
 formal=json.loads((ROOT/p['formal_baseline_manifest']).read_text())['baseline_files'];assert all(sha(ROOT/n)==v for n,v in formal.items())
 assert all(sha(Path(n))==v for n,v in p['external_native_sha256'].items())
 assert sha(Path('D:/conda/python311.dll'))==p['python_dll_sha256'] and sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==p['numpy_pyd_sha256']
 for n in p['sources']:
  if n.endswith('.py'):compile((HERE/n).read_text(encoding='utf-8'),n,'exec')
 run=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],capture_output=True,text=True)
 tests=dict(returncode=run.returncode,output=run.stdout+run.stderr,workload_started=False);(HERE/'windows_tests01.json').write_text(json.dumps(tests,indent=2));assert run.returncode==0
 proof=dict(passed=True,plan_sha256=sha(HERE/'plan02.json'),tests_sha256=sha(HERE/'windows_tests01.json'),workload_started=False);(HERE/'preflight_passed01.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
