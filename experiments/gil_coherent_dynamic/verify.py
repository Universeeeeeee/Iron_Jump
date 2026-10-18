"""Recompute dynamic synthetic identity and native heartbeat delivery controls."""
import argparse
import bisect
import hashlib
import json
from pathlib import Path, PureWindowsPath
import statistics
import sys


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stats(v):return dict(min=min(v),median=statistics.median(v),max=max(v)) if v else None


def pause_check(s):
    p,a,b,q=s['oracle_reads']
    return (s['qpc_begin']<=p['qpc_begin']<=p['qpc_end']<=s['suspended_qpc']
        <=a['qpc_begin']<=a['qpc_end']<=b['qpc_begin']<=b['qpc_end']
        <=s['resume_returned_qpc']<=s['qpc_end']<=q['qpc_begin']<=q['qpc_end']<=s['resolve_begin_qpc']
        and a['values']==b['values'] and a['values'][3]>0
        and p['values'][3]<=a['values'][3]<=q['values'][3])


def inspect(record,rows,plan,resolved,root):
    sys.path.insert(0,str(root/'experiments/native_stack_capture'));from align_clock import mapping
    clock=mapping(record['anchors']+[t[k] for g in ('before','after') for t in record[g] for k in ('start','end')]);f=clock['qpc_frequency']
    lo,hi=clock['host_ns_offset_lower'],clock['host_ns_offset_upper']
    samples=[r for r in rows if r['kind']=='sample'];oracle=[p for p in record['oracle'] if p[2]==p[6] and p[2]%2==0]
    starts=[p[0] for p in oracle];ends=[p[1] for p in oracle]
    modules={m['base']:m for m in resolved['modules']};addresses={a['address']:a for m in modules.values() for a in m['resolved']}
    def names(n):return [addresses.get(a['address'],{}).get('symbol') for a in n['frames']]
    def closed(n):
        return len(n['frames'])>=2 and names(n)[-2:]==['BaseThreadInitThunk','RtlUserThreadStart'] and all(addresses.get(a['address'],{}).get('pdb_matched') for a in n['frames'][-2:]) and [PureWindowsPath(modules[a['module_base']]['path']).name.lower() for a in n['frames'][-2:]]==['kernel32.dll','ntdll.dll']
    joins=[];unknown=[];previous=rows[0]['qpc_end'];ordered=True
    for i,s in enumerate(samples):
        ordered &= s['ordinal']==i and s['pid']==record['ready']['pid'] and previous<=s['qpc_begin']<=s['qpc_end']<=s['resolve_begin_qpc']<=s['resolve_end_qpc'];previous=s['resolve_end_qpc']
        b=s['qpc_begin']*10**9//f+lo;e=(s['qpc_end']*10**9+f-1)//f+hi
        assert record['external_begin_ns']<=b<=e<=record['external_end_ns']
        pre,post=bisect.bisect_right(ends,b)-1,bisect.bisect_left(starts,e)
        if pre<0 or post>=len(oracle):unknown.append(dict(ordinal=i,reason='no full oracle bracket'));continue
        p,q=oracle[pre],oracle[post]
        if p[2]!=q[2] or p[3] not in (1,2) or p[3:5]!=q[3:5]:unknown.append(dict(ordinal=i,reason='transition or idle'));continue
        expected=record['ready']['tids'][str(p[3])];waiter=record['ready']['tids']['heartbeat']
        owners=[t for t in s['traces'] if t['owns_gil']];native={n['tid']:n for n in s['native']}
        owner=native.get(expected);waiting=native.get(waiter)
        identity=len(owners)==1 and owners[0]['os_thread_id']==expected==p[4] and owners[0]['pid']==record['ready']['pid'] and any(a['name']==('hold_a' if p[3]==1 else 'hold_b') for a in owners[0]['frames'])
        raw=len(native)==len(s['native'])==2 and owner is not None and waiting is not None and all(n['frames'] and n['context_ip']==n['frames'][0]['address'] and n['context_ip']>0 and 'frame cap' not in n['stopped_by'] for n in native.values())
        roots=raw and all(closed(n) for n in native.values())
        owner_path=raw and all(n in names(owner) for n in ('NtDelayExecution','SleepEx')) and any(modules.get(a['module_base'],{}).get('image_sha256')==plan['oracle_dll_sha256'] for a in owner['frames'])
        waiter_py=[t for t in s['traces'] if t['os_thread_id']==waiter]
        waiter_path=raw and len(waiter_py)==1 and not waiter_py[0]['owns_gil'] and any(a['name']=='heartbeat' for a in waiter_py[0]['frames']) and all(n in names(waiting) for n in ('take_gil','PyEval_RestoreThread','NtWaitForSingleObject'))
        inner=s['oracle_reads'][1]['values']
        independent=p[2:5]==inner[:3]==q[2:5] and p[5]<=inner[3]<=q[5]
        joins.append(dict(ordinal=i,phase=p[3],epoch=p[2],expected_tid=expected,full_read_bracket_ns=[b,e],owner_and_python_frame=identity,raw_contexts=raw,both_roots_closed=roots,owner_path=owner_path,waiter_path=waiter_path,external_oracle_agrees=independent,matches=identity and raw and roots and owner_path and waiter_path and independent))
    counts={str(p):sum(j['phase']==p for j in joins) for p in (1,2)}
    free=record['free_running_controls']
    checks=dict(stream_complete=len(samples)==plan['count'] and len(rows)==len(samples)+2 and rows[0]['kind']=='init' and rows[0]['schema']==3 and rows[0]['error'] is None and rows[0]['pid']==record['ready']['pid'] and rows[0]['qpc_frequency']==f and rows[-1]['kind']=='complete' and rows[-1]['pid']==record['ready']['pid'] and rows[-1]['samples_written']==len(samples),
        ordered=ordered and previous<=rows[-1]['qpc'],clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],
        running_negative_controls=len(free)==plan['free_running_count'] and all(a[1]<b[0] and a[5]<b[5] for a,b in free),
        inner_native_heartbeat_still=bool(samples) and all(pause_check(s) for s in samples),
        native_heartbeat_progress=bool(oracle) and all(a[5]<=b[5] for a,b in zip(oracle,oracle[1:])) and record['complete']['heartbeat']>oracle[-2][5]>oracle[0][5],
        oracle_epochs=all(a[2]<=b[2] and (a[2]!=b[2] or a[3:5]==b[3:5]) for a,b in zip(oracle,oracle[1:])),
        coverage=len(joins)>=plan['eligible_floor'] and all(n>=plan['per_holder_floor'] for n in counts.values()),every_eligible_matches=bool(joins) and all(j['matches'] for j in joins),
        symbol_identity=all(not m['pdb_matched'] or (not m['pdb_unmatched'] and any(c['guid']==m['pdb_identity']['guid']==m['loaded_guid'] and c['age']==m['pdb_identity']['age']==m['loaded_age'] for c in m['codeview'])) for m in modules.values()) and all((a['symbol'] is None or a['pdb_matched']) and a['pdb_matched']==m['pdb_matched'] and a['module_base']==m['base'] and a['module_offset']==a['address']-m['base'] and 0<=a['module_offset']<m['image_size'] for m in modules.values() for a in m['resolved']),
        native_lifetimes=len(record['before'])==len(record['after'])==4 and all(a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')) for a,b in zip(record['before'],record['after'])),
        recovered=record['complete']['completed'] and record['complete']['host_ns']>record['external_end_ns'],
        activity_not_interpreted=rows[0]['activity_flags_valid'] is False and all(s['activity_flags_valid'] is False for s in samples),
        clean=not record['errors'] and record['capture_complete'] and record['target_returncode']==record['observer_returncode']==0 and not record['target_still_running'] and not record['observer_still_running'])
    return dict(checks=checks,dynamic_synthetic_control_pass=all(checks.values()),samples=len(samples),eligible_counts=counts,unknown=unknown,joins=joins,clock=clock,
        full_read_us=stats([(s['qpc_end']-s['qpc_begin'])*1e6/f for s in samples]),inner_heartbeat_probe_interval_us=stats([(s['oracle_reads'][2]['qpc_begin']-s['oracle_reads'][1]['qpc_end'])*1e6/f for s in samples]),
        actual_start_gap_ms=stats([(b['qpc_begin']-a['qpc_begin'])*1e3/f for a,b in zip(samples,samples[1:])]),
        counter_deltas=[dict(tid=a['tid'],user_100ns=b['user_100ns']-a['user_100ns'],kernel_100ns=b['kernel_100ns']-a['kernel_100ns'],cycles=b['cycles']-a['cycles']) for a,b in zip(record['before'],record['after'])],
        actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,
        scope='One synthetic dynamic control. Heartbeat independently checks this native thread stopped across the measured inner interval; no all-thread scheduling states, GIL time shares, field owner identity or actual-load readiness inferred. Transition samples stay unknown.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--resolved',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items());plan=read(a.raw/'plan01.json');record=read(a.raw/'run01/record.json')
    assert record['plan_sha256']==sha(a.raw/'plan01.json') and all(sha(a.raw/n)==h for n,h in plan['sources'].items())
    assert sha(a.raw/'target/release/ironjump-gil-coherent-dynamic.exe')==plan['observer_sha256'] and sha(a.raw/'DynamicOracle.dll')==plan['oracle_dll_sha256'] and not (a.raw/'run01/observer.log').read_bytes() and not (a.raw/'run01/target.log').read_bytes()
    resolved=read(a.resolved);assert resolved['samples_sha256']==sha(a.raw/'run01/samples.jsonl')
    rows=[json.loads(s) for s in (a.raw/'run01/samples.jsonl').read_text().splitlines()];result=inspect(record,rows,plan,resolved,a.root)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='joins'},indent=2))
