"""Archive all authorized AB windows, including any failure; never replace."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    plan=read(HERE/'plan02.json');status=read(HERE/'runs/gui02/status.json')
    assert all(not read(HERE/'runs/gui02'/n/'record.json')['target_still_running'] for n in status['cases'])
    cmd="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    query=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,check=True);assert not query.stdout.strip()
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items()) and all(sha(Path(n))==v for n,v in plan['external_native_sha256'].items())
    assert sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256'] and sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
    baseline=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')['baseline_files'];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
    assert all(sha(formal/n)==v for n,v in baseline.items())
    sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'));from winapi import profile_interval
    interval=profile_interval();assert interval==10000
    wpr=subprocess.run(['wpr.exe','-status'],capture_output=True);assert wpr.returncode==0 and b'WPR is not recording' in wpr.stdout
    (HERE/'wpr_status01.txt').write_bytes(wpr.stdout+wpr.stderr)
    locks=sorted(str(p.relative_to(HERE)) for p in (HERE/'runs').rglob('active.lock'))
    audit=dict(formal_files_unchanged=len(baseline),existing_dependencies_unchanged=True,input_and_native_libraries_unchanged=True,no_related_targets=True,WPR_not_recording=True,sampling_interval_100ns=interval,locks_retained=locks)
    with (HERE/'audit01.json').open('x') as f:json.dump(audit,f,indent=2)
    paths=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.ps1','.json','.stdout','.stderr','.txt','.npz','.log')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in paths}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for p in (HERE/'runs').rglob('active.lock'):z.write(p,p.relative_to(HERE).as_posix()+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),audit=audit)))
