"""Archive the one fixed synthetic cohort, including expected fault states."""
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
    assert status['complete'] and not status['errors'] and status['cases']==plan['cases']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    query="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and $_.Name -eq 'python.exe'}|Select-Object ProcessId,CommandLine)|ConvertTo-Json -Compress"
    processes=subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,check=True);assert not processes.stdout.strip()
    for name in plan['cases']:
        result=read(HERE/'runs'/name/'result.json');assert result['contract_pass'] and not result['errors'] and not result['final_outbox']['writer_alive']
        for path in (HERE/'runs'/name).rglob('state.json'):
            saved=read(path);assert all(sha(path.parent/n)==v for n,v in saved['unconfirmed_files'].items())
    baseline=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')['baseline_files'];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
    assert all(sha(formal/n)==v for n,v in baseline.items())
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    interval=profile_interval();assert interval==10000
    wpr=subprocess.run(['wpr','-status'],capture_output=True);assert wpr.returncode==0 and b'WPR is not recording' in wpr.stdout
    audit=dict(no_related_python_targets=True,all_writer_threads_confirmed_stopped=True,all_sources_unchanged=True,all_unconfirmed_packet_hashes_pass=True,
        formal_files_unchanged=len(baseline),wpr_not_recording=True,sampling_interval_100ns=interval,locks_retained=sorted(p.relative_to(HERE).as_posix() for p in (HERE/'runs').rglob('active.lock')))
    with (HERE/'audit01.json').open('x') as f:json.dump(audit,f,indent=2)
    files=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.pickle')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in files}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for n in audit['locks_retained']:z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),audit=audit)))
