import subprocess,json,hashlib
from pathlib import Path
h=Path(__file__).resolve().parent;p=json.loads((h/'plan01.json').read_text());sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
assert not (h/'runs').exists()
assert all(sha(h/n)==v for n,v in p['sources'].items())
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s',str(h),'-p','test_*.py'],capture_output=True)
v=dict(returncode=r.returncode,stderr=r.stderr.decode(),cohort_started=False)
with (h/'windows_tests01.json').open('x') as f:json.dump(v,f,indent=2)
print(json.dumps(v));raise SystemExit(r.returncode)
