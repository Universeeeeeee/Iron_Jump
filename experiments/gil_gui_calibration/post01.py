"""Read-only final preservation and quiescence audit for the GUI pilot."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from winapi import profile_interval


here=Path(__file__).resolve().parent;root=here.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(here/'aa_plan01.json');formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
def mismatch(folder,expected):return [n for n,h in expected.items() if not (folder/n).is_file() or sha(folder/n)!=h]
prior=read(Path('E:/OptoJump/IronJump-gil-observer-noise-20261018-01/final_audit_windows01.json'))
v=dict(formal_mismatches=mismatch(formal,plan['baseline_files']),gui_mismatches=mismatch(root,plan['baseline_files']),dependency_mismatches=mismatch(root,plan['dependencies']),input_mismatches=mismatch(Path(plan['input_root']),plan['input_sha256']),oracle_mismatches=mismatch(Path(plan['oracle_root']),plan['oracle_sha256']),smoke_frozen_mismatches=mismatch(root,read(here/'frozen_sources.json')['files']),aa_frozen_mismatches=mismatch(root,read(here/'aa_frozen_sources01.json')['files']),old_locks={n:dict(path=p['path'],retained=Path(p['path']).is_dir()) for n,p in prior['locks'].items()},new_locks={n:(here/n).is_dir() for n in ('runs/functional_smoke01/active.lock','runs/off_aa01/active.lock')},numpy_pyd_sha256=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),sampling_interval_100ns=profile_interval(),source_sha256=sha(Path(__file__)))
ps="@((Get-CimInstance Win32_Process|Where-Object {$_.Name -eq 'python.exe' -and $_.ProcessId -ne "+str(os.getpid())+" -and ($_.CommandLine -like '*IronJump-gil-*' -or $_.CommandLine -match '-m\\s+camera\\.control_service')})|Select-Object ProcessId,ParentProcessId,CommandLine)|ConvertTo-Json -Compress"
query=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,check=True)
v['remaining_processes']=json.loads(query.stdout.decode('utf-8-sig')) if query.stdout.strip() else []
v['preservation_pass']=not any(value for key,value in v.items() if key.endswith('mismatches')) and all(p['retained'] for p in v['old_locks'].values()) and all(v['new_locks'].values()) and v['sampling_interval_100ns']==10000 and v['numpy_pyd_sha256']==plan['numpy_pyd_sha256'] and not v['remaining_processes']
with (here/'post01.json').open('x') as f:json.dump(v,f,indent=2)
print(json.dumps(v));raise SystemExit(not v['preservation_pass'])
