"""Cross-check historical lifecycle events; rundown is not creation or termination."""
import base64
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def lifetimes(events):
    active=None;out=[]
    for stamp,opcode in sorted(events):
        if opcode in (1,3):
            if active is not None:raise ValueError('Duplicate/open lifetime; no silent merge')
            active=dict(begin=stamp,actual_creation=opcode==1)
        elif opcode in (2,4):
            if active is None:raise ValueError('Unanchored end')
            out.append(dict(**active,end=stamp,actual_exit=opcode==2));active=None
        else:raise ValueError('Not a lifecycle opcode')
    if active is not None:out.append(dict(**active,end=None,actual_exit=False))
    return out

if __name__=='__main__':
    old=ROOT/'experiments/native_stack_capture';case=old/'runs/cpu_pair1_cpu';m=read(case/'decoded/metadata.json');f=read(case/'fixture/fixture.json');binding=read(old/'scan_manifest.json')['cases']['cpu_pair1_cpu']
    assert sha(case/'trace.etl')==binding['etl_sha256'] and sha(case/'decoded/events.jsonl')==binding['decoded_sha256']
    assert sha(case/'record.json')==binding['record_sha256']
    assert all(m[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost'))
    rows=[];group=defaultdict(list)
    for line in (case/'decoded/events.jsonl').open():
        e=json.loads(line)
        if e['provider']=='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' and e['opcode'] in (1,2,3,4):
            data=base64.b64decode(e['payload']);assert e['version']==3 and len(data)>=8
            pid,tid=struct.unpack_from('<II',data);assert pid==f['pid']==m['target_pid']
            rows.append(dict(opcode=e['opcode'],version=e['version'],pid=pid,tid=tid,payload_hex=data.hex(),qpc=e['qpc']));group[tid].append((e['qpc'],e['opcode']))
    independent=read(HERE/'tracerpt_selected03.json');keys=lambda rs:Counter((r['opcode'],r['version'],r['pid'],r['tid'],r['payload_hex']) for r in rs)
    assert keys(rows)==keys(independent['selected']) and len(rows)==16
    life={tid:lifetimes(events) for tid,events in group.items()};roles={}
    for role,t in f['threads'].items():
        tid=t['before']['tid'];assert tid==t['after']['tid'] and t['before']['creation_100ns']==t['after']['creation_100ns']
        spans=life[tid];assert len(spans)==1
        span=spans[0];begin=t['before']['clock']['qpc_before'];end=t['after']['clock']['qpc_after']
        assert span['actual_creation'] and span['actual_exit'] and span['begin']<=begin<=end<=span['end']
        roles[role]=dict(tid=tid,counter_window_enclosed=True,lifetime_qpc=span)
    result=dict(raw_events_and_payloads_exactly_match_tracerpt=True,event_count=len(rows),distinct_tids=len(life),named_role_checks=roles,
        all_lifetimes=life,loss={k:m[k] for k in ('header_events_lost','buffers_lost','consumer_events_lost')},
        named_start_address_decoded=False,tracerpt_schema_error=15005,whole_process_lifetime_calibration_complete=False,
        limits=['Raw cross-reader identity is validated; tracerpt did not resolve thread fields beyond raw bytes. Thread start address stays uninterpreted.',
                'Only four independently counter-observed historical roles are validated. Dedicated between-enumeration short-lived and TID-reuse controls remain missing.',
                'DCStart/DCStop are capture rundown, not actual creation/exit. Synthetic sequence tests enforce this distinction.',
                'Historical ETL cannot identify the three new TIDs in the later untraced fixed-model experiment; no retroactive attribution.',
                'Stack closure and observer-disturbance failures are unchanged; lifecycle event validation does not make those pass.'],
        sources={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),case/'trace.etl',case/'decoded/events.jsonl',case/'decoded/metadata.json',case/'fixture/fixture.json',HERE/'tracerpt_selected03.json']})
    with (HERE/'review01.json').open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps(dict(events=len(rows),tids=len(life),roles=roles),indent=2))
