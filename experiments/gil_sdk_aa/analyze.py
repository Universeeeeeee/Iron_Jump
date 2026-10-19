"""Full prospective pair evidence; mismatch is retained, not normalized away."""
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pair_identity',HERE/'compare.py');identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))

def totals(record):
    before=record['before'];after=record['after'];assert len(before)==len(after)
    output={}
    for a,b in zip(before,after):
        assert (a['pid'],a['tid'],a['creation_100ns'],a['role'])==(b['pid'],b['tid'],b['creation_100ns'],b['role']) and a['active'] and b['active']
        cpu=(b['user_100ns']+b['kernel_100ns']-a['user_100ns']-a['kernel_100ns'])*100;cycles=b['cycles']-a['cycles'];assert cpu>=0 and cycles>=0
        role='gui_other_native' if a['role']=='gui' and a.get('name') else a['role']
        slot=output.setdefault(role,dict(cpu_ns=0,cycles=0,threads=0));slot['cpu_ns']+=cpu;slot['cycles']+=cycles;slot['threads']+=1
    return output

if __name__=='__main__':
    cases={};ids={}
    for name in read(HERE/'plan01.json')['cases']:
        folder=HERE/'runs/evidence01/runs'/name;review=read(HERE/(name+'_review.json'));m=read(folder/'capture/measurement.json');r=read(folder/'record01.json')
        ids[name]=identity.identities(m,review)
        cases[name]=dict(protocol_qualification_pass=review['protocol_qualification_pass'],counts={k:(len(v) if isinstance(v,list) else v) for k,v in ids[name].items()},totals=totals(r),native_clock=review['native_clock'],child_clock=review['wire']['child_clock'],queue_observed_lower=max(x[3] for x in m['queue_common']+m['queue_samples']))
    a,b=read(HERE/'plan01.json')['cases'];comparison=identity.compare(ids[a],ids[b]);different={}
    for key in ('video','whole_inference','ROI_inference'):
        x,y=ids[a][key],ids[b][key];different[key]=dict(lengths=[len(x),len(y)],first_mismatch=next((dict(position=i,left=u,right=v) for i,(u,v) in enumerate(zip(x,y)) if u!=v),None))
    changes={role:{k:(cases[b]['totals'][role][k]/v[k]-1 if v[k]>0 else None) for k in ('cpu_ns','cycles')} for role,v in cases[a]['totals'].items() if role in cases[b]['totals']}
    result=dict(cases=cases,comparison=comparison,identity_differences=different,descriptive_counter_relative_changes=changes,
                all_protocols_pass=all(x['protocol_qualification_pass'] for x in cases.values()),ON_allowed=False,
                limits=['Single pair cannot estimate independent-pair variance or a confidence interval.','Counter differences include scheduling and unequal work; never label these as observer overhead.','GUI main thread and other GUI native threads are separate; SDK belongs to another PID/GIL.','GetThreadTimes empirical15.625ms quantum remains material;100ns units do not establish precision.','Common observation overhead remains unqualified even if a later sampler-only comparison passes.'],
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
