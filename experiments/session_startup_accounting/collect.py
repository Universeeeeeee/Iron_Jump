"""Archive fixed-cohort successes and failures only after actual targets are absent."""
import hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');stage=HERE/'runs/cohort01';status=read(stage/'status.json')
    query="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and $_.Name -eq 'python.exe'}|Select-Object ProcessId,CommandLine)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,check=True);assert not p.stdout.strip(),'Live targets; preserve and wait, never restart'
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
    assert all(sha(Path(n))==v for n,v in plan['external_native_sha256'].items())
    assert sha(Path('D:/conda/python311.dll'))==plan['python_dll_sha256'] and sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==plan['numpy_pyd_sha256']
    assert sha(ROOT/plan['formal_baseline_manifest'])==plan['formal_baseline_manifest_sha256']
    baseline=read(ROOT/plan['formal_baseline_manifest'])['baseline_files'];formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017');assert all(sha(formal/n)==v for n,v in baseline.items())
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import profile_interval
    interval=profile_interval();assert interval==10000
    wpr=subprocess.run(['wpr','-status'],capture_output=True);assert wpr.returncode==0 and b'WPR is not recording' in wpr.stdout
    audit=dict(collection_attempt=1,collector_sha256=sha(Path(__file__)),no_targets=True,cohort_complete=status['complete'],attempted_cases=status['cases'],errors=status['errors'],formal_files_unchanged=len(baseline),frozen_sources_inputs_libraries_unchanged=True,wpr_not_recording=True,sampling_interval_100ns=interval,
        locks_retained=sorted(p.relative_to(HERE).as_posix() for p in stage.rglob('active.lock')))
    with (HERE/'audit01.json').open('x') as f:json.dump(audit,f,indent=2)
    files=[p for p in stage.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.ps1','.json','.stdout','.stderr')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in files}
    with (HERE/'manifest01.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest01.json','manifest01.json')
        for n in audit['locks_retained']:z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),audit=audit)))
