"""Independent new wire checks beside all unchanged legacy workload gates."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('prior_finalization_verify',HERE.parent/'gil_workload_finalization/verify.py');previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
spec=importlib.util.spec_from_file_location('new_sdk_stream_link',HERE.parent/'gil_sdk_workload/link.py');wire=importlib.util.module_from_spec(spec);spec.loader.exec_module(wire)
read=previous.read;sha=previous.sha


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('reference',type=Path);p.add_argument('output',type=Path);p.add_argument('--case',required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    plan=read(a.raw/'plan01.json');assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    stage=a.raw/'runs'/a.case;record=read(stage/'record01.json');assert record['plan_sha256']==sha(a.raw/'plan01.json')
    capture=stage/'capture';initial=read(capture/'application_return.json');tail=read(capture/'workload_final.json');final=read(capture/'finalization.json')
    phases=previous.check_phases(initial,tail,final)
    assert tail['sources']=={n:plan['existing_sources']['experiments/gil_workload_finalization/'+n] for n in ('entry01.py','finalize.py')}
    m=previous.old.semantic_check(capture,a.reference);payload=copy.deepcopy(tail);payload['schema']=1
    legacy=previous.old.check_workload(payload,m,record)
    child=read(capture/'wire/child_0/receipts.json');parent=read(capture/'wire/parent.json')
    linked=wire.inspect(parent,child,tail,{n:plan['existing_sources'][n] for n in child['source_sha256']})
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from align_clock import mapping
    clock=mapping(tail['anchors']+record['anchors']+[x[k] for part in ('before','after') for x in record[part] for k in ('start','end')])
    terminal=record['terminal'];end=record['after']
    checks=dict(phases=all(phases.values()),legacy_workload_links=legacy['observability_pass'],native_clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],
                terminal_lifetimes=len(terminal)==len(end) and all(not b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')) for a,b in zip(end,terminal)),
                clean=not record['errors'] and record['target_returncode']==0 and not record['target_still_running'] and record.get('protocol_case_pass',False) and record['lock_retained'],
                wire_delivery=linked['wire_delivery_pass'],child_clock_precision=linked['child_clock'] is not None and 0<=linked['child_clock']['uncertainty_ns']<=plan['clock_uncertainty_ns_max'])
    result=dict(checks=checks,phase_checks=phases,legacy_workload=legacy,wire=linked,protocol_qualification_pass=all(checks.values()),native_clock=clock,
                application_return_model_confirmed=final['application_return_model_confirmed'],original_return_not_rewritten=True,
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,prior_failed_windows_still_failed=True,
                scope='One new full-input replay with independent pipe receipts and original SDK. Legacy relay/runtime equality remains a separate unchanged gate; receipt success does not upgrade it or qualify overhead.')
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('legacy_workload','phase_checks')},indent=2));raise SystemExit(not result['protocol_qualification_pass'])
