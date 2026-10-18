"""Freeze one new metadata observation pair; never overwrite an existing experiment."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_workload_observation'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    old=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')
    paths=[p for p in HERE.iterdir() if p.suffix in ('.py','.ps1')]
    sources={p.name:sha(p) for p in paths}
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p.name)
    archive_sha=sha(HERE/'source01.zip')
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing metadata experiment'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{REMOTE}/source01.zip')
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/source01.zip').Hash.ToLower() -ne '{archive_sha}'){{throw 'Source mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source01.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}};& D:/conda/python.exe '{REMOTE}/preflight01.py';if($LASTEXITCODE){{throw 'Preflight failed'}}",timeout=90))
    w.transfer(f'{w.HOST}:{REMOTE}/preflight01.json',HERE/'preflight01.json')
    preflight=read(HERE/'preflight01.json');existing=dict(old['baseline_files']);existing.update(old['frozen_sources']);existing.update(old['dependencies'])
    plan=dict(scope='One prospectively fixed two-case OFF/OFF observability pair. Original saved optical/video replay, real SDK control child; no physical optical/camera acquisition, human, Run, stack sampler, ETW or optimization AB. Common old10Hz queue probe and new metadata hooks remain ON.',
              cases=['off_a','off_b'],input_root=old['input_root'],input_sha256=old['input_sha256'],offset_ns=12000000000,duration_ns=5000000000,lateness_ns_max=50000000,clock_uncertainty_ns_max=1000000,
              sources=sources,frozen_existing=existing,external_native_sha256=preflight['native_sha256'],python_dll_sha256=old['python_dll_sha256'],numpy_pyd_sha256=old['numpy_pyd_sha256'],
              checks=['Full serialized report/quality/runtime/filter/audit/archive state exact against the retained input oracle; only the preexisting checked-host-timestamp normalization is permitted.',
                      'Every actual adapter call joins one inference event and its service-submit metadata. Keep frame index, camera-clock epoch, VIDEO timestamp, wall begin/end, original worker TID and data shape/type. No pixel/pose-coordinate capture.',
                      'Every projected GUI relay occurrence joins one SDK pose-input occurrence and referenced inference. SDK counts match original measurement aggregates; native child PID stays separate.',
                      'Retained native handles/creation times and monotone GetThreadTimes/cycles cover inference thread in the unchanged12..17s ROI; target/controller QPC mapping<=1ms. Independently bound child clock with causal request/reply metadata, retaining all endpoints.',
                      'All outcomes retained; no repetitions replacing failures, no warm-up deletion, and no3%/1% equivalence certification from a single pair. New metadata overhead remains unqualified.'],
              old_stack_plan_sha256=sha(ROOT/'experiments/gil_gui_analysis/stack_plan01.json'),old_waiter_first_plan_sha256=sha(ROOT/'experiments/gil_waiter_first/plan01.json'),
              actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    w.transfer(HERE/'plan01.json',f'{w.HOST}:{REMOTE}/plan01.json')
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan01.json'),sources=len(sources),frozen_existing=len(existing))))
