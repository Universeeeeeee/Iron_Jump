"""All delivered events, no rate/frequency inference or replacement capture."""
import base64
import collections
import hashlib
import json
from pathlib import Path
import struct

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def delta(a,b):
    assert len(a)==len(b)==3
    assert all(y>=x for x,y in zip(a,b)),'Counter regression/reset: no wrap guess'
    return [y-x for x,y in zip(a,b)]

if __name__=='__main__':
    root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest.items())
    assert sha(HERE/'runs/evidence01.zip')==read(HERE/'transport01.json')['sha256']
    metadata=read(HERE/'metadata04.json');events=[json.loads(x) for x in (HERE/'runs/events04.jsonl').read_text().splitlines()]
    assert metadata['qpc_frequency']==10_000_000 and metadata['clock_type']==1
    assert all(metadata[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost'))
    target=read(root/'target01.json');probe=read(root/'result01.json');capture=read(root/'capture01.json')
    assert capture['cleanup_confirmed'] and capture['stop_returncode']==0 and target['returncode']==0
    assert probe['complete'] and probe['memory_released'] and not probe['errors']
    assert target['tid']==target['before']['tid']==target['after']['tid']
    assert target['before']['creation_100ns']==target['after']['creation_100ns']
    thread_provider='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c';perf='ce1dbfb4-137e-4da6-87b0-3f59aa102cbc'
    expected=['InstructionRetired','UnhaltedCoreCycles','UnhaltedReferenceCycles'];sources=[];by=collections.defaultdict(list);lifecycle=[]
    for e in events:
        payload=base64.b64decode(e['payload'])
        if e['provider']==perf and e['opcode']==48:
            assert struct.unpack_from('<I',payload)[0]==3
            names=[v for v in payload[4:].decode('utf-16le').split('\0') if v];assert names==expected;sources.append(names)
        if e['provider']==thread_provider and e['opcode'] in (1,2,3,4) and len(payload)>=8:
            pid,tid=struct.unpack_from('<II',payload)
            if tid==target['tid']:assert pid==target['pid'];lifecycle.append(dict(opcode=e['opcode'],qpc=e['qpc'],pid=pid,tid=tid))
        if not e['pmc']:continue
        assert e['provider']==thread_provider and e['opcode']==36 and e['version']==5 and len(payload)==28
        assert len(e['pmc'])==1 and e['pmc'][0]['size']==24 and len(e['pmc'][0]['values'])==3
        by[e['cpu']].append(e)
    assert sources and lifecycle
    target_segments=[];switches=0
    for cpu,rows in by.items():
        for a,b in zip(rows,rows[1:]):
            new=struct.unpack_from('<I',base64.b64decode(a['payload']))[0]
            old=struct.unpack_from('<I',base64.b64decode(b['payload']),4)[0]
            assert a['qpc']<=b['qpc'] and new==old
            d=delta(a['pmc'][0]['values'],b['pmc'][0]['values']);switches+=1
            if new==target['tid']:target_segments.append(dict(cpu=cpu,begin_qpc=a['qpc'],end_qpc=b['qpc'],delta=d))
    # Bracket each perf timestamp using its anchor, without fitting to counters.
    anchor=target['clock_before'];scale=1e9/anchor['frequency']
    offset_low=anchor['perf_before_ns']-anchor['qpc_after']*scale
    offset_high=anchor['perf_after_ns']-anchor['qpc_before']*scale
    loops=[]
    for row in probe['rows']:
        assert row['result']==row['iterations']*16
        begin=(row['begin_ns']-offset_high)/scale;end=(row['end_ns']-offset_low)/scale
        contained=[s for s in target_segments if s['begin_qpc']>=begin and s['end_qpc']<=end]
        cover=[s for s in target_segments if s['end_qpc']>begin and s['begin_qpc']<end]
        loops.append(dict(iterations=row['iterations'],expected_native_retired_instructions=18*row['iterations']+2,
            contained_switch_intervals=len(contained),overlapping_switch_intervals=len(cover)))
    expected_work=sum(v['expected_native_retired_instructions'] for v in loops)
    first=(probe['rows'][0]['begin_ns']-offset_high)/scale;last=(probe['rows'][-1]['end_ns']-offset_low)/scale
    covering=[s for s in target_segments if s['begin_qpc']<=first and s['end_qpc']>=last]
    assert len(covering)==1 and covering[0]['delta'][0]>=expected_work
    out=dict(actual_three_counter_attachments_delivered=True,source_order=expected,attachments=sum(len(v) for v in by.values()),
        no_reported_loss=True,all_adjacent_per_CPU_thread_chains_match=True,adjacent_intervals_checked=switches,
        target_lifecycle=lifecycle,target_switch_intervals=len(target_segments),expected_six_loop_instructions=expected_work,
        combined_covering_interval=covering[0],per_loop_bounds=loops,
        per_loop_instruction_scaling_verified=False,hardware_attribution_ready=False,frequency_estimated=False,
        conclusion='Actual PMC delivery established, but no per-loop switch boundaries. Known-work scaling calibration remains incomplete; no slow-state hardware attribution.',
        limits=['Combined interval also contains Python/bookkeeping and edge work; excess instructions are not attributed to a function.',
            'Reference-counter units and architectural semantics require independent qualification; no GHz from ratios.',
            'Zero reported loss is not a full observer disturbance qualification.','One fixed control only; no GUI/model/field capture orreplacement trial.'],
        bindings={p.name:sha(p) for p in (Path(__file__),HERE/'metadata04.json',HERE/'runs/events04.jsonl',HERE/'capture_plan02.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
