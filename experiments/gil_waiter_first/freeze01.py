"""Freeze the new binary/configuration before one positive and one transition control."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-waiter-first-20261019-01'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))


if __name__=='__main__':
    build=read(HERE/'build01.json');old=read(ROOT/'experiments/gil_waiter_control/plan01.json')
    assert sha(HERE/'src/main.rs')==build['rust_source_sha256']
    assert sha(HERE/'positive_control.py')==old['sources']['control.py'] and sha(HERE/'fixture.py')==old['sources']['fixture.py']
    assert build['observer_old_sha256']==old['observer_sha256'] and build['positive_dll_sha256']==old['oracle_dll_sha256']
    paths=[p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.rs','.toml','.lock','.cmd') and 'runs' not in p.parts and 'target' not in p.parts]
    sources={p.relative_to(HERE).as_posix():sha(p) for p in paths}
    with zipfile.ZipFile(HERE/'runtime_source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p.relative_to(HERE))
    w.transfer(HERE/'runtime_source01.zip',f'{w.HOST}:{REMOTE}/runtime_source01.zip')
    archive_sha=sha(HERE/'runtime_source01.zip')
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/runtime_source01.zip').Hash.ToLower() -ne '{archive_sha}'){{throw 'Package mismatch'}};if(Test-Path '{REMOTE}/plan01.json'){{throw 'Existing frozen plan'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/runtime_source01.zip' '{REMOTE}';Set-Location '{REMOTE}';Copy-Item 'E:/OptoJump/IronJump-gil-waiter-control-20261018-01/WaiterOracle.dll' positive_oracle.dll;Copy-Item 'E:/OptoJump/IronJump-gil-pause-control-20261019-01/PauseOracle.dll' negative_oracle.dll;New-Item -ItemType Directory dependency_sources|Out-Null;$registry='C:/Users/86150/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f';Copy-Item \"$registry/remoteprocess-0.5.2/src/windows/mod.rs\" dependency_sources/remoteprocess_windows.rs;Copy-Item \"$registry/remoteprocess-0.5.2/src/windows/unwinder.rs\" dependency_sources/remoteprocess_unwinder.rs;Copy-Item \"$registry/py-spy-0.4.2/src/python_spy.rs\" dependency_sources/python_spy.rs;Copy-Item 'D:/conda/include/internal/pycore_gil.h' dependency_sources/pycore_gil.h;@{{python_sha=(Get-FileHash D:/conda/python311.dll).Hash.ToLower();dbghelp_sha=(Get-FileHash C:/Windows/System32/dbghelp.dll).Hash.ToLower();observer_sha=(Get-FileHash target/release/ironjump-gil-waiter-first.exe).Hash.ToLower();active=@(Get-CimInstance Win32_Process|Where-Object {{$_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe'}}|Select-Object ProcessId,CommandLine)}}|ConvertTo-Json -Depth 5 -Compress",timeout=40))
    plan=dict(scope='One newly frozen waiter-first candidate. Original positive native oracle: two owner phases,20 samples each. One single-sample synthetic request-arrival barrier negative control. No application/human/device/USB/Run/optimization AB.',
              observer_path=REMOTE+'/target/release/ironjump-gil-waiter-first.exe',observer_sha256=build['exe_sha256'],oracle_dll_sha256=old['oracle_dll_sha256'],
              negative_oracle_path=REMOTE+'/negative_oracle.dll',negative_oracle_sha256=build['negative_dll_sha256'],python_dll_sha256=old['python_dll_sha256'],dbghelp_sha256=old['dbghelp_sha256'],
              count_per_phase=20,period_ms=50,settle_ms=200,free_running_count=16,free_running_ms=4,clock_uncertainty_ns_max=1000000,
              native_helpers=old['native_helpers'],symbol_search_path=old['symbol_search_path'],sources=sources,
              original_positive_plan_sha256=sha(ROOT/'experiments/gil_waiter_control/plan01.json'),original_pause_control_plan_sha256=sha(ROOT/'experiments/gil_pause_entry_control/plan01.json'),
              checks=['All40 positive first native contexts before global pause have exact PID/TID, unfiltered closed roots and independently matched GIL acquisition symbols. Preserve the original native request/acquire, owner-phase, empty waiter Python, both-root and lifetime controls.',
                      'Negative: request gate opens after first context capture while requested thread remains paused. Eight independent probes show requested/acquired0, gate1, owner/native heartbeats progress; first and global native contexts match and have no GIL acquisition chain.',
                      'All symbolication/result construction follows the capture window; native capture order, after-collection resolution, exact binary/source hashes and recovery validated.',
                      'Threadstate pointer endpoints do not certify continuous owner identity. No owner causal association, percent attribution or actual-load calibration promoted.',
                      'Every failed window, old threshold and lock remains; no resampling of failure.'],
              actual_load_disturbance_pass=False,natural_owner_association_qualified=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    w.transfer(HERE/'plan01.json',f'{w.HOST}:{REMOTE}/plan01.json')
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan01.json'),sources=len(sources),observer_sha256=build['exe_sha256'])))
