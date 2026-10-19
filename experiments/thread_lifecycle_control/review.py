"""Validate actual short-lived synthetic threads against delivered lifecycle events."""
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from analyze import clock_residual_ms,PLAN
    sys.path.insert(0,str(ROOT/'experiments/thread_lifecycle_review'));from review import lifetimes
    plan=read(HERE/'plan01.json');f=read(HERE/'fixture01.json');m=read(HERE/'metadata01.json');record=read(HERE/'record01.json');status=read(HERE/'status01.json')
    assert all(sha(ROOT/n)==v for n,v in plan['sources'].items())
    assert f['complete'] and not f['errors'] and not f['workers_alive'] and f['handles_closed']
    assert status['complete'] and not status['errors'] and status['interval_before']==status['interval_after']
    assert record['cleanup_complete'] and record['stop_ok'] and 'failure' not in record
    assert m['target_pid']==f['pid'] and m['clock_type']==1 and m['qpc_frequency']==f['start']['frequency']
    assert all(m[k]==0 for k in ('header_events_lost','consumer_events_lost','buffers_lost'))
    forbidden=[k for k in m['shapes'] if k.startswith(('ce1dbfb4','def2fe46')) or (k.startswith('3d6fa8d1') and k.split('/')[1] in ('36','50'))]
    assert not forbidden,'Unexpected CPU/stack/CSwitch/ReadyThread event'
    anchors=[f['start'],f['end']]+[t[k]['clock'] for t in f['threads'] for k in ('before','after')]
    residual=clock_residual_ms(anchors,m['clock_samples'],m['qpc_frequency']);assert residual<=PLAN['gates']['clock_residual_ms_max']
    freq=m['qpc_frequency'];low=max(a['perf_before_ns']-a['qpc_after']*10**9//freq for a in anchors);high=min(a['perf_after_ns']-a['qpc_before']*10**9//freq for a in anchors);assert low<=high
    events=defaultdict(list)
    for line in (HERE/'events01.jsonl').open():
        e=json.loads(line)
        if e['provider']=='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' and e['opcode'] in (1,2,3,4):
            data=base64.b64decode(e['payload']);assert e['version']==3 and len(data)>=8
            pid,tid=struct.unpack_from('<II',data);assert pid==f['pid'];events[tid].append((e['qpc'],e['opcode']))
    life={tid:lifetimes(rows) for tid,rows in events.items()};checks=[]
    for t in f['threads']:
        a,b=t['before'],t['after'];tid=a['tid'];assert tid==b['tid'] and a['creation_100ns']==b['creation_100ns'] and t['blocks']>0 and t['joined']
        matches=[x for x in life[tid] if x['actual_creation'] and x['actual_exit'] and x['begin']<=a['clock']['qpc_before']<=b['clock']['qpc_after']<=x['end']];assert len(matches)==1
        x=matches[0];birth=[x['begin']*10**9//freq+low,x['begin']*10**9//freq+high];death=[x['end']*10**9//freq+low,x['end']*10**9//freq+high]
        assert f['enumeration_before']['after_ns']<=birth[0] and death[1]<=f['enumeration_after']['before_ns']
        assert tid not in f['enumeration_before']['tids'] and tid not in f['enumeration_after']['tids']
        checks.append(dict(ordinal=t['ordinal'],tid=tid,creation_100ns=a['creation_100ns'],actual_lifetime=x,entire_lifetime_inside_enumeration_gap=True,counter_window_enclosed=True,
            cpu_ms=(b['kernel_100ns']+b['user_100ns']-a['kernel_100ns']-a['user_100ns'])/10000,cycles=b['cycles']-a['cycles']))
    assert len(checks)==plan['thread_count']
    result=dict(all_known_short_lived_threads_observed=True,threads=checks,clock_max_residual_ms=residual,clock_gate_ms=PLAN['gates']['clock_residual_ms_max'],
        total_target_tids=len(life),known_short_lived_count=len(checks),all_target_lifetimes=life,
        loss={k:m[k] for k in ('header_events_lost','consumer_events_lost','buffers_lost')},sampling_interval_100ns=status['interval_after'],
        CPU_CSwitch_stacks_enabled=False,actual_load_disturbance_pass=False,start_address_field_qualified=False,primary_root_identified=False,
        limits=['Validated3 known short-lived threads, not arbitrary load/loss conditions or observed TID reuse.','Extra target threads have no independent fixture role; do not assign library ownership.','No CPU samples/CSwitch stacks; do not infer running/waiting shares from lifetime events.','Existing stack/3%/1% failures unchanged. New event collection requires its own real-workload perturbation calibration.'],
        sources={n:sha(HERE/n) for n in ['review.py','fixture01.json','record01.json','metadata01.json','events01.jsonl','plan01.json']})
    with (HERE/'review01.json').open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps(dict(known_threads=checks,clock_residual_ms=residual,total_target_tids=len(life)),indent=2))
