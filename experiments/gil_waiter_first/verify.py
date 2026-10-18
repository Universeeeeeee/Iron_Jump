"""Version5: natural pre-global acquisition location; later owner stays unqualified."""
import bisect
import hashlib
import json
from pathlib import Path,PureWindowsPath
import sys

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def ordered(*v):return all(a<=b for a,b in zip(v,v[1:]))


def pause_order(s):
    p,a,b,q=s['oracle_reads']
    return (ordered(s['qpc_begin'],p['qpc_begin'],p['qpc_end'],s['requested_suspend_call_qpc'],s['suspended_qpc'],a['qpc_begin'],a['qpc_end'],b['qpc_begin'],b['qpc_end'],s['global_resume_returned_qpc'],s['resume_returned_qpc'],q['qpc_begin'],q['qpc_end'],s['collection_end_qpc']) and a['values']==b['values'] and p['values'][3]<=a['values'][3]<=q['values'][3])


def stream_checks(rows,count,test):
    samples=[s for s in rows if s['kind']=='sample']
    checks=dict(count=len(samples)==count and len(rows)==count+2,
                schema=rows[0]['kind']=='init' and rows[0]['schema']==5 and rows[0]['error'] is None and rows[0]['test_gate_enabled']==test,
                complete=rows[-1]['kind']=='complete' and rows[-1]['samples_written']==count,
                no_owner_promotion=rows[0]['natural_owner_association_qualified'] is False and all(s['natural_owner_association_qualified'] is False for s in samples),
                activity_not_used=rows[0]['activity_flags_valid'] is False and all(s['activity_flags_valid'] is False for s in samples))
    previous=rows[0]['qpc_end'];resolve_previous=0
    for i,s in enumerate(samples):
        checks[f'capture_order_{i}']=s['ordinal']==i and ordered(previous,s['qpc_begin'],s['requested_suspend_call_qpc'],s['requested_locked_qpc'],s['pre_context_begin_qpc'],s['pre_context_end_qpc'],s['global_suspend_call_qpc'],s['suspended_qpc'],s['global_resume_returned_qpc'],s['resume_returned_qpc'],s['qpc_end'],s['collection_end_qpc'],s['resolve_begin_qpc'],s['resolve_end_qpc'],rows[-1]['qpc'])
        checks[f'deferred_resolution_{i}']=all(t['qpc_end']<=s['collection_end_qpc'] for t in samples) and resolve_previous<=s['resolve_begin_qpc']
        previous=s['qpc_end'];resolve_previous=s['resolve_end_qpc']
    return checks


def native_checks(s,tid,catalog,expected_wait):
    modules={m['base']:m for m in catalog['modules']};addresses={a['address']:a for m in modules.values() for a in m['resolved']}
    native={n['tid']:n for n in s['native']};pre=s['pre_native'];post=native.get(tid)
    names=lambda n:[addresses.get(f['address'],{}).get('symbol') for f in n['frames']]
    def roots(n):
        return len(n['frames'])>=2 and names(n)[-2:]==['BaseThreadInitThunk','RtlUserThreadStart'] and all(addresses.get(f['address'],{}).get('pdb_matched') for f in n['frames'][-2:]) and [PureWindowsPath(modules[f['module_base']]['path']).name.lower() for f in n['frames'][-2:]]==['kernel32.dll','ntdll.dll']
    wanted=('NtWaitForSingleObject','take_gil','PyGILState_Ensure')
    gil=all(n in names(pre) for n in wanted) and all(addresses.get(f['address'],{}).get('pdb_matched') for f in pre['frames'] if addresses.get(f['address'],{}).get('symbol') in wanted)
    checks=dict(requested_identity=pre['tid']==tid and post is not None,
                unchanged_requested_context=post is not None and all(pre[k]==post[k] for k in ('context_ip','context_sp','context_bp')) and [f['address'] for f in pre['frames']]==[f['address'] for f in post['frames']],
                roots=roots(pre) and all(roots(n) for n in native.values()),
                raw_ips=len(native)==len(s['native']) and all(n['frames'] and n['context_ip']==n['frames'][0]['address'] and n['context_ip']>0 and 'frame cap' not in n['stopped_by'] for n in [pre,*native.values()]),
                acquisition_location=(gil and 'pysleep' not in names(pre)) if expected_wait else (not any(n in names(pre) for n in ('take_gil','PyGILState_Ensure')) and 'NtDelayExecution' in names(pre)),
                symbol_identities=all((not m['pdb_matched'] or (not m['pdb_unmatched'] and any(c['guid']==m['pdb_identity']['guid']==m['loaded_guid'] and c['age']==m['pdb_identity']['age']==m['loaded_age'] for c in m['codeview']))) and all((a['symbol'] is None or a['pdb_matched']) and a['pdb_matched']==m['pdb_matched'] and a['module_base']==m['base'] and a['module_offset']==a['address']-m['base'] and 0<=a['module_offset']<m['image_size'] for a in m['resolved']) for m in modules.values()))
    return dict(checks=checks,passed=all(checks.values()),pre_global_GIL_acquisition_chain=gil,pre_symbols=names(pre))


def counters(group,ready):
    a=group['before'];b=group['after']
    return len(a)==len(b)==3 and all(x['active'] and y['active'] and (x['pid'],x['tid'],x['creation_100ns'])==(y['pid'],y['tid'],y['creation_100ns']) and x['pid']==ready['pid'] and all(y[k]>=x[k] for k in ('user_100ns','kernel_100ns','cycles')) for x,y in zip(a,b))


def positive(root,plan,catalog,project):
    sys.path.insert(0,str(project/'experiments/native_stack_capture'));from align_clock import mapping
    record=read(root/'runs/positive01/record.json');checks={};proof=[];ready=record['ready']
    observations=[p for p in record['oracle'] if p[2]==p[6] and p[2]%2==0];starts=[p[0] for p in observations];ends=[p[1] for p in observations]
    for phase in (1,2):
        g=record['phases'][str(phase)];rows=[json.loads(l) for l in (root/f'runs/positive01/phase{phase}/samples.jsonl').read_text().splitlines()]
        checks.update({f'phase{phase}_{k}':v for k,v in stream_checks(rows,plan['count_per_phase'],False).items()})
        clock=mapping(g['anchors']+[t[k] for part in ('before','after') for t in g[part] for k in ('start','end')]);f=clock['qpc_frequency']
        checks[f'phase{phase}_clock']=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'] and f==rows[0]['qpc_frequency']
        checks[f'phase{phase}_counters']=counters(g,ready) and {t['tid'] for t in g['before']}=={ready['tids'][n] for n in (str(phase),'waiter','native_beat')}
        for s in rows[1:-1]:
            evidence=native_checks(s,ready['tids']['waiter'],catalog,True)
            b=s['qpc_begin']*10**9//f+clock['host_ns_offset_lower'];e=(s['qpc_end']*10**9+f-1)//f+clock['host_ns_offset_upper']
            i=bisect.bisect_right(ends,b)-1;j=bisect.bisect_left(starts,e)
            joined=False
            if i>=0 and j<len(observations):
                p,q=observations[i],observations[j];inner=s['oracle_reads'][1]['values']
                joined=(p[2]==q[2] and p[3]==q[3]==phase and p[4]==q[4]==ready['tids'][str(phase)] and p[7]==q[7]==phase and p[8]<phase and q[8]<phase and p[2:5]==inner[:3] and p[5]<=inner[3]<=q[5] and g['external_begin_ns']<=b<=e<=g['external_end_ns'])
            owner=[t for t in s['traces'] if t['owns_gil']];waiter=[t for t in s['traces'] if t['os_thread_id']==ready['tids']['waiter']]
            own=(len(owner)==1 and owner[0]['os_thread_id']==ready['tids'][str(phase)] and any(x['name']==('hold_a' if phase==1 else 'hold_b') for x in owner[0]['frames']))
            empty=len(waiter)==1 and not waiter[0]['frames'] and not waiter[0]['owns_gil']
            native={n['tid']:n for n in s['native']};modules={m['base']:m for m in catalog['modules']};resolved={a['address']:a for m in modules.values() for a in m['resolved']}
            holder=native.get(ready['tids'][str(phase)])
            holder_native=(set(native)=={ready['tids'][str(phase)],ready['tids']['waiter']} and holder is not None and
                           all(n in [resolved[f['address']]['symbol'] for f in holder['frames']] for n in ('NtDelayExecution','SleepEx')) and
                           any(modules[f['module_base']]['image_sha256']==plan['oracle_dll_sha256'] for f in holder['frames']))
            pause=pause_order(s)
            good=evidence['passed'] and joined and own and holder_native and empty and pause and s['pid']==ready['pid']
            proof.append(dict(phase=phase,ordinal=s['ordinal'],passed=good,pre_native=evidence,independent_pending_request=joined,owner_fixed_by_native_oracle=own,holder_native_path=holder_native,waiter_has_no_python_evaluation_frame=empty,pause_heartbeat_stable=pause))
        checks[f'phase{phase}_recover']=g['done']['phase']==g['done']['acquired']==phase and g['done']['host_ns']>g['external_end_ns'] and g['observer_returncode']==0
    free=record['free_running_controls']
    checks['free_running']=len(free)==plan['free_running_count'] and all(a[5]<b[5] for a,b in free)
    checks['all40']=len(proof)==40 and all(x['passed'] for x in proof)
    checks['clean']=not record['errors'] and record['capture_complete'] and record['target_returncode']==0 and not record['target_still_running'] and not record['observer_still_running'] and record['lock_retained'] and record['complete']['acquired']==2
    return dict(checks=checks,proof=proof,passed=all(checks.values()))


def negative(root,catalog):
    record=read(root/'runs/negative01/record.json');rows=[json.loads(l) for l in (root/'runs/negative01/samples.jsonl').read_text().splitlines()];s=rows[1];ready=record['ready']
    checks=stream_checks(rows,1,True);proof=native_checks(s,ready['tids']['waiter'],catalog,False)
    probes=record['oracle'];during=[p for p in probes if p['label']=='requester_frozen_others_running'];pre=next(p for p in probes if p['label']=='before_request')
    qb=lambda p:p['begin']['qpc_before'];qe=lambda p:p['end']['qpc_after']
    checks.update(native=proof['passed'],
        transition_order=ordered(s['pre_context_end_qpc'],record['pre_event_observed']['qpc_before'],qb(pre),qe(pre),record['gate_written']['qpc_before'],qb(during[0]),qe(during[-1]),record['global_go']['qpc_before'],s['global_suspend_call_qpc']),
        no_request_before=pre['values'][4:6]==[0,0] and pre['values'][8]==0,
        requester_frozen_with_request_ready=len(during)==8 and all(p['values'][4:6]==[0,0] and p['values'][8]==1 and p['values'][1:3]==[1,ready['tids']['owner']] and p['values'][0]==p['confirm'] for p in during),
        other_threads_run=during[-1]['values'][9]>during[0]['values'][9] and during[-1]['values'][3]>during[0]['values'][3],
        counters=counters(record,ready) and {t['tid'] for t in record['before']}==set(ready['tids'].values()),global_pause=pause_order(s),
        acquired_after_cleanup=record['complete']['state'][4:6]==[1,1] and record['complete']['state'][11]==1,
        clean=not record['errors'] and record['observer_returncode']==record['target_returncode']==0 and not record['observer_still_running'] and not record['target_still_running'] and record['lock_retained'])
    return dict(checks=checks,pre_native=proof,passed=all(checks.values()))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);p.add_argument('--project',type=Path,required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==v for n,v in manifest.items())
    plan=read(a.raw/'plan01.json');assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    assert b''.join((a.raw/f'runs/positive01/phase{i}/samples.jsonl').read_bytes() for i in (1,2))==(a.raw/'positive_samples01.jsonl').read_bytes()
    assert (a.raw/'runs/negative01/samples.jsonl').read_bytes()==(a.raw/'negative_samples01.jsonl').read_bytes()
    assert sha(a.raw/'positive_oracle.dll')==plan['oracle_dll_sha256'] and sha(a.raw/'negative_oracle.dll')==plan['negative_oracle_sha256']
    catalogs={}
    for name in ('positive','negative'):
        cat=read(a.raw/f'{name}_symbols01.json');assert cat['samples_sha256']==sha(a.raw/f'{name}_samples01.jsonl') and cat['resolver_sha256']==plan['sources']['resolve_raw.py'] and cat['dbghelp_sha256']==plan['dbghelp_sha256'];catalogs[name]=cat
    assert sha(a.raw/'target/release/ironjump-gil-waiter-first.exe')==plan['observer_sha256']
    for name in ('positive01','negative01'):
        r=read(a.raw/f'runs/{name}/record.json');assert r['plan_sha256']==sha(a.raw/'plan01.json')
    pos=positive(a.raw,plan,catalogs['positive'],a.project);neg=negative(a.raw,catalogs['negative'])
    result=dict(positive=pos,negative=neg,pre_global_wait_location_control_pass=pos['passed'] and neg['passed'],
                natural_owner_association_qualified=False,actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,
                limits=['A pre-global native acquisition chain is established only for the fixed native oracle. It is not a wait-time percentage or continuous wait-duration proof.',
                        'Current-tstate endpoint equality does not exclude intervening GIL release/reacquisition. Later owner frames are not certified as the original blocker.',
                        'Negative control deliberately waits at a named-event barrier while the requested thread is paused. Its latency is not a field overhead calibration.',
                        'ThreadLock resume failure panics; prior suspension counts are not emitted by remoteprocess0.5.2. No production entry has been deployed.'],
                raw_manifest_sha256=sha(a.raw/'manifest.json'),plan_sha256=sha(a.raw/'plan01.json'))
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(positive=pos['passed'],negative=neg['passed'],pre_global_wait_location_control_pass=result['pre_global_wait_location_control_pass'])));raise SystemExit(not result['pre_global_wait_location_control_pass'])
