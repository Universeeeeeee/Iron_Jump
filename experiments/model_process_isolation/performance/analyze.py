import hashlib
import json
import math
from pathlib import Path
import statistics
from delivery import verify_child
from verify import check,identity

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def compare(pairs,minimum=.20,whole_cap=.05):
    if len(pairs)!=4:raise ValueError('Exactly four pairs required')
    ratios=[b['consumer_wall_ms']/a['consumer_wall_ms'] for a,b in pairs]
    whole=[b['whole_wall_ms']/a['whole_wall_ms'] for a,b in pairs]
    if any(v<=0 for v in ratios+whole):raise ValueError('Nonpositive endpoint')
    logs=[math.log(v) for v in ratios];mean=statistics.mean(logs);half=3.182446305284263*statistics.stdev(logs)/2
    gain=-math.expm1(mean);regression=math.expm1(statistics.mean(math.log(v) for v in whole))
    return dict(relative_consumer_changes=[v-1 for v in ratios],geometric_consumer_reduction=gain,geometric_whole_work_change=regression,
        descriptive_95pct_consumer_reduction_interval=[-math.expm1(mean+half),-math.expm1(mean-half)],
        all_four_pairs_improve=all(v<1 for v in ratios),advance=all(v<1 for v in ratios) and gain>=minimum and regression<=whole_cap)

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');assert sha(raw/'plan01.json')==sha(HERE/'plan01.json')
    assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    status=read(raw/'runs/status.json');reference=identity(read(raw/'reference01.json'));cases={}
    for name in plan['cases']:
        folder=raw/'runs'/name
        if not (folder/'result.json').exists():cases[name]=dict(missing=True);continue
        r=read(folder/'result.json')
        if not r.get('complete') or r['errors'] or r['worker_alive']:cases[name]=dict(failed=True,errors=r['errors']);continue
        validation=check(plan,r);assert validation['pass_all'] and identity(r)==reference and r['opencv_threads']==8
        c,m=r['consumer'],r['model'];a,b=r['process_before'],r['process_after']
        child=None
        if plan['isolation_variants'][name]=='process':
            ctrl=read(folder/'vision_child/controller.json');source=read(folder/'vision_child/result.json')
            assert ctrl['parent_pid']==a['pid'] and ctrl['child_pid']==source['pid']
            child=verify_child(r,source,[v['pixels_sha256'] for v in r['frame_evidence']],a['pid'])
        points=[dict(frames=0,host_ns=c['begin_ns'],thread_cpu_ns=0)]+r['consumer_progress']
        cases[name]=dict(qualified=True,variant=plan['isolation_variants'][name],consumer_wall_ms=validation['consumer_wall_ms'],consumer_cpu_ms=c['thread_cpu_ns']/1e6,
            whole_wall_ms=statistics.mean(r['process_accounting']['wall_ns_bounds'])/1e6,
            parent_process_cpu_ms=r['process_accounting']['process_cpu_ns']/1e6,model_or_proxy_wall_ms=(m['end_ns']-m['begin_ns'])/1e6,
            child=child,progress_blocks=[dict(first_frame=x['frames']+1,last_frame=y['frames'],wall_ms=(y['host_ns']-x['host_ns'])/1e6,cpu_ms=(y['thread_cpu_ns']-x['thread_cpu_ns'])/1e6) for x,y in zip(points,points[1:])])
    complete=status['complete'] and not status['errors'] and all(v.get('qualified') for v in cases.values())
    decision=compare([(cases[p['local']],cases[p['process']]) for p in plan['pairs']],plan['criteria']['minimum_geometric_consumer_reduction'],plan['criteria']['maximum_geometric_whole_work_regression']) if complete else None
    result=dict(all_eight_complete=complete,cases=cases,comparison=decision,statistics_withheld=not complete,field_fix_verified=False,root_identified=False,
        limits=['Four paired log ratios; t interval descriptive with independence/approximate-normality assumptions.','Parent model-threadCPU is IPC proxyCPU in process arm. Parent processCPU excludes vision child. No aligned whole-systemCPU sum orGIL share.','OriginalGUI/realtime1000Hz pending/contact-to-paint absent. Fixed-work improvement is not a field-fix proof.','Delivery windows excluded; no reruns or omitted first pairs.'],bindings=dict(plan_sha256=sha(HERE/'plan01.json'),analysis_sha256=sha(Path(__file__))))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(all_eight_complete=complete,comparison=decision),indent=2))
