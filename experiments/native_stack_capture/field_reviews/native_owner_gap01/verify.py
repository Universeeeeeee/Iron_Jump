"""Recheck a synthetic native-only GIL owner, preserving original field rejection."""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import sys


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(record,rows,plan):
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'))
    from align_clock import mapping
    sys.path.insert(0,str(ROOT/'experiments/gil_timestamped'))
    from field import protocol
    clock=mapping(record['anchors']+[t[k] for g in ('before','after') for t in record[g] for k in ('start','end')])
    f=clock['qpc_frequency'];lo=clock['host_ns_offset_lower'];hi=clock['host_ns_offset_upper']
    samples=[s for s in rows if s['kind']=='sample'];oracle=[p for p in record['oracle'] if p[2]==p[6] and p[2]%2==0]
    starts=[p[0] for p in oracle];ends=[p[1] for p in oracle];joins=[];unknown=[]
    for i,s in enumerate(samples):
        assert s['ordinal']==i and s['pid']==record['ready']['pid']
        b=s['qpc_begin']*10**9//f+lo;e=(s['qpc_end']*10**9+f-1)//f+hi
        assert b<=e and record['external_begin_ns']<=b<=e<=record['external_end_ns']
        before=bisect.bisect_right(ends,b)-1;after=bisect.bisect_left(starts,e)
        if before<0 or after>=len(oracle):unknown.append(i);continue
        p,q=oracle[before],oracle[after]
        if p[2]!=q[2] or p[3]!=1 or p[3:5]!=q[3:5]:unknown.append(i);continue
        owners=[t for t in s['traces'] if t['owns_gil']]
        match=len(owners)==1 and owners[0]['pid']==record['ready']['pid'] and owners[0]['os_thread_id']==record['ready']['tids']['native']==p[4] and owners[0]['frames']==[]
        joins.append(dict(ordinal=i,bracket_host_ns=[b,e],oracle_before=p,oracle_after=q,matches_native_owner_without_python_frame=match))
    held=[p for p in oracle if p[3]==1]
    checks=dict(complete=len(samples)==plan['count'] and len(rows)==len(samples)+2 and rows[0]['kind']=='init' and rows[0]['schema']==1 and rows[0]['error'] is None and rows[0]['pid']==record['ready']['pid'] and rows[0]['qpc_frequency']==f and rows[-1]['kind']=='complete' and rows[-1]['pid']==record['ready']['pid'] and rows[-1]['samples_written']==plan['count'],
        ordered=rows[0]['qpc_end']<=samples[0]['qpc_begin'] and all(a['qpc_begin']<=a['qpc_end']<=b['qpc_begin'] for a,b in zip(samples,samples[1:])) and samples[-1]['qpc_end']<=rows[-1]['qpc'],
        eligible_floor=len(joins)>=plan['eligible_floor'],all_eligible_match=bool(joins) and all(j['matches_native_owner_without_python_frame'] for j in joins),
        clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],
        fixture_lifetime_margins=bool(joins) and oracle[next(i for i,p in enumerate(oracle) if p[3]==1)][1]+plan['phase_margin_ns']<joins[0]['bracket_host_ns'][0] and joins[-1]['bracket_host_ns'][1]<record['complete']['host_ns']-plan['phase_margin_ns'],
        monotone_oracle=all(p[2]<=q[2] and p[5]<=q[5] for p,q in zip(oracle,oracle[1:])),
        same_epoch_coherent=all(p[2]!=q[2] or p[3:5]==q[3:5] for p,q in zip(oracle,oracle[1:])),
        held_heartbeat_still=bool(held) and len({p[5] for p in held})==1,
        recovered=record['complete']['completed'] and record['complete']['heartbeat']>held[-1][5] and record['complete']['host_ns']>record['external_end_ns'],
        native_lifetime=all(a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) for a,b in zip(record['before'],record['after'])),
        clean=not record['errors'] and record['target_returncode']==record['observer_returncode']==0 and not record['target_still_running'] and not record['observer_still_running'],
        original_field_protocol_still_rejects=not protocol(rows,record['ready']['pid'],plan['count']))
    return dict(checks=checks,native_only_counterexample_pass=all(checks.values()),samples=len(samples),eligible=len(joins),unknown=unknown,joins=joins,clock=clock,field_attribution_ready=False,actual_load_disturbance_pass=False,limits=['A new controlled counterexample, never a replacement repeat of the failed field window.','Proves this exact binary can report a correct native GIL owner with no Python frame. Does not identify the native function of field TID3816.','No accepted field subset, native unwind, time shares, dominant cause or threshold change.'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();ROOT=a.root
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n.replace('\\','/'))==v for n,v in manifest.items())
    plan=read(a.raw/'plan01.json');record=read(a.raw/'run01/record.json');assert sha(a.raw/'plan01.json')==record['plan_sha256'] and sha(a.raw/'NativeOwner.dll')==plan['oracle_dll_sha256']
    assert all(sha(a.raw/n)==v for n,v in plan['sources'].items())
    rows=[json.loads(s) for s in (a.raw/'run01/samples.jsonl').read_text().splitlines()]
    assert not (a.raw/'run01/observer.log').read_bytes()
    result=inspect(record,rows,plan)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='joins'},indent=2))
