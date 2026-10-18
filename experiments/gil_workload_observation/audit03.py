"""Read-only preservation after the stopped pair; no replay or device operation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan02.json');base=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json');prior=read(ROOT/'experiments/gil_gui_calibration/post_repeat01.json')
    def mismatch(base,expected):return [n for n,v in expected.items() if not (base/n).is_file() or sha(base/n)!=v]
    locks={n:Path(x['path']).is_dir() for n,x in prior['old_locks'].items()};locks.update({n:(ROOT/'experiments/gil_gui_calibration'/n).is_dir() for n in prior['new_locks']})
    locks['stack01']=(ROOT/'experiments/gil_gui_analysis/runs/stack01/active.lock').is_dir()
    pause=Path('E:/OptoJump/IronJump-gil-pause-control-20261019-01');first=Path('E:/OptoJump/IronJump-gil-waiter-first-20261019-01')
    locks.update({'pause_'+n:(pause/'runs'/n/'active.lock').is_dir() for n in ('baseline01','early_owner_pause01')})
    locks.update(waiter_first_positive=(first/'runs/active.lock').is_dir(),waiter_first_negative=(first/'runs/negative01/active.lock').is_dir())
    locks.update({'metadata_'+n:(HERE/'runs'/n/'active.lock').is_dir() for n in ('observation01','observation02')})
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'));from winapi import profile_interval
    ps="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,check=True);active=json.loads(p.stdout.decode('utf-8-sig')) if p.stdout.strip() else []
    wpr=subprocess.run(['wpr.exe','-status'],capture_output=True);(HERE/'wpr_status03.txt').write_bytes(wpr.stdout+wpr.stderr)
    results=dict(formal_count=len(base['baseline_files']),formal_mismatches=mismatch(Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017'),base['baseline_files']),gui_copy_mismatches=mismatch(ROOT,base['baseline_files']),old_existing_mismatches=mismatch(ROOT,plan['frozen_existing']),new_source_mismatches=mismatch(HERE,plan['sources']),input_mismatches=mismatch(Path(plan['input_root']),plan['input_sha256']),external_native_mismatches=[n for n,v in plan['external_native_sha256'].items() if sha(Path(n))!=v],
                 python_dll_sha256=sha(Path('D:/conda/python311.dll')),numpy_pyd_sha256=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),
                 locks=locks,remaining_processes=active,sampling_interval_100ns=profile_interval(),WPR_not_recording=wpr.returncode==0 and b'WPR is not recording' in wpr.stdout,
                 metadata_acceptance_pass=False,actual_load_disturbance_pass=False,field_attribution_ready=False)
    results['preservation_and_OS_quiescence_pass']=(not any(v for n,v in results.items() if n.endswith('mismatches')) and all(locks.values()) and not active and results['python_dll_sha256']==plan['python_dll_sha256'] and results['numpy_pyd_sha256']==plan['numpy_pyd_sha256'] and results['sampling_interval_100ns']==10000 and results['WPR_not_recording'])
    with (HERE/'audit03.json').open('x') as f:json.dump(results,f,indent=2)
    print(json.dumps(results,indent=2));raise SystemExit(not results['preservation_and_OS_quiescence_pass'])
