"""Preserve delivery windows and failed/post-capture test logs; no new workload."""
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
    plan=read(HERE/'plan01.json');child=read(HERE/'child/plan01.json');status=read(HERE/'runs/delivery01/status.json')
    command="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'ReadStacks.exe')}|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
    query=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,check=True);assert not query.stdout.strip()
    baseline=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')['baseline_files'];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    wpr=subprocess.run(['wpr','-status'],capture_output=True);assert wpr.returncode==0 and b'WPR is not recording' in wpr.stdout
    audit=dict(no_related_targets=True,sources_unchanged=all(sha(HERE/n)==v for n,v in plan['sources'].items()),dependencies_unchanged=all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items()),formal_files_unchanged=all(sha(formal/n)==v for n,v in baseline.items()),formal_file_count=len(baseline),
        inputs_unchanged=all(sha(Path(child['input_root'])/n)==v for n,v in child['input_sha256'].items()),media_unchanged=all(sha(Path(child['media_root'])/n)==v for n,v in child['media_sha256'].items()),model_unchanged=sha(Path(child['model_path']))==child['model_sha256'],
        cv2_unchanged=sha(Path('D:/conda/Lib/site-packages/cv2/cv2.pyd'))==plan['cv2_sha256'],numpy_unchanged=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==child['numpy_pyd_sha256'],python_unchanged=sha(Path('D:/conda/python311.dll'))==child['python_dll_sha256'],
        sampling_interval_100ns=profile_interval(),wpr_not_recording=True,locks_retained=sorted(p.relative_to(HERE).as_posix() for p in HERE.rglob('active.lock')),delivery_complete=status['complete'])
    with (HERE/'audit_delivery01.json').open('x') as f:json.dump(audit,f,indent=2)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.jsonl','.stdout','.stderr','.wprp')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in files}
    with (HERE/'manifest_delivery01.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'delivery_evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest_delivery01.json','manifest_delivery01.json')
        for n in audit['locks_retained']:z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'delivery_evidence01.zip'),manifest_files=len(manifest),ETLs={p.relative_to(HERE).as_posix():sha(p) for p in HERE.rglob('*.etl')},audit=audit)))
