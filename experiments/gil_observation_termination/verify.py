"""Qualify only immutable-recorder and synthetic termination invariants."""
import hashlib
import json
from pathlib import Path

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
encoded=lambda v:json.dumps(v,sort_keys=True).encode()


def inspect(cases):
    checks={}
    old=cases['legacy_alias'];first=old['first_value_at_return'];after=old['first_snapshot']
    checks['legacy_alias_independently_reproduced']=(old['first_snapshot_changed'] and not first['rows']['model_close'] and bool(after['rows']['model_close']) and first['running_services']==after['running_services']==[0] and hashlib.sha256(encoded(first)).hexdigest()==old['first_serialized_sha_before'] and hashlib.sha256(encoded(after)).hexdigest()==old['first_serialized_sha_after'])
    for name,c in cases.items():
        a=c['native_before'];b=c['native_after'];blocked=c['blocked']['native']
        checks[name+'_native_lifetime']=(a['available'] and b['available'] and blocked['available'] and (a['pid'],a['tid'],a['creation_100ns'])==(blocked['pid'],blocked['tid'],blocked['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and a['exit_code']==blocked['exit_code']==259 and b['exit_code']==0 and all(b[k]>=a[k] for k in ('kernel_100ns','user_100ns','cycles')))
        checks[name+'_real_service_no_inputs']=(c['target_was_real_FootVisionService'] and c['no_inputs_submitted'] and c['used_original_default_stop_timeout'] and c['blocked']['service_running'] and c['blocked']['python_thread_alive'] and c['blocked']['close_enter_oracle'] and all(not c['second_snapshot']['rows'][k] for k in ('adapter_calls','inferences','service_submit_calls','sdk_events','relay_packets')))
        if name=='legacy_alias':continue
        initial=c['first_value_at_return'];final=c['second_snapshot']
        checks[name+'_immutable_snapshot']=(not c['first_snapshot_changed'] and c['first_serialized_sha_before']==c['first_serialized_sha_after'] and encoded(c['first_snapshot'])==encoded(initial) and initial['event_sequence']<final['event_sequence'])
        checks[name+'_initial_not_complete']=not all(initial['model_end_checks'].values()) and initial['model_end_checks']['service_exited'] is False
        checks[name+'_prefix_order']=initial['model_end_checks']['committed_prefix'] and final['model_end_checks']['committed_prefix'] and all(s['snapshot']['requested_ns']<=s['snapshot']['locked_begin_ns']<=s['snapshot']['locked_end_ns'] and all(s['snapshot']['locked_begin_ns']<=r['begin_ns']<=r['end_ns']<=s['snapshot']['locked_end_ns'] for r in s['service_liveness_reads']) for s in (initial,final))
        if name=='close_failure':
            checks[name+'_error_not_hidden']=final['model_end_checks']['service_exited'] and not final['model_end_checks']['close_return_confirmed'] and final['rows']['model_close'][0]['error']=='RuntimeError'
        else:checks[name+'_final_complete']=all(final['model_end_checks'].values())
        if name=='stopped_but_alive':
            s=c['listener_snapshot'];n=c['listener_native']
            checks['stopped_callback_not_exit']=s['model_end_checks']['service_markers'] and s['model_end_checks']['close_return_confirmed'] and not s['model_end_checks']['service_exited'] and n['exit_code']==259
    return dict(checks=checks,synthetic_termination_and_snapshot_controls_pass=all(checks.values()),
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False,
                limitations=['One controlled legacy alias reproduction and three frozen-recorder scenarios, no repeated actual replay or human/device inputs.',
                             'Production FootVisionService uses a Python-only fake adapter. This tests recorder/termination semantics, not the real MediaPipe close cause or native-pool teardown.',
                             'Event prefix is immutable; service liveness is separately bracketed, not a globally simultaneous native/OS snapshot.',
                             'New per-event copy/lock/sequence and close-entry hook have not undergone actual-load perturbation calibration. No replay/field entry deployed.',
                             'Failed workload windows01/02, prior plans, acceptance gates and locks remain unchanged.'])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    plan=read(a.raw/'synthetic_plan01.json');assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    status=read(a.raw/'runs/synthetic01/result01.json');assert status['complete'] and not status['errors'] and status['lock_retained']
    cases={name:read(a.raw/'runs/synthetic01'/file) for name,file in status['cases'].items()}
    result=inspect(cases);result['raw_manifest_sha256']=sha(a.raw/'manifest.json');result['plan_sha256']=sha(a.raw/'synthetic_plan01.json')
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(not result['synthetic_termination_and_snapshot_controls_pass'])
