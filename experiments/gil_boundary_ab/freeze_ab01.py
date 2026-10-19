"""Freeze4 balanced randomized pairs after the authorized full semantic gate."""
import hashlib
import json
from pathlib import Path
import random
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    semantic=read(HERE/'semantic_result01.json');assert semantic['complete'] and not semantic['errors'] and semantic['original_report_and_state_exact'] and semantic['helper_calls']>0
    prior=read(HERE.parent/'gil_sdk_workload/plan01.json');binding=read(HERE.parent/'gil_boundary_candidate/source_binding01.json');assert sha(HERE/'candidate.py')==binding['candidate_sha256']
    orders=['AB','AB','BA','BA'];random.Random(20261019).shuffle(orders);cases=[];pairs=[]
    for i,order in enumerate(orders,1):
        pair={v:f'pair{i:02d}_{v}' for v in ('original','candidate')};pairs.append(pair)
        for letter in order:
            variant='original' if letter=='A' else 'candidate';cases.append(dict(id=pair[variant],pair=i,variant=variant))
    plan=dict(scope='Authorized single-quality-equality intervention on saved Walk GUI replay. Original GUI/model/processor/filter and Python SDK runtime retained. Both arms use identical simulated native SDK; no device acquisition/human/Run, ETW or stack sampler.',
              cases=cases,pairs=pairs,random_seed=20261019,balanced_orders=orders,
              input_root=prior['input_root'],input_sha256=prior['input_sha256'],existing_sources=prior['existing_sources'],
              python_dll_sha256=prior['python_dll_sha256'],numpy_pyd_sha256=prior['numpy_pyd_sha256'],external_native_sha256=prior['external_native_sha256'],
              sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.ps1')},
              original_module_sha256=binding['original_module_sha256'],original_function_source_sha256=binding['original_function_source_sha256'],candidate_sha256=binding['candidate_sha256'],
              semantic_gate_sha256=sha(HERE/'semantic_result01.json'),authorization_sha256=sha(HERE/'authorization01.json'),
              primary_endpoints=['maximum source-touch-to-first-paint latency across all active contacts','nearest-rankP95 source-touch-to-first-paint latency across all active contacts'],
              secondary_endpoints=['continuous deque peak lower/upper bounds from both preserved witness families','per-contact raw trigger/FIFO/dequeue/publication/paint time bounds','actual video/inference/SDK/draw work and complete model close lifecycle'],
              baseline_reproduction=dict(observed_deque_at_least=1000,max_contact_latency_at_least_ms=1000,rule='Report per-original case; absence makes severe-backlog intervention evidence inconclusive, never triggers replacement.'),
              analysis=dict(independent_units=4,retain_every_case=True,no_optional_extension=True,no_posthoc_matching_or_normalization=True,
                            dynamic_work_policy='Keep original real-time frame selection and latest-only policy; actual workload differences are outcomes, not a posthoc exclusion gate.',
                            intervals='Descriptive paired log-ratio Student-t simultaneous95% intervals for2 latency endpoints; parametric assumptions stated, raw paired changes retained.',
                            root_limit='An effect in this simulated-SDK instrumented GUI protocol does not prove physical SDK/field effect, GIL share, or unique main cause.'),
              checks=['Candidate compiled in both arms before startup; only class method binding differs.',
                      'Original complete raw input/report/quality/state gates pass for every case, plus model finalization and simulated backend shutdown.',
                      'Any runtime/semantic/source failure retains window and aborts remaining cases; no rerun/replacement.',
                      'All old CPU/CSwitch and3%/1% qualification failures remain unchanged. Causal A/B is user-authorized but is not a relaxation of observer acceptance.'],
              actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (HERE/'ab_plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'ab_source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in plan['sources']:z.write(HERE/n,n)
        z.write(HERE/'ab_plan01.json','ab_plan01.json')
    sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
    remote='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_boundary_ab'
    command=f"if(Test-Path '{remote}/runs/ab01'){{throw 'Existing AB window'}};if(@(Get-Process python -ErrorAction SilentlyContinue).Count){{throw 'Existing target'}}"
    w.ssh(command);w.transfer(HERE/'ab_source01.zip',f'{w.HOST}:{remote}/ab_source01.zip')
    print(w.ssh(f"if((Get-FileHash '{remote}/ab_source01.zip').Hash.ToLower() -ne '{sha(HERE/'ab_source01.zip')}'){{throw 'Package mismatch'}};& D:/conda/python.exe -m zipfile -e '{remote}/ab_source01.zip' '{remote}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(json.dumps(dict(plan_sha256=sha(HERE/'ab_plan01.json'),orders=orders,cases=cases)))
