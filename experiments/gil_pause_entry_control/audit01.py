"""Post-control read-only source/dependency/lock/process audit."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
GUI=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01')
FORMAL=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan01.json');old=read(GUI/'experiments/gil_gui_analysis/stack_plan01.json')
    def mismatch(base,expected):return [n for n,h in expected.items() if not (base/n).is_file() or sha(base/n)!=h]
    prior=read(GUI/'experiments/gil_gui_calibration/post_repeat01.json')
    locks={n:Path(x['path']).is_dir() for n,x in prior['old_locks'].items()}
    locks.update({n:(GUI/'experiments/gil_gui_calibration'/n).is_dir() for n in prior['new_locks']})
    locks['stack01']=(GUI/'experiments/gil_gui_analysis/runs/stack01/active.lock').is_dir()
    locks.update({n:(HERE/'runs'/n/'active.lock').is_dir() for n in plan['cases']})
    sys.path.insert(0,plan['native_helpers']);from winapi import profile_interval
    command="@(Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe')} | Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,check=True)
    active=json.loads(p.stdout.decode('utf-8-sig')) if p.stdout.strip() else []
    wpr=subprocess.run(['wpr.exe','-status'],capture_output=True);(HERE/'wpr_status01.txt').write_bytes(wpr.stdout+wpr.stderr)
    result=dict(formal_files=len(old['baseline_files']),formal_mismatches=mismatch(FORMAL,old['baseline_files']),
                gui_copy_mismatches=mismatch(GUI,old['baseline_files']),old_frozen_mismatches=mismatch(GUI,old['frozen_sources']),
                dependency_mismatches=mismatch(GUI,old['dependencies']),input_mismatches=mismatch(Path(old['input_root']),old['input_sha256']),
                new_frozen_mismatches=mismatch(HERE,plan['sources']),
                helper_copy_matches=all(sha(HERE/'frozen_helpers'/n)==sha(Path(plan['native_helpers'])/n) for n in ('observe.py','winapi.py')),
                observer_sha256=sha(Path(plan['observer_path'])),python_dll_sha256=sha(Path('D:/conda/python311.dll')),
                numpy_sha256=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd')),
                prior_analysis_sha256=sha(GUI/'experiments/gil_gui_analysis/analysis_summary01.json'),
                locks=locks,remaining_processes=active,sampling_interval_100ns=profile_interval(),
                wpr_not_recording=wpr.returncode==0 and b'WPR is not recording' in wpr.stdout)
    result['preservation_pass']=(not any(v for n,v in result.items() if n.endswith('mismatches')) and
                                 result['helper_copy_matches'] and all(locks.values()) and not active and
                                 result['sampling_interval_100ns']==10000 and result['wpr_not_recording'] and
                                 result['python_dll_sha256']==plan['python_dll_sha256'] and result['numpy_sha256']==old['numpy_pyd_sha256'] and
                                 result['observer_sha256']==plan['observer_sha256'] and result['prior_analysis_sha256']==plan['original_gui_analysis_sha256'])
    with (HERE/'audit01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['preservation_pass'])
