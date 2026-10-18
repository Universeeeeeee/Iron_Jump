"""Check every frozen deterministic waiter sample; keep failures and transitions."""
import argparse
import bisect
import json
from pathlib import Path,PureWindowsPath
import statistics
import sys
from control import read,sha


def pause_check(s):
    p,a,b,q=s['oracle_reads']
    return (s['qpc_begin']<=p['qpc_begin']<=p['qpc_end']<=s['suspended_qpc']<=a['qpc_begin']<=a['qpc_end']<=b['qpc_begin']<=b['qpc_end']<=s['resume_returned_qpc']<=s['qpc_end']<=q['qpc_begin']<=q['qpc_end']<=s['resolve_begin_qpc'] and a['values']==b['values'] and a['values'][3]>0 and p['values'][3]<=a['values'][3]<=q['values'][3])


def inspect(record,streams,plan,resolved,root):
    sys.path.insert(0,str(root/'experiments/native_stack_capture'));from align_clock import mapping
    clocks=[];joins=[];unknown=[];phase_checks=[];cost=[]
    oracle=[p for p in record['oracle'] if p[2]==p[6] and p[2]%2==0];starts=[p[0] for p in oracle];ends=[p[1] for p in oracle]
    modules={m['base']:m for m in resolved['modules']};addresses={a['address']:a for m in modules.values() for a in m['resolved']}
    def names(n):return [addresses.get(a['address'],{}).get('symbol') for a in n['frames']]
    def roots(n):return len(n['frames'])>=2 and names(n)[-2:]==['BaseThreadInitThunk','RtlUserThreadStart'] and all(addresses.get(a['address'],{}).get('pdb_matched') for a in n['frames'][-2:]) and [PureWindowsPath(modules[a['module_base']]['path']).name.lower() for a in n['frames'][-2:]]==['kernel32.dll','ntdll.dll']
    for phase in (1,2):
        group=record['phases'][str(phase)];rows=streams[str(phase)];samples=[s for s in rows if s['kind']=='sample']
        clock=mapping(group['anchors']+[t[k] for g in ('before','after') for t in group[g] for k in ('start','end')]);clocks.append(clock);f=clock['qpc_frequency'];lo,hi=clock['host_ns_offset_lower'],clock['host_ns_offset_upper']
        prior=rows[0]['qpc_end'];ordered=True;count=0
        for i,s in enumerate(samples):
            ordered &= s['ordinal']==i and s['pid']==record['ready']['pid'] and prior<=s['qpc_begin']<=s['qpc_end']<=s['resolve_begin_qpc']<=s['resolve_end_qpc'];prior=s['resolve_end_qpc']
            cost.append((s['qpc_end']-s['qpc_begin'])*1e6/f)
            b=s['qpc_begin']*10**9//f+lo;e=(s['qpc_end']*10**9+f-1)//f+hi
            assert group['external_begin_ns']<=b<=e<=group['external_end_ns']
            pre,post=bisect.bisect_right(ends,b)-1,bisect.bisect_left(starts,e)
            if pre<0 or post>=len(oracle):unknown.append([phase,i,'no full oracle bracket']);continue
            p,q=oracle[pre],oracle[post]
            if p[2]!=q[2] or p[3]!=phase or p[3:5]!=q[3:5] or p[7]!=q[7] or p[7]!=phase or not(p[8]<phase and q[8]<phase):unknown.append([phase,i,'transition or request not pending']);continue
            count+=1;expected=record['ready']['tids'][str(phase)];waiter=record['ready']['tids']['waiter']
            owners=[t for t in s['traces'] if t['owns_gil']];waiting_py=[t for t in s['traces'] if t['os_thread_id']==waiter];native={n['tid']:n for n in s['native']}
            owner=native.get(expected);waiting=native.get(waiter)
            identity=len(owners)==1 and owners[0]['os_thread_id']==expected==p[4] and owners[0]['pid']==record['ready']['pid'] and any(a['name']==('hold_a' if phase==1 else 'hold_b') for a in owners[0]['frames'])
            empty=len(waiting_py)==1 and waiting_py[0]['pid']==record['ready']['pid'] and not waiting_py[0]['owns_gil'] and not waiting_py[0]['frames']
            raw=len(native)==len(s['native'])==2 and owner is not None and waiting is not None and all(n['frames'] and n['context_ip']==n['frames'][0]['address'] and n['context_ip']>0 and 'frame cap' not in n['stopped_by'] for n in native.values())
            closed=raw and all(roots(n) for n in native.values())
            owner_path=raw and all(n in names(owner) for n in ('NtDelayExecution','SleepEx')) and any(modules.get(a['module_base'],{}).get('image_sha256')==plan['oracle_dll_sha256'] for a in owner['frames'])
            gil_path=raw and all(n in names(waiting) for n in ('take_gil','PyGILState_Ensure','NtWaitForSingleObject')) and 'pysleep' not in names(waiting) and all(addresses[a['address']]['pdb_matched'] for a in waiting['frames'] if addresses[a['address']]['symbol'] in ('take_gil','PyGILState_Ensure','NtWaitForSingleObject'))
            inner=s['oracle_reads'][1]['values'];independent=p[2:5]==inner[:3]==q[2:5] and p[5]<=inner[3]<=q[5]
            checks=dict(owner_python_identity=identity,waiter_native_empty_python=empty,raw_ips_preserved=raw,both_roots_closed=closed,owner_sleep_path=owner_path,waiter_GIL_acquisition_path=gil_path,external_pending_request_agrees=independent,pause_heartbeat_still=pause_check(s))
            joins.append(dict(phase=phase,ordinal=i,bracket_host_ns=[b,e],checks=checks,passed=all(checks.values())))
        counters=group['before'];after=group['after'];expected_ids={record['ready']['tids'][n] for n in (str(phase),'waiter','native_beat')}
        checks=dict(stream=len(samples)==plan['count_per_phase'] and len(rows)==len(samples)+2 and rows[0]['kind']=='init' and rows[0]['schema']==4 and rows[0]['error'] is None and rows[0]['synthetic_probe_enabled'] is True and rows[0]['pid']==record['ready']['pid'] and rows[0]['qpc_frequency']==f and rows[-1]['kind']=='complete' and rows[-1]['samples_written']==len(samples) and rows[-1]['pid']==record['ready']['pid'],ordered=ordered and prior<=rows[-1]['qpc'],clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],all_samples_independently_joined=count==plan['count_per_phase'],counter_identity=len(counters)==len(after)==3 and {t['tid'] for t in counters}==expected_ids and all(a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and a['pid']==record['ready']['pid'] and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')) for a,b in zip(counters,after)),waiter_acquired_after_owner_release=group['done']['phase']==group['done']['acquired']==phase and group['done']['host_ns']>group['external_end_ns'],clean=group['observer_returncode']==0,activity_not_used=rows[0]['activity_flags_valid'] is False and all(s['activity_flags_valid'] is False for s in samples))
        phase_checks.append(dict(phase=phase,checks=checks,passed=all(checks.values())))
    free=record['free_running_controls']
    checks=dict(both_phases=all(g['passed'] for g in phase_checks) and len(phase_checks)==2,every_join_matches=len(joins)==plan['count_per_phase']*2 and all(j['passed'] for j in joins),no_unknowns=not unknown,
        native_running_controls=len(free)==plan['free_running_count'] and all(a[1]<b[0] and a[5]<b[5] for a,b in free),
        native_oracle_monotone=all(a[2]<=b[2] and a[5]<=b[5] and (a[2]!=b[2] or a[3:5]==b[3:5]) for a,b in zip(oracle,oracle[1:])),
        symbols=all(not m['pdb_matched'] or (not m['pdb_unmatched'] and any(c['guid']==m['pdb_identity']['guid']==m['loaded_guid'] and c['age']==m['pdb_identity']['age']==m['loaded_age'] for c in m['codeview'])) for m in modules.values()) and all((a['symbol'] is None or a['pdb_matched']) and a['pdb_matched']==m['pdb_matched'] and a['module_base']==m['base'] and a['module_offset']==a['address']-m['base'] and 0<=a['module_offset']<m['image_size'] for m in modules.values() for a in m['resolved']),
        recovered=record['complete']['completed'] and record['complete']['pid']==record['ready']['pid'] and record['complete']['acquired']==2 and record['complete']['heartbeat']>oracle[-2][5],
        clean=record['capture_complete'] and record['target_returncode']==0 and not record['errors'] and not record['target_still_running'] and not record['observer_still_running'] and record['lock_retained'])
    return dict(checks=checks,deterministic_waiter_control_pass=all(checks.values()),phase_checks=phase_checks,joins=joins,unknown=unknown,clocks=clocks,full_read_us=dict(min=min(cost),median=statistics.median(cost),max=max(cost)),actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,scope='New independently frozen deterministic native GIL waiter; does not replace prior failures, infer scheduling states/time shares, or qualify actual workload.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items());plan=read(a.raw/'plan01.json');record=read(a.raw/'run01/record.json');assert record['plan_sha256']==sha(a.raw/'plan01.json') and all(sha(a.raw/n)==h for n,h in plan['sources'].items())
    joined=b''.join((a.raw/f'run01/phase{i}/samples.jsonl').read_bytes() for i in (1,2));assert joined==(a.raw/'all_samples.jsonl').read_bytes()
    resolved=read(a.raw/'symbols01.json');assert resolved['samples_sha256']==sha(a.raw/'all_samples.jsonl') and resolved['dbghelp_sha256']==plan['dbghelp_sha256'] and resolved['resolver_sha256']==plan['sources']['resolve_raw.py']
    assert sha(a.raw/'target/release/ironjump-gil-waiter-control.exe')==plan['observer_sha256'] and sha(a.raw/'WaiterOracle.dll')==plan['oracle_dll_sha256'] and not (a.raw/'run01/target.log').read_bytes() and all(not (a.raw/f'run01/phase{i}/observer.log').read_bytes() for i in (1,2))
    streams={str(i):[json.loads(l) for l in (a.raw/f'run01/phase{i}/samples.jsonl').read_text().splitlines()] for i in (1,2)}
    result=inspect(record,streams,plan,resolved,a.root)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='joins'},indent=2))
