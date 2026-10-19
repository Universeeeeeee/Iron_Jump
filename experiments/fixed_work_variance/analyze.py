"""Every fixed pair retained; statistics withheld on work/boundary failure."""
import importlib.util
import json
import hashlib
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());plan=read(raw/'plan01.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    boundary=module('variance_process_boundary',HERE.parent/'fixed_work_accounting/counters.py');bundle=module('variance_work_identity',HERE.parent/'fixed_concurrent_work/verify.py');stats=module('variance_pilot_stats',HERE/'pilot_stats.py')
    status=read(raw/'runs/status.json');cases={};anchor=None;numeric={}
    for row in status['cases']:
        name=row['name'];value=read(raw/'runs'/name/'result.json');account=boundary.validate(value);identity=bundle.check_case(plan,value)
        current=(value['frame_evidence'],value['model_result_sha256'],value['report_sha256'])
        if anchor is None:anchor=current
        checks=dict(exit0=row['exit_code']==0,accounting=account['accounting_pass'],saved_accounting=account==value['process_accounting'],identity_and_overlap=identity['identity_and_overlap_pass'],same_complete_work=current==anchor)
        cases[name]=dict(checks=checks,case_pass=all(checks.values()),accounting=account,identity=identity)
        numeric[name]=dict(wall_ns=sum(account['wall_ns_bounds'])/2,cpu_ns=account['process_cpu_ns'],cycles=account['process_cycles'])
    qualified=status.get('complete',False) and not status['errors'] and list(cases)==plan['cases'] and all(x['case_pass'] for x in cases.values())
    pairs=[(numeric[a],numeric[b]) for a,b in plan['pairs']] if qualified else []
    result=dict(all_case_qualification_pass=qualified,cases=cases,status=status,numeric_endpoints=numeric,
                pilot_statistics=stats.describe(pairs) if qualified else None,
                statistics_withheld_reason=None if qualified else 'Incomplete or unqualified fixed cohort; no replacement/selection.',
                wall_log_ratio_bounds=[dict(cases=[a,b],lower=__import__('math').log(cases[b]['accounting']['wall_ns_bounds'][0]/cases[a]['accounting']['wall_ns_bounds'][1]),upper=__import__('math').log(cases[b]['accounting']['wall_ns_bounds'][1]/cases[a]['accounting']['wall_ns_bounds'][0])) for a,b in plan['pairs'] if a in cases and b in cases],
                primary_endpoint_scope=plan['statistics'],manifest_files_verified=len(manifest),
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ('all_case_qualification_pass','pilot_statistics','statistics_withheld_reason','manifest_files_verified')},indent=2))
