"""Archive terminal fixed cohort including failures; never launch or replace cases."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');status=read(HERE/'runs/status.json')
    script="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    processes=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,check=True);assert not processes.stdout.strip(),'Targets still running; do not collect/restart'
    baseline=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')['baseline_files'];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    interval=profile_interval();wpr=subprocess.run(['wpr','-status'],capture_output=True)
    audit=dict(no_related_targets=True,all_runtime_sources_unchanged=all(sha(HERE/n)==v for n,v in plan['sources'].items()),dependencies_unchanged=all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items()),
        formal_files_unchanged=all(sha(formal/n)==v for n,v in baseline.items()),formal_file_count=len(baseline),input_unchanged=all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items()),
        media_unchanged=all(sha(Path(plan['media_root'])/n)==v for n,v in plan['media_sha256'].items()),model_unchanged=sha(Path(plan['model_path']))==plan['model_sha256'],
        python_dll_unchanged=sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256'],numpy_pyd_unchanged=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256'],
        sampling_interval_100ns=interval,wpr_not_recording=wpr.returncode==0 and b'WPR is not recording' in wpr.stdout,
        locks_retained=sorted(p.relative_to(HERE).as_posix() for p in (HERE/'runs').rglob('active.lock')),cohort_complete=status['complete'])
    with (HERE/'audit01.json').open('x') as f:json.dump(audit,f,indent=2)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.stdout','.stderr','.txt')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in files}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for n in audit['locks_retained']:z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),audit=audit)))
