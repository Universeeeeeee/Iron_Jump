import subprocess,json,hashlib
from pathlib import Path
h=Path(__file__).resolve().parent;root=h.parents[2];p=json.loads((h/'plan01.json').read_text());sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
assert not (h/'runs').exists()
assert all(sha(h/n)==v for n,v in p['sources'].items()) and all(sha(root/n)==v for n,v in p['dependency_sources'].items())
assert sha(h.parent/'delivery_review01.json')==p['delivery_review_sha256']
assert json.loads((h.parent/'delivery_review01.json').read_text())['observed_delivery_and_complete_semantics_pass']
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s',str(h),'-p','test_*.py'],capture_output=True)
v=dict(returncode=r.returncode,stderr=r.stderr.decode(),performance_started=False)
with (h/'windows_tests01.json').open('x') as f:json.dump(v,f,indent=2)
print(json.dumps(v));raise SystemExit(r.returncode)
