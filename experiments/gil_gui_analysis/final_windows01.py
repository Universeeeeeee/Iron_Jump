"""Read-only preservation audit; no target, SDK, recorder or sampling start."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


here=Path(__file__).resolve().parent;root=here.parents[1];old=root/'experiments/gil_gui_calibration'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(here/'stack_plan01.json');prior=read(old/'post_repeat01.json');formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
def mismatch(base,expected):return [n for n,h in expected.items() if not (base/n).is_file() or sha(base/n)!=h]
locks={n:Path(x['path']).is_dir() for n,x in prior['old_locks'].items()};locks.update({n:(old/n).is_dir() for n in prior['new_locks']});locks['stack01']=(here/'runs/stack01/active.lock').is_dir()
sys.path.insert(0,str(old));from winapi import profile_interval
status=subprocess.run(['wpr.exe','-status'],capture_output=True,check=False);(here/'final_wpr_status01.txt').write_bytes(status.stdout+status.stderr)
ps="@((Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe') -and ($_.CommandLine -like '*IronJump-gil-*' -or $_.CommandLine -match '-m\\s+camera\\.control_service')})|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
query=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,check=True);active=json.loads(query.stdout.decode('utf-8-sig')) if query.stdout.strip() else []
result=dict(formal_count=len(plan['baseline_files']),formal_mismatches=mismatch(formal,plan['baseline_files']),gui_copy_mismatches=mismatch(root,plan['baseline_files']),frozen_source_mismatches=mismatch(root,plan['frozen_sources']),dependency_mismatches=mismatch(root,plan['dependencies']),input_mismatches=mismatch(Path(plan['input_root']),plan['input_sha256']),locks=locks,remaining_processes=active,sampling_interval_100ns=profile_interval(),python_dll_sha256=sha(Path('D:/conda/python311.dll')),numpy_sha256=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),wpr_not_recording=status.returncode==0 and b'WPR is not recording' in status.stdout,source_sha256=sha(Path(__file__)))
result['preservation_pass']=not any(value for key,value in result.items() if key.endswith('mismatches')) and all(locks.values()) and not active and result['sampling_interval_100ns']==10000 and result['python_dll_sha256']==plan['python_dll_sha256'] and result['numpy_sha256']==plan['numpy_pyd_sha256'] and result['wpr_not_recording']
with (here/'final_windows01.json').open('x') as f:json.dump(result,f,indent=2)
print(json.dumps(result));raise SystemExit(not result['preservation_pass'])
