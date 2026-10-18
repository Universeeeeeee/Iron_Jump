"""Post-case read-only audit. Metadata-tail success never erases old failures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];OLD=ROOT/'experiments/gil_workload_observation'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan01.json');base=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json');prior=read(ROOT/'experiments/gil_gui_calibration/post_repeat01.json')
    def mismatch(base,expected):return [n for n,v in expected.items() if not (base/n).is_file() or sha(base/n)!=v]
    locks={n:Path(x['path']).is_dir() for n,x in prior['old_locks'].items()};locks.update({n:(ROOT/'experiments/gil_gui_calibration'/n).is_dir() for n in prior['new_locks']})
    locks['stack01']=(ROOT/'experiments/gil_gui_analysis/runs/stack01/active.lock').is_dir()
    pause=Path('E:/OptoJump/IronJump-gil-pause-control-20261019-01');first=Path('E:/OptoJump/IronJump-gil-waiter-first-20261019-01')
    locks.update({'pause_'+n:(pause/'runs'/n/'active.lock').is_dir() for n in ('baseline01','early_owner_pause01')})
    locks.update(waiter_first_positive=(first/'runs/active.lock').is_dir(),waiter_first_negative=(first/'runs/negative01/active.lock').is_dir())
    locks.update({'metadata_'+n:(OLD/'runs'/n/'active.lock').is_dir() for n in ('observation01','observation02')})
    locks['synthetic_termination']=(ROOT/'experiments/gil_observation_termination/runs/synthetic01/active.lock').is_dir();locks['new_protocol01']=(HERE/'runs/protocol01/active.lock').is_dir()
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'));from winapi import profile_interval
    cmd="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,check=True);active=json.loads(p.stdout.decode('utf-8-sig')) if p.stdout.strip() else []
    wpr=subprocess.run(['wpr.exe','-status'],capture_output=True);(HERE/'wpr_status01.txt').write_bytes(wpr.stdout+wpr.stderr)
    result=dict(formal_files=len(base['baseline_files']),formal_mismatches=mismatch(Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017'),base['baseline_files']),gui_copy_mismatches=mismatch(ROOT,base['baseline_files']),existing_source_mismatches=mismatch(ROOT,plan['existing_sources']),new_source_mismatches=mismatch(HERE,plan['sources']),input_mismatches=mismatch(Path(plan['input_root']),plan['input_sha256']),external_native_mismatches=[n for n,v in plan['external_native_sha256'].items() if sha(Path(n))!=v],
                python_dll_sha256=sha(Path('D:/conda/python311.dll')),numpy_pyd_sha256=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),locks=locks,remaining_processes=active,sampling_interval_100ns=profile_interval(),WPR_not_recording=wpr.returncode==0 and b'WPR is not recording' in wpr.stdout,
                old_metadata_plan_sha256=sha(OLD/'plan02.json'),old_window02_acceptance_pass=False,actual_load_disturbance_pass=False,field_attribution_ready=False)
    result['preservation_and_OS_quiescence_pass']=not any(v for n,v in result.items() if n.endswith('mismatches')) and all(locks.values()) and not active and result['sampling_interval_100ns']==10000 and result['WPR_not_recording'] and result['python_dll_sha256']==plan['python_dll_sha256'] and result['numpy_pyd_sha256']==plan['numpy_pyd_sha256'] and result['old_metadata_plan_sha256']==plan['old_failed_metadata_plan_sha256']
    with (HERE/'audit01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['preservation_and_OS_quiescence_pass'])
