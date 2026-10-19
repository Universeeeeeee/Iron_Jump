"""Archive one terminal window, including failures; no rerun or success reclassification."""
import hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    number=int(sys.argv[1]);assert number==1
    tag=f'{number:02d}';stage=HERE/('runs' if number==1 else 'runs02');plan=read(HERE/f'plan{tag}.json')
    query="@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and $_.Name -eq 'python.exe'}|Select-Object ProcessId,CommandLine)|ConvertTo-Json -Compress"
    processes=subprocess.run(['powershell','-NoProfile','-Command',query],capture_output=True,check=True);assert not processes.stdout.strip(),'Live Python targets; never archive as completed'
    assert (stage/'finalization.json').exists() and ((stage/'pipeline_failure.json').exists() or (stage/'pipeline_review.json').exists())
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
    audit=dict(no_targets=True,formal_files_unchanged=len(baseline),frozen_sources_inputs_libraries_unchanged=True,wpr_not_recording=True,sampling_interval_100ns=interval,
        window_pass=(stage/'pipeline_review.json').exists(),failure_preserved=(stage/'pipeline_failure.json').exists(),
        locks_retained=sorted(p.relative_to(HERE).as_posix() for p in stage.rglob('active.lock')))
    with (HERE/f'audit{tag}.json').open('x') as f:json.dump(audit,f,indent=2)
    files=[p for p in stage.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.ps1','.json','.stdout','.stderr')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in files}
    with (HERE/f'manifest{tag}.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/f'evidence{tag}.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/f'manifest{tag}.json',f'manifest{tag}.json')
        for n in audit['locks_retained']:z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/f'evidence{tag}.zip'),manifest_files=len(manifest),audit=audit)))
