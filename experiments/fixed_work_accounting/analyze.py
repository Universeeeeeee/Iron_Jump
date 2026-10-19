"""Recompute complete work identities and process-accounting boundary gates."""
import hashlib
import importlib.util
import json
from pathlib import Path
from counters import validate

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    spec=importlib.util.spec_from_file_location('fixed_bundle_verify',HERE.parent/'fixed_concurrent_work/verify.py');bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());plan=read(raw/'plan01.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    status=read(raw/'runs/status.json');assert status['complete'] and not status['errors'] and [x['name'] for x in status['cases']]==plan['cases']
    cases={n:read(raw/'runs'/n/'result.json') for n in plan['cases']};identity=bundle.compare(plan,*cases.values());accounts={n:validate(value) for n,value in cases.items()}
    assert all(cases[n]['process_accounting']==r for n,r in accounts.items())
    checks=dict(fixed_bundle_identity=identity['fixed_bundle_identity_pass'],both_process_boundaries=all(x['accounting_pass'] for x in accounts.values()),
                model_close_outside_consumer=identity['model_close_outside_consumer'],distinct_case_processes=len({v['process_before']['pid'] for v in cases.values()})==len(cases))
    result=dict(checks=checks,boundary_qualification_pass=all(checks.values()),bundle_identity=identity,accounts=accounts,
                process_counter_brackets={n:{k:v[k] for k in ('process_before','process_after','close_release_ns')} for n,v in cases.items()},
                manifest_files_verified=len(manifest),actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,
                limits=['Process CPU/cycles include model native thread pools; counters also include common record/wait bookkeeping.','No sampler or ETW enabled; one pair is not a variance estimate,3% equivalence or1% precision.','Whole-task accounting excludes model close but does not assert identical model overlap inside consumer-only ROI.','Controlled fixed work is not dynamic GUI/SDK/live sensor qualification.'])
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ('checks','boundary_qualification_pass','accounts','manifest_files_verified')},indent=2))
