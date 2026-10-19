"""GC callback intervals joined to retained same-run block endpoints."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def pair_events(gc):
    assert not gc['overflow'];pending={};out=[]
    for row in gc['rows']:
        wall,cpu,kind,generation,phase,tid,collected,uncollectable=row;key=(tid,generation)
        if kind==0:
            assert key not in pending;pending[key]=row
        else:
            assert kind==1 and key in pending;start=pending.pop(key);assert start[0]<=wall and start[1]<=cpu
            out.append(dict(begin_ns=start[0],end_ns=wall,wall_ns=wall-start[0],cpu_counter_delta_ns=cpu-start[1],generation=generation,start_phase=start[4],end_phase=phase,tid=tid,collected=collected,uncollectable=uncollectable))
    assert not pending
    return out

def overlap(block,event):return max(0,min(block['wall_end_ns'],event['end_ns'])-max(block['wall_begin_ns'],event['begin_ns']))

if __name__=='__main__':
    raw=HERE/'runs/evidence02';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());plan=read(HERE/'plan02.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items());status=read(raw/'runs/status.json');assert status['complete'] and not status['errors']
    cases={}
    for name,order in plan['cases'].items():
        r=read(raw/'runs'/name/'result.json');assert r['complete'] and not r['errors'] and r['original_stage_semantics_exact'];gc=pair_events(r['gc']);stages={}
        for stage,blocks in r['stages'].items():
            rows=[]
            for b in blocks:
                assert b['wall_end_ns']-b['wall_begin_ns']==b['wall_ns']
                matches=[dict(**e,overlap_ns=overlap(b,e)) for e in gc if overlap(b,e)]
                rows.append(dict(**b,GC_overlap_wall_ms=sum(x['overlap_ns'] for x in matches)/1e6,GC_events=matches))
            stages[stage]=rows
        cases[name]=dict(report_sha256=r['report_sha256'],stages=stages,all_GC_events=gc)
    assert len({r['report_sha256'] for r in cases.values()})==1
    largest=sorted([dict(case=n,stage=s,block=b['block'],raw_first=b['raw_first'],raw_last=b['raw_last'],wall_ms=b['wall_ns']/1e6,cpu_ms=b['thread_cpu_ns']/1e6,GC_overlap_wall_ms=b['GC_overlap_wall_ms'],GC_events=b['GC_events']) for n,c in cases.items() for s,rows in c['stages'].items() for b in rows if b['block']>=0],key=lambda x:x['GC_overlap_wall_ms'],reverse=True)[:12]
    result=dict(cases=cases,largest_GC_overlap_blocks=largest,manifest_files_verified=len(manifest),
                limits=['Same-run temporal overlap only; callback interval is not exclusive GC CPU time. Nested intervals must not be interpreted as additive exclusive costs.','No collections forced or GC policy changed. New callback and endpoint bookkeeping overhead unqualified.','This measured stage replay owns retained call tapes and result lists; GC behavior need not match original GUI/consumer.','Prior windows remain unchanged and cannot be retroactively assigned these new GC events.'],actual_load_disturbance_pass=False,primary_root_identified=False)
    with (HERE/'result02.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(largest[:5],indent=2))
