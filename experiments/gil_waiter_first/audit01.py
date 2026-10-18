"""Post-control read-only preservation and process-state audit."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;GUI=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01');PAUSE=Path('E:/OptoJump/IronJump-gil-pause-control-20261019-01')
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan01.json');base=read(GUI/'experiments/gil_gui_analysis/stack_plan01.json');prior=read(GUI/'experiments/gil_gui_calibration/post_repeat01.json')
    def mismatch(base,files):return [n for n,h in files.items() if not (base/n).is_file() or sha(base/n)!=h]
    locks={n:Path(x['path']).is_dir() for n,x in prior['old_locks'].items()};locks.update({n:(GUI/'experiments/gil_gui_calibration'/n).is_dir() for n in prior['new_locks']})
    locks['stack01']=(GUI/'experiments/gil_gui_analysis/runs/stack01/active.lock').is_dir()
    locks.update({'pause_'+n:(PAUSE/'runs'/n/'active.lock').is_dir() for n in ('baseline01','early_owner_pause01')})
    locks.update(positive01=(HERE/'runs/active.lock').is_dir(),negative01=(HERE/'runs/negative01/active.lock').is_dir())
    sys.path.insert(0,plan['native_helpers']);from winapi import profile_interval
    command="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,check=True);active=json.loads(p.stdout.decode('utf-8-sig')) if p.stdout.strip() else []
    wpr=subprocess.run(['wpr.exe','-status'],capture_output=True);(HERE/'wpr_status01.txt').write_bytes(wpr.stdout+wpr.stderr)
    result=dict(formal_files=len(base['baseline_files']),formal_mismatches=mismatch(Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017'),base['baseline_files']),gui_copy_mismatches=mismatch(GUI,base['baseline_files']),old_frozen_mismatches=mismatch(GUI,base['frozen_sources']),dependency_mismatches=mismatch(GUI,base['dependencies']),input_mismatches=mismatch(Path(base['input_root']),base['input_sha256']),new_frozen_mismatches=mismatch(HERE,plan['sources']),
                native_helpers_match_prior_frozen_copy=all(sha(Path(plan['native_helpers'])/n)==sha(PAUSE/'frozen_helpers'/n) for n in ('observe.py','winapi.py')),
                observer_sha256=sha(Path(plan['observer_path'])),old_observer_sha256=sha(Path('E:/OptoJump/IronJump-gil-observer-noise-20261018-01/observer.exe')),
                python_dll_sha256=sha(Path('D:/conda/python311.dll')),numpy_sha256=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),
                locks=locks,remaining_processes=active,sampling_interval_100ns=profile_interval(),wpr_not_recording=wpr.returncode==0 and b'WPR is not recording' in wpr.stdout)
    result['preservation_pass']=(not any(v for n,v in result.items() if n.endswith('mismatches')) and result['native_helpers_match_prior_frozen_copy'] and all(locks.values()) and not active and result['sampling_interval_100ns']==10000 and result['wpr_not_recording'] and result['observer_sha256']==plan['observer_sha256'] and result['python_dll_sha256']==plan['python_dll_sha256'] and result['numpy_sha256']==base['numpy_pyd_sha256'] and result['old_observer_sha256']=='02e367c7ca0b1cda5f1067b03125a770a502f10fcabb99fa5925b4265050d615')
    with (HERE/'audit01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['preservation_pass'])
