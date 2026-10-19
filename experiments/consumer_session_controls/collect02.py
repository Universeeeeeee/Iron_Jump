"""Archive original single delivery and verify terminal state; never launches it."""
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
    plan=read(HERE/'plan02.json');status=read(HERE/'runs02/status.json')
    query="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and $_.Name -eq 'python.exe'}|Select-Object ProcessId,CommandLine)|ConvertTo-Json -Compress"
    check=subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,check=True);assert not check.stdout.strip()
    assert status['complete'] and status['cases']==plan['cases'] and not status['errors']
    for name in status['cases']:
        result=read(HERE/'runs02'/name/'status.json');actor=read(HERE/'runs02'/name/'actor/result.json')
        assert result['complete'] and not result['actor_still_alive'] and result['actor_exitcode']==0
        assert actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['controller_released']
    assert not read(HERE/'runs/status.json')['complete']
    assert sha(HERE/'runs/full_with_unsupported_pause/status.json')==read(HERE/'first_review01.json')['bindings']['truncated_status_sha256']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
    assert all(sha(Path(n))==v for n,v in plan['external_native_sha256'].items())
    assert sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256'] and sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
    baseline=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')['baseline_files'];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
    assert all(sha(formal/n)==v for n,v in baseline.items())
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    interval=profile_interval();assert interval==10000
    wpr=subprocess.run(['wpr','-status'],capture_output=True);assert wpr.returncode==0 and b'WPR is not recording' in wpr.stdout
    audit=dict(no_targets=True,reader_and_qt_thread_stopped=True,old_cohort_failure_and_status_bytes_preserved=True,formal_files_unchanged=len(baseline),sources_dependencies_inputs_oracles_libraries_unchanged=True,
        wpr_not_recording=True,sampling_interval_100ns=interval,locks_retained=sorted(p.relative_to(HERE).as_posix() for base in (HERE/'runs',HERE/'runs02') for p in base.rglob('active.lock')))
    with (HERE/'audit02.json').open('x') as f:json.dump(audit,f,indent=2)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.jsonl','.npz','.stdout','.stderr')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in files}
    with (HERE/'manifest02.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence02.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest02.json','manifest02.json')
        for n in audit['locks_retained']:z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence02.zip'),manifest_files=len(manifest),audit=audit)))
