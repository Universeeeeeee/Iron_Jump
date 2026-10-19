"""All isolated-stage rows retained; no cross-scope summing or causal percentages."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def summarize(rows):
    assert rows and len({r['block'] for r in rows})==len(rows)
    assert all(r['wall_ns']>=0 and r['thread_cpu_ns']>=0 and r['operations']==sum(r['calls'].values()) for r in rows)
    groups={}
    for phase,values in (('preflight',[r for r in rows if r['block']<0]),('formal',[r for r in rows if r['block']>=0])):
        groups[phase]=dict(wall_ms=sum(r['wall_ns'] for r in values)/1e6,cpu_ms=sum(r['thread_cpu_ns'] for r in values)/1e6,operations=sum(r['operations'] for r in values),blocks=len(values),negative_wall_minus_cpu_blocks=[r['block'] for r in values if r['wall_ns']<r['thread_cpu_ns']])
    return groups

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());plan=read(HERE/'plan01.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items());status=read(raw/'runs/status.json');assert status['complete'] and not status['errors']
    cases={};identities={}
    for name,order in plan['cases'].items():
        value=read(raw/'runs'/name/'result.json');assert value['complete'] and not value['errors'] and value['original_stage_semantics_exact'] and value['order']==order
        cases[name]=dict(order=order,report_sha256=value['report_sha256'],stages={s:summarize(rows) for s,rows in value['stages'].items()},all_rows=value['stages'])
        identities[name]={s:[{k:r[k] for k in ('block','raw_first','raw_last','operations','calls')} for r in rows] for s,rows in value['stages'].items()}
    same=all(x==next(iter(identities.values())) for x in identities.values());assert same
    assert len({x['report_sha256'] for x in cases.values()})==1
    ranges={s:{metric:[min(c['stages'][s]['formal'][metric] for c in cases.values()),max(c['stages'][s]['formal'][metric] for c in cases.values())] for metric in ('wall_ms','cpu_ms')} for s in ('quality','filter','processor')}
    result=dict(cases=cases,same_stage_call_counts_and_boundaries=same,formal_ranges=ranges,manifest_files_verified=len(manifest),
                limits=['Three fixed rotating-order cases; not enough for equivalence or independent noise characterization.','Stage replay reads retained call tapes; it changes cache/allocation/GC and excludes some session work. Do not sum stage times as whole-chain time.','No per-frame timers; original1000-raw-input block timers retained. CPU quantization can yield negative wall-minus-CPU.','All rows and failed limits remain; no fastest-run or warmup selection.','New stage scope cannot explain oldcpu01..cpu04 or historical GUI GIL contribution.'],actual_load_disturbance_pass=False,primary_root_identified=False)
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(ranges,indent=2))
