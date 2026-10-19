"""Conservative whole-interval PDH association; no frequency or causal conversion."""
import hashlib
import json
from pathlib import Path
import statistics
from verify import check,identity

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def phase(rows,begin,end,rules):
    selected=[]
    for previous,current in zip(rows,rows[1:]):
        if not begin<=previous['begin_ns']<=previous['end_ns']<current['begin_ns']<=current['end_ns']<=end:continue
        if current['end_ns']-previous['begin_ns']>rules['max_interval_ns']:continue
        if any(v['end_ns']-v['begin_ns']>rules['max_collection_bracket_ns'] for v in [previous,current]):continue
        if not all(v['valid'] for v in current['values'].values()):continue
        selected.append(current)
    return dict(valid_whole_intervals=len(selected),coverage_pass=len(selected)>=rules['min_whole_intervals_per_phase'],
        median_values={k:statistics.median(v['values'][k]['value'] for v in selected) if selected else None for k in ['performance_pct','busy_pct','queue']},
        ac_values=sorted(set(v['power']['ac'] for v in selected if v['power']['valid'])),
        ordinals=[v['ordinal'] for v in selected])

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');assert sha(raw/'plan01.json')==sha(HERE/'plan01.json')
    assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    status=read(raw/'runs/status.json');assert status['complete'] and not status['errors']
    cases={};reference=identity(read(raw/'reference01.json'));rules=plan['observation_rules']
    for name in plan['cases']:
        r=read(raw/'runs'/name/'result.json');assert check(plan,r)['pass_all'] and identity(r)==reference and r['opencv_threads']==8
        p,c,m=r['preparation'],r['consumer'],r['model'];assert m['ready_ns']<=p['begin_ns']<=p['end_ns']<=c['begin_ns']<=c['end_ns']
        rows=[json.loads(s) for s in (raw/'runs'/(name+'.system.jsonl')).read_text().splitlines()]
        assert [v['ordinal'] for v in rows]==list(range(len(rows)))
        ms=(p['end_ns']-p['begin_ns'])/1e6;state='fast' if ms<=rules['prepare_state_proxy_ms']['fast_max'] else 'slow' if ms>=rules['prepare_state_proxy_ms']['slow_min'] else 'intermediate'
        cases[name]=dict(preparation_wall_ms=ms,preparation_cpu_ms=p['thread_cpu_ns']/1e6,preparation_state=state,
            consumer_wall_ms=(c['end_ns']-c['begin_ns'])/1e6,consumer_cpu_ms=c['thread_cpu_ns']/1e6,
            preparation_system=phase(rows,p['begin_ns'],p['end_ns'],rules),consumer_system=phase(rows,c['begin_ns'],c['end_ns'],rules),
            model_tail_system=phase(rows,c['end_ns'],m['end_ns'],rules),model_call_median_ms=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in m['calls']),
            monitor_sample_count=len(rows),monitor_max_bracket_ms=max(v['end_ns']-v['begin_ns'] for v in rows)/1e6)
    states={v['preparation_state'] for v in cases.values()}
    result=dict(cases=cases,both_states_observed={'fast','slow'}<=states,causal_attribution=False,disturbance_qualified=False,field_fix_verified=False,
        limits=['PDH system aggregate performance relative to nominal is an OS counter, not direct GHz, temperature or throttle reason.',
                'System busy and queue do not identify external process responsibility or individual core/thread execution.',
                'All windows have the same uncalibrated observer. No old3%/1% pass or observer-free speed claim.',
                'One observed state cannot distinguish state-dependent mechanisms. No replacement windows.'],
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),analyzer_sha256=sha(Path(__file__))))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
