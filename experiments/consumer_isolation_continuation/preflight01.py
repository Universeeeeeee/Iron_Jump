import subprocess,json,hashlib
from pathlib import Path
h=Path(__file__).resolve().parent;root=h.parents[1];p=json.loads((h/'plan02.json').read_text());sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
assert not (h/'runs').exists()
assert all(sha(h/n)==v for n,v in p['sources'].items())
assert all(sha(root/n)==v for n,v in p['existing_sources'].items())
assert all(sha(Path(p['input_root'])/n)==v for n,v in p['input_sha256'].items())
assert all(sha(Path(n))==v for n,v in p['external_native_sha256'].items())
assert sha(Path('D:/conda/python311.dll'))==p['python_dll_sha256']
assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==p['numpy_pyd_sha256']
for n in p['sources']:
 if n.endswith('.py'):compile((h/n).read_text(encoding='utf-8'),n,'exec')
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s',str(h),'-p','test_*.py'],capture_output=True)
v=dict(returncode=r.returncode,stderr=r.stderr.decode(),all_source_input_oracle_hashes_pass=True,workload_started=False,preflight_attempt=1,checker_sha256=sha(Path(__file__)))
with (h/'windows_tests02.json').open('x') as f:json.dump(v,f,indent=2)
print(json.dumps(v));raise SystemExit(r.returncode)
