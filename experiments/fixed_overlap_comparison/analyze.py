"""Frozen four-pair directional comparison; no field or GIL-share claim."""
import hashlib
import json
import math
from pathlib import Path
import statistics
from verify import check,identity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))

def paired(pairs,minimum=.20):
    from scipy.stats import t
    if len(pairs)!=4 or any(a<=0 or b<=0 for a,b in pairs):raise ValueError('Require four positive, complete pairs')
    logs=[math.log(b/a) for a,b in pairs];mean=statistics.mean(logs);half=float(t.ppf(.975,3))*statistics.stdev(logs)/2
    change=math.expm1(mean)
    return dict(concurrent=[a for a,b in pairs],serial=[b for a,b in pairs],serial_minus_concurrent_ms=[b-a for a,b in pairs],relative_change=[b/a-1 for a,b in pairs],geometric_relative_change=change,descriptive_95pct_t_interval_relative=[math.expm1(mean-half),math.expm1(mean+half)],all_pairs_improve=all(b<a for a,b in pairs),directional_threshold_met=all(b<a for a,b in pairs) and change<=-minimum)

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');assert sha(raw/'plan01.json')==sha(HERE/'plan01.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    status=read(raw/'runs/status.json');reference=identity(read(raw/'reference01.json'));cases={}
    for name in plan['cases']:
        path=raw/'runs'/name/'result.json'
        if not path.exists():cases[name]=dict(not_attempted_or_missing=True);continue
        r=read(path)
        if not r.get('complete') or r['errors'] or r['worker_alive']:cases[name]=dict(failed=True,errors=r['errors'],worker_alive=r['worker_alive']);continue
        v=check(plan,r);assert v['pass_all'] and identity(r)==reference and r['variant']==plan['case_variants'][name]
        c=r['consumer'];m=r['model'];a=r['process_before'];b=r['process_after']
        # Recompute counters independently of saved derived accounting.
        assert a['pid']==b['pid'] and a['creation_100ns']==b['creation_100ns'] and all(b[k]>=a[k] for k in ('user_100ns','kernel_100ns','cycles'))
        assert a['end_ns']<=min(c['begin_ns'],m['begin_ns']) and max(c['end_ns'],m['work_done_ns'])<=b['begin_ns']
        points=[dict(frames=0,host_ns=c['begin_ns'],thread_cpu_ns=0)]+r['consumer_progress'];blocks=[]
        for x,y in zip(points,points[1:]):blocks.append(dict(first_frame=x['frames']+1,last_frame=y['frames'],wall_ms=(y['host_ns']-x['host_ns'])/1e6,cpu_ms=(y['thread_cpu_ns']-x['thread_cpu_ns'])/1e6))
        cases[name]=dict(qualified=True,variant=r['variant'],consumer_wall_ms=v['consumer_wall_ms'],consumer_cpu_ms=c['thread_cpu_ns']/1e6,
            whole_work_wall_ms_bounds=[(b['begin_ns']-a['end_ns'])/1e6,(b['end_ns']-a['begin_ns'])/1e6],process_cpu_ms=(b['kernel_100ns']+b['user_100ns']-a['kernel_100ns']-a['user_100ns'])/10000,process_cycles=b['cycles']-a['cycles'],consumer_progress_blocks=blocks,
            model_ready_to_consumer_ms=(c['begin_ns']-m['ready_ns'])/1e6,model_begin_since_consumer_ms=(m['begin_ns']-c['begin_ns'])/1e6,model_wall_ms=(m['end_ns']-m['begin_ns'])/1e6,
            model_call_blocks=[dict(first_ordinal=i,median_wall_ms=statistics.median((x['end_ns']-x['begin_ns'])/1e6 for x in m['calls'][i:i+20])) for i in range(0,len(m['calls']),20)])
    complete=status.get('complete',False) and not status['errors'] and all(v.get('qualified') for v in cases.values())
    primary=paired([(cases[p['concurrent']]['consumer_wall_ms'],cases[p['serial']]['consumer_wall_ms']) for p in plan['pairs']],plan['directional_min_geometric_reduction']) if complete else None
    result=dict(all_eight_cases_qualified=complete,cases=cases,primary=primary,statistics_withheld=not complete,actual_load_disturbance_pass=False,field_fix_verified=False,primary_root_identified=False,
        limits=['One primary endpoint;95% paired t interval assumes independent approximately normal log ratios. Four pairs are a bounded directional experiment, not a robust population estimate.',
                'Direction threshold is the prospectively frozen20% and all-four-pair rule; it does not override old3%/1% failures or establish GIL shares.',
                'No GUI/latest-only/SDK or realtime1000Hz pending measurements. A serial diagnostic schedule is not a production recommendation.',
                'Common seven progress markers and boundary counters are not separately disturbance-qualified. No posthoc case selection or replacement.'],
        bindings={n:sha(HERE/n) for n in ['plan01.json','analyze.py','verify.py']})
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(complete=complete,primary=primary),indent=2))
