import json,hashlib,subprocess
from pathlib import Path
h=Path(__file__).resolve().parent;p=json.loads((h/'plan01.json').read_text());sha=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
assert all(sha(h/n)==v for n,v in p['sources'].items())
assert not (h/'next_plan02.json').exists()
r=subprocess.run(['D:/conda/python.exe','-m','unittest','discover','-s',str(h),'-p','test_*.py'],capture_output=True)
v=dict(returncode=r.returncode,stderr=r.stderr.decode(),old_runtime_hashes_unchanged=True,new_actor_window_started=False,old_cohort_complete=json.loads((h/'runs/status.json').read_text())['complete'])
with (h/'poll_fix_tests01.json').open('x') as f:json.dump(v,f,indent=2)
print(json.dumps(v));raise SystemExit(r.returncode)
