"""Frozen joint native-throughput/complete-work decision, every pair retained."""
import hashlib
import json
import math
from pathlib import Path
import statistics
from verify import check,identity

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def compare(pairs,criteria):
    if len(pairs)!=4:raise ValueError('All four pairs required')
    ratios=[b['consumer_wall_ms']/a['consumer_wall_ms'] for a,b in pairs]
    native=[b['native_billion_adds_per_second']/a['native_billion_adds_per_second'] for a,b in pairs]
    whole=[b['whole_wall_ms']/a['whole_wall_ms'] for a,b in pairs]
    if any(x<=0 for x in ratios+native+whole):raise ValueError('Positive endpoints required')
    logs=[math.log(x) for x in ratios];gain=-math.expm1(statistics.mean(logs))
    ngain=math.expm1(statistics.mean(math.log(x) for x in native));regression=math.expm1(statistics.mean(math.log(x) for x in whole))
    slow=sum(a['preparation_wall_ms']>=criteria['slow_preparation_wall_ms_min'] for a,b in pairs)
    # Fixed df3 Student-t critical value; descriptive interval, no qualification claim.
    half=3.182446305284263*statistics.stdev(logs)/2
    gates=dict(all_pairs_consumer_improve=all(x<1 for x in ratios),consumer_gain=gain>=criteria['minimum_geometric_consumer_reduction'],native_gain=ngain>=criteria['minimum_geometric_native_throughput_gain'],whole_work=regression<=criteria['maximum_geometric_whole_work_regression'],slow_baselines=slow>=criteria['minimum_slow_default_windows'])
    return dict(consumer_pair_changes=[x-1 for x in ratios],native_pair_changes=[x-1 for x in native],geometric_consumer_reduction=gain,geometric_native_throughput_gain=ngain,geometric_whole_work_change=regression,slow_default_windows=slow,descriptive_95pct_consumer_reduction_interval=[-math.expm1(statistics.mean(logs)+half),-math.expm1(statistics.mean(logs)-half)],gates=gates,advance=all(gates.values()))

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');assert sha(raw/'plan01.json')==sha(HERE/'plan01.json')
    assert all(sha(raw/n)==v for n,v in plan['sources'].items());status=read(raw/'runs/status.json');cases={};reference=identity(read(raw/'reference01.json'))
    for name in plan['cases']:
        path=raw/'runs'/name/'result.json'
        if not path.exists():cases[name]=dict(missing=True);continue
        r=read(path)
        if not r.get('complete') or r['errors'] or r['worker_alive']:cases[name]=dict(failed=True);continue
        assert check(plan,r)['pass_all'] and identity(r)==reference and r['opencv_threads']==8
        q=read(raw/'runs'/(name+'_qos.json'));cfg=q['configuration'];before=cfg['before'];expected=dict(before)
        assert before['version']==1 and before['control_mask']&1==before['state_mask']&1==0
        if plan['qos_variants'][name]=='optout':expected['control_mask']|=1
        assert not q['errors'] and q['returncode']==0 and cfg['variant']==plan['qos_variants'][name] and cfg['after']==q['at_end']==expected
        native=read(raw/'runs'/(name+'_native')/'result01.json');rows=native['rows']
        assert native['complete'] and native['memory_released'] and not native['errors']
        assert [v['iterations'] for v in rows]==plan['native_iterations'] and all(v['result']==v['dependent_adds']==v['iterations']*16 and v['end_ns']>v['begin_ns'] for v in rows)
        ratios=[]
        for a,b in zip(rows[::2],rows[1::2]):
            small,large=sorted([a,b],key=lambda v:v['iterations']);ratios.append((large['end_ns']-large['begin_ns'])/(small['end_ns']-small['begin_ns']))
        p,c,m=r['preparation'],r['consumer'],r['model'];assert p['frames']==42237 and m['ready_ns']<=p['begin_ns']<=p['end_ns']<=c['begin_ns']
        bounds=r['process_accounting']['wall_ns_bounds']
        cases[name]=dict(qualified=True,native_scaling_pass=all(3.2<=v<=4.8 for v in ratios),native_scaling_ratios=ratios,consumer_wall_ms=(c['end_ns']-c['begin_ns'])/1e6,consumer_cpu_ms=c['thread_cpu_ns']/1e6,preparation_wall_ms=(p['end_ns']-p['begin_ns'])/1e6,preparation_cpu_ms=p['thread_cpu_ns']/1e6,whole_wall_ms=statistics.mean(bounds)/1e6,native_billion_adds_per_second=sum(v['dependent_adds'] for v in rows)/sum(v['end_ns']-v['begin_ns'] for v in rows),model_wall_ms=(m['end_ns']-m['begin_ns'])/1e6,configuration=cfg)
    complete=status['complete'] and not status['errors'] and all(v.get('qualified') and v['native_scaling_pass'] for v in cases.values())
    decision=compare([(cases[p['default']],cases[p['optout']]) for p in plan['pairs']],plan['criteria']) if complete else None
    result=dict(all_eight_qualified=complete,cases=cases,comparison=decision,statistics_withheld=not complete,field_fix_verified=False,root_identified=False,old_disturbance_gate_pass=False,
        limits=['Four paired log ratios, t interval descriptive and dependent on independence/approximate normality; no universal performance guarantee.','A source/configuration readback is not proof of speed; native and original work endpoints must jointly improve.','Common native pre-work probe may change startup state; both arms use it. No cross-cohort subtraction or actualGHz claim.','Fixed work lacks originalGUI1000Hz pending/contact-to-paint endpoints.'],bindings=dict(plan_sha256=sha(HERE/'plan01.json'),analyzer_sha256=sha(Path(__file__))))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(all_eight_qualified=complete,comparison=decision),indent=2))
