"""One idle telemetry check; no retrospective subtraction from prior missing data."""
import base64
import collections
import hashlib
import json
from pathlib import Path
import struct
from intervals import union
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'capture_plan02.json');root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest.items()) and all(sha(HERE/n)==v for n,v in p['sources'].items())
    meta=read(root/'decoded01/metadata.json');target=read(root/'target01.json');capture=read(root/'capture01.json')
    assert capture['cleanup_confirmed'] and all(meta[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost')) and meta['clock_type']==1
    intervals=collections.defaultdict(list);threaded=[];shapes=collections.Counter()
    for line in (root/'decoded01/events.jsonl').read_text().splitlines():
        e=json.loads(line)
        if e['provider']!='ce1dbfb4-137e-4da6-87b0-3f59aa102cbc' or e['opcode'] not in (50,66,67,68,69):continue
        data=base64.b64decode(e['payload']);opcode=e['opcode'];length=20 if opcode in (50,67) else 16
        assert e['version']==2 and len(data)==length and e['flags']&0x40
        begin,routine=struct.unpack_from('<qQ',data);assert 0<=begin<=e['qpc'];assert 0<=e['cpu']<8
        shapes[(opcode,len(data))]+=1
        v=dict(cpu=e['cpu'],opcode=opcode,begin_qpc=begin,end_qpc=e['qpc'],routine_hex=hex(routine))
        if opcode==66:threaded.append(v)
        else:intervals[(e['cpu'],'ISR' if opcode in (50,67) else 'DPC')].append((begin,e['qpc']))
    lo=target['before']['after']['qpc_after'];hi=target['after']['before']['qpc_before'];freq=meta['qpc_frequency'];rows=[]
    for cpu,(a,b) in enumerate(zip(target['before']['rows'],target['after']['rows'])):
        record=dict(cpu=cpu,OS_interrupt_count_delta=(b['interrupt_count']-a['interrupt_count'])%2**32)
        for kind,key in [('DPC','DPC'),('ISR','interrupt')]:
            raw=intervals[(cpu,kind)];clipped=[(max(x,lo),min(y,hi)) for x,y in raw if y>lo and x<hi]
            qpc=sum(y-x for x,y in union(clipped));api=(b[key]-a[key])*100;assert api>=0
            record[kind]=dict(event_count=len(clipped),union_ns=qpc*1e9/freq,OS_counter_ns=api,scope_difference_ns=qpc*1e9/freq-api)
        rows.append(record)
    delivered=any(v['DPC']['event_count'] for v in rows) and any(v['ISR']['event_count'] for v in rows)
    # Coarse independent endpoint check only; zero/tick values do not certify fine accuracy.
    coarse=all(abs(v[kind]['scope_difference_ns'])<=p['coarse_CPU_tolerance_ns'] for v in rows for kind in ('DPC','ISR'))
    out=dict(actual_DPC_ISR_delivery=delivered,version2_schema_and_QPC_intervals_valid=True,no_reported_loss=True,
        shapes={str(k):v for k,v in shapes.items()},per_CPU=rows,threaded_DPC_events_kept_separate=len(threaded),coarse_OS_endpoint_check_pass=coarse,
        independent_counter_has_nonzero_time=any(v[k]['OS_counter_ns']>0 for v in rows for k in ('DPC','ISR')),
        root_mechanism_identified=False,old_83ms_gap_explained=False,prior_windows_repaired=False,
        limitations=['One idle window cannot explain historical 83ms mismatch orcalibrate actual workload disturbance.',
            'ThreadedDPC is scheduled thread work, not subtracted again.','Nested ISR/DPC uses union toavoid double counting.',
            'Endpoint OS counters are coarse; event counts andhardware interrupt count have different units forshared handlers.',
            'Routine addresses retained asaddresses; no invented kernel symbol names.'],
        bindings={v.name:sha(v) for v in (Path(__file__),HERE/'capture_plan02.json',HERE/'runs/evidence01.zip')})
    with (HERE/'result01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
