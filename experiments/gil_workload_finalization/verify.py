"""New two-phase format. Old failed01/02 snapshots are never reclassified."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE));from finalize import prefix_equal
sys.path.insert(0,str(HERE.parent/'gil_observation_termination'));from snapshot import model_end_checks
spec=importlib.util.spec_from_file_location('old_workload_checks',HERE.parent/'gil_workload_observation/verify.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
read=old.read;sha=old.sha


def check_phases(initial,tail,result):
    first=initial['snapshot']
    return dict(schema=first['schema']==tail['schema']==2,
                app_outcome_preserved=initial['application_outcome']['success'] is True,
                original_state_preserved=result['application_return_model_checks']==model_end_checks(first) and first['model_end_checks']==model_end_checks(first),
                final_state_recomputed=tail['model_end_checks']==model_end_checks(tail)==result['observer_tail_model_checks'],
                prefix_unchanged=prefix_equal(first,tail),
                final_model_complete=all(model_end_checks(tail).values()),
                no_join_timeout=all(j['alive_after'] is not True for j in result['joins']),
                finalization=result['metadata_finalization_pass'] is True and all(result['checks'].values()))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('reference',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    plan=read(a.raw/'plan01.json');assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    stage=a.raw/'runs/protocol01';record=read(stage/'record01.json');assert record['plan_sha256']==sha(a.raw/'plan01.json')
    initial=read(stage/'capture/application_return.json');tail=read(stage/'capture/workload_final.json');final=read(stage/'capture/finalization.json')
    assert tail['sources']=={n:plan['sources'][n] for n in ('entry01.py','finalize.py')}
    phases=check_phases(initial,tail,final)
    m=old.semantic_check(stage/'capture',a.reference)
    # Validated schema2 -> legacy field reader projection only. No timestamp,
    # row, error, closure or numeric tolerance is changed by this adapter.
    payload=copy.deepcopy(tail);payload['schema']=1
    data=old.check_workload(payload,m,record)
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from align_clock import mapping
    clock=mapping(tail['anchors']+record['anchors']+[x[k] for part in ('before','after') for x in record[part] for k in ('start','end')])
    terminal=record['terminal'];end=record['after']
    checks=dict(phases=all(phases.values()),saved_workload_links=data['observability_pass'],native_clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],
                terminal_lifetimes=len(terminal)==len(end) and all(not b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')) for a,b in zip(end,terminal)),
                clean=not record['errors'] and record['target_returncode']==0 and not record['target_still_running'] and record['protocol_case_pass'] and record['lock_retained'])
    result=dict(checks=checks,phase_checks=phases,workload=data,protocol_qualification_pass=all(checks.values()),native_clock=clock,
                application_return_model_confirmed=final['application_return_model_confirmed'],original_return_not_rewritten=True,
                queue_observed_max_sampled=max(x[3] for x in m['queue_samples']),queue_observed_max_common=max(x[3] for x in m['queue_common']),
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,
                scope='One independently frozen protocol qualification case, not A/A variance or an overhead/optimization comparison. Final metadata includes observer-only tail. Original-return unconfirmed state stays in its own snapshot.',
                prior_failed_windows_still_failed=True)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='workload'},indent=2));raise SystemExit(not result['protocol_qualification_pass'])
