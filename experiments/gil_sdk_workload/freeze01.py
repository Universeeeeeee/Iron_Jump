"""One prospectively frozen real SDK receipt replay, no replacement attempts."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_sdk_workload'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    previous=ROOT/'experiments/gil_workload_finalization';old=read(previous/'plan01.json');existing=dict(old['existing_sources'])
    existing.update({'experiments/gil_workload_finalization/'+n:v for n,v in old['sources'].items()})
    for n in ('experiments/gil_sdk_entry/entry.py','experiments/gil_wire_receipts/receipts.py'):existing[n]=sha(ROOT/n)
    assert sha(HERE/'sdk_child.py')==existing['experiments/gil_sdk_entry/entry.py']
    remote_only=[n for n in existing if not (ROOT/n).is_file()]
    assert all(sha(ROOT/n)==v for n,v in existing.items() if n not in remote_only)
    plan={k:old[k] for k in ('input_root','input_sha256','offset_ns','duration_ns','lateness_ns_max','clock_uncertainty_ns_max','python_dll_sha256','numpy_pyd_sha256','external_native_sha256','old_failed_metadata_plan_sha256')}
    plan.update(scope='One new full saved optical/video Walk replay with original real SDK child and exact qualified diagnostic entry. No human, optical/camera acquisition, Run, ETW, stack sampling or optimization AB. Observer disturbance remains unqualified.',
                sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.ps1')},existing_sources=existing,remote_only_dependencies_must_verify_before_start=remote_only,
                previous_protocol_plan_sha256=sha(previous/'plan01.json'),previous_protocol_result_sha256=sha(previous/'result01.json'),previous_qualification_remains_failed=not read(previous/'result01.json')['protocol_qualification_pass'],
                exact_sdk_entry_source_sha256=sha(HERE/'sdk_child.py'),observer_tail_deadline_s=90,cases=['protocol01'],no_retry_or_replacement=True,
                checks=['Keep original full input, report, processing state, inference policy, queue, thread structure, NumPy and painter unchanged; unchanged12..17s ROI/lateness/clock gates.',
                        'Parent original QProcess write bytes/return preserve every accepted chunk; independent child preparse text ordinal reconstructs full ASCII LF stream with no wire IDs.',
                        'Original imported serve/runtime/mailbox body preserved. Child local sequence links runtime and nested submit calls; mailbox return does not assert business acceptance.',
                        'SDK PID from actual QProcess start must match child receipt, native parent relationship, exact diagnostic command/output path and both loaded SDK images; GUI and SDK handles remain separate.',
                        'New full delivery and causal clock checks are separate from unchanged legacy all-relay/runtime equality and all other original gates; any failed gate remains failed.',
                        'Preserve original application-return snapshot before bounded90s observer tail, all late model-close events, terminal native thread handles and every lock/failure.',
                        'One independent feasibility window, not OFF/OFF variance, OFF/ON overhead,3%/1% equivalence or root attribution. No resampling to replace this result.'],
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in plan['sources']:z.write(HERE/n,n)
        z.write(HERE/'plan01.json','plan01.json')
    package=sha(HERE/'source01.zip')
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing receipt workload'}};if(@(Get-CimInstance Win32_Process|Where-Object {{$_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe'}}).Count){{throw 'Existing target; no start'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{REMOTE}/source01.zip')
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/source01.zip').Hash.ToLower() -ne '{package}'){{throw 'Package mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source01.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan01.json'),source_archive_sha256=package)))
