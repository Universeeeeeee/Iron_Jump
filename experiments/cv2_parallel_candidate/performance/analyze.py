"""Frozen OpenCV candidate endpoints, all four pairs retained."""
import hashlib
import json
import math
from pathlib import Path
import statistics
from verify import check,identity

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def compare(pairs,minimum=.10,whole_cap=.05):
    from scipy.stats import t
    if len(pairs)!=4:raise ValueError('Require all four pairs')
    wall=[(a['consumer_wall_ms'],b['consumer_wall_ms']) for a,b in pairs]
    whole=[(sum(a['whole_wall_ms_bounds'])/2,sum(b['whole_wall_ms_bounds'])/2) for a,b in pairs]
    if any(a<=0 or b<=0 for a,b in wall+whole):raise ValueError('Nonpositive endpoint')
    logs=[math.log(b/a) for a,b in wall];mean=statistics.mean(logs);half=float(t.ppf(.975,3))*statistics.stdev(logs)/2
    gain=-math.expm1(mean);total=math.expm1(statistics.mean(math.log(b/a) for a,b in whole))
    return dict(default_consumer_ms=[a for a,b in wall],one_consumer_ms=[b for a,b in wall],relative_changes=[b/a-1 for a,b in wall],geometric_consumer_reduction=gain,descriptive_95pct_reduction_interval=[-math.expm1(mean+half),-math.expm1(mean-half)],all_pairs_consumer_improve=all(b<a for a,b in wall),geometric_whole_work_change=total,practical_gate_pass=all(b<a for a,b in wall) and gain>=minimum and total<=whole_cap)

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());plan=read(HERE/'plan01.json');assert sha(raw/'plan01.json')==sha(HERE/'plan01.json')
    assert all(sha(raw/n)==v for n,v in plan['sources'].items());status=read(raw/'runs/status.json');reference=identity(read(raw/'reference01.json'));cases={}
    for name in plan['cases']:
        path=raw/'runs'/name/'result.json'
        if not path.exists():cases[name]=dict(missing=True);continue
        r=read(path)
        if not r.get('complete') or r['errors'] or r['worker_alive']:cases[name]=dict(failed=True,errors=r['errors']);continue
        cfg=read(path.parent/'cv2_config.json');expected=1 if plan['opencv_variants'][name]=='one' else plan['original_threads'];v=check(plan,r)
        assert v['pass_all'] and identity(r)==reference and r['variant']=='concurrent'
        assert cfg['before']==plan['original_threads'] and cfg['after']==cfg['at_end']==expected and cfg['setting']==plan['opencv_variants'][name] and cfg['binary_sha256']==plan['cv2_sha256'] and cfg['workload_returncode']==0
        c,m=r['consumer'],r['model'];a,b=r['process_before'],r['process_after']
        assert a['pid']==b['pid'] and a['creation_100ns']==b['creation_100ns'] and a['end_ns']<=min(c['begin_ns'],m['begin_ns']) and max(c['end_ns'],m['work_done_ns'])<=b['begin_ns']
        points=[dict(frames=0,host_ns=c['begin_ns'],thread_cpu_ns=0)]+r['consumer_progress']
        cases[name]=dict(qualified=True,setting=plan['opencv_variants'][name],consumer_wall_ms=v['consumer_wall_ms'],consumer_cpu_ms=c['thread_cpu_ns']/1e6,
            whole_wall_ms_bounds=[(b['begin_ns']-a['end_ns'])/1e6,(b['end_ns']-a['begin_ns'])/1e6],process_cpu_ms=(b['user_100ns']+b['kernel_100ns']-a['user_100ns']-a['kernel_100ns'])/10000,
            model_wall_ms=(m['end_ns']-m['begin_ns'])/1e6,progress_blocks=[dict(first_frame=x['frames']+1,last_frame=y['frames'],wall_ms=(y['host_ns']-x['host_ns'])/1e6,cpu_ms=(y['thread_cpu_ns']-x['thread_cpu_ns'])/1e6) for x,y in zip(points,points[1:])])
    complete=status.get('complete') and not status['errors'] and all(c.get('qualified') for c in cases.values())
    stats=compare([(cases[p['default']],cases[p['one']]) for p in plan['pairs']],plan['minimum_geometric_consumer_reduction'],plan['maximum_geometric_whole_work_regression']) if complete else None
    result=dict(all_eight_cases_qualified=bool(complete),cases=cases,comparison=stats,statistics_withheld=not complete,actual_load_disturbance_pass=False,field_fix_verified=False,primary_root_identified=False,
        limits=['Primary95% t interval assumes independent approximately normal paired log ratios; four pairs support a bounded directional decision, not universal performance guarantees.','Consumer gain>=10%, every pair improving, and whole-work geometric regression<=5% were frozen before results. Old3%/1% gates unchanged.','No GUI or realtime1000Hz pending/contact-to-paint endpoints. No GIL/CPU responsibility shares inferred.','Prior delivery Windows preflight failure remains preserved; this performance cohort has its own explicit passed preflight gate.'],
        bindings={n:sha(HERE/n) for n in ['plan01.json','analyze.py','verify.py','preflight_passed01.json']})
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(complete=complete,comparison=stats),indent=2))
