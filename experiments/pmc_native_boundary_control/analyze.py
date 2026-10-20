"""Prespecified exact-work gates; count outer running intervals without subtraction."""
import base64
import collections
import hashlib
import json
from pathlib import Path
import struct
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def segments(events,tid):
    by=collections.defaultdict(list)
    for e in events:
        if e['pmc']:
            assert e['provider']=='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' and e['opcode']==36 and e['version']==5
            assert len(e['pmc'])==1 and e['pmc'][0]['size']==24
            by[e['cpu']].append(e)
    found=[]
    for cpu,rows in by.items():
        for a,b in zip(rows,rows[1:]):
            new=struct.unpack_from('<I',base64.b64decode(a['payload']))[0];old=struct.unpack_from('<I',base64.b64decode(b['payload']),4)[0]
            assert new==old and a['qpc']<=b['qpc']
            x=a['pmc'][0]['values'];y=b['pmc'][0]['values'];assert len(x)==len(y)==3 and all(v>=u for u,v in zip(x,y))
            if new==tid:found.append(dict(cpu=cpu,begin=a['qpc'],end=b['qpc'],values=[v-u for u,v in zip(x,y)]))
    return found

def bound(row,spans):
    lo=row['begin']['qpc_before'];hi=row['end']['qpc_after']
    hits=[s for s in spans if s['end']>lo and s['begin']<hi]
    assert hits and min(s['begin'] for s in hits)<=lo and max(s['end'] for s in hits)>=hi
    return dict(instructions=sum(s['values'][0] for s in hits),core_cycles=sum(s['values'][1] for s in hits),reference_counter=sum(s['values'][2] for s in hits),
        intervals=hits,running_qpc=sum(s['end']-s['begin'] for s in hits),marker_qpc=hi-lo)

if __name__=='__main__':
    p=read(HERE/'capture_plan02.json');root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest.items()) and all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert sha(HERE/'runs/evidence01.zip')==read(HERE/'transport01.json')['sha256']
    m=read(root/'decoded01/metadata.json');r=read(root/'target01.json');capture=read(root/'capture01.json')
    assert all(m[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost')) and m['clock_type']==1
    assert r['frequency']==m['qpc_frequency']
    assert r['complete'] and r['memory_released'] and not r['errors'] and capture['cleanup_confirmed']
    assert [v['iterations'] for v in r['rows']]==p['iterations']
    events=[json.loads(x) for x in (root/'decoded01/events.jsonl').read_text().splitlines()]
    names=[];lifecycle=[]
    for e in events:
        data=base64.b64decode(e['payload'])
        if e['provider']=='ce1dbfb4-137e-4da6-87b0-3f59aa102cbc' and e['opcode']==48:
            assert struct.unpack_from('<I',data)[0]==3;names.append([v for v in data[4:].decode('utf-16le').split('\0') if v])
        if e['provider']=='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' and e['opcode'] in (1,2,3,4) and len(data)>=8:
            pid,tid=struct.unpack_from('<II',data)
            if tid==r['tid']:assert pid==r['pid'];lifecycle.append(e['opcode'])
    assert names and all(v==p['counter_order'] for v in names) and 1 in lifecycle and 2 in lifecycle
    spans=segments(events,r['tid']);rows=[];used=[]
    for v in r['rows']:
        assert v['before']['tid']==v['after']['tid']==r['tid'] and v['value']==v['iterations']*16
        assert v['before']['creation_100ns']==v['after']['creation_100ns']
        b=bound(v,spans);keys={(s['cpu'],s['begin'],s['end']) for s in b['intervals']}
        assert not any(keys&prior for prior in used),'Two blocks share a CSwitch interval; boundaries failed'
        used.append(keys);expected=18*v['iterations']+2;ratio=b['instructions']/expected
        cpu=(v['after']['kernel_100ns']+v['after']['user_100ns']-v['before']['kernel_100ns']-v['before']['user_100ns'])/1e4
        rows.append(dict(ordinal=v['ordinal'],iterations=v['iterations'],expected_instructions=expected,observed=b,
            ratio=ratio,thread_cpu_ms=cpu,running_ms=b['running_qpc']/m['qpc_frequency']*1000))
    active=[v for v in rows if v['iterations']>1];blank=[v for v in rows if v['iterations']==1]
    exact=all(p['instruction_ratio'][0]<=v['ratio']<=p['instruction_ratio'][1] for v in active)
    blank_ok=max(v['observed']['instructions'] for v in blank)<=min(v['expected_instructions'] for v in active)*p['blank_max_fraction']
    accounting=all(abs(v['thread_cpu_ms']-v['running_ms'])<=p['accounting_tolerance_ms'] for v in active)
    out=dict(all_blocks_have_disjoint_running_boundaries=True,no_reported_loss=True,counter_source_order_verified=True,rows=rows,
        instruction_scaling_pass=exact,blank_control_pass=blank_ok,OS_accounting_crosscheck_pass=accounting,
        known_work_boundary_calibration_pass=exact and blank_ok and accounting,frequency_semantics_verified=False,
        actual_workload_disturbance_qualified=False,root_mechanism_identified=False,
        limitations=['Bounds include marker and switch overhead; no blank subtraction orfit.','Clock ratios are notGHz; core/reference semantics not separately qualified.',
            'One synthetic delivery/calibration process, not independent performance trials orGUI attribution.','Old failures andwindows retained.'],
        bindings={v.name:sha(v) for v in (Path(__file__),HERE/'capture_plan02.json',HERE/'runs/evidence01.zip')})
    with (HERE/'result01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
