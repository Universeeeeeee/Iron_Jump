"""Offline A/A and paired equivalence summaries from immutable saved windows."""
import argparse
import json
from pathlib import Path
from control03 import read,sha,write
from verify import case_result
import noise_stats as stats

ROOT=Path(__file__).resolve().parents[2]



def ordered_pairs(specs,cases):
    pairs=[]
    for i in sorted({s['pair'] for s in specs}):
        group=[s for s in specs if s['pair']==i]
        if len(group)!=2:raise ValueError('A pair needs exactly two cases')
        if {s['mode'] for s in group}=={'off','on'}:
            group=sorted(group,key=lambda s:s['mode']!='off')
        elif len({s['mode'] for s in group})==1 and {s['side'] for s in group}=={'a','b'}:
            group=sorted(group,key=lambda s:s['side'])
        else:raise ValueError('Ambiguous pair orientation')
        pairs.append(tuple(cases[s['id']] for s in group))
    return pairs


def stage(raw,plan_name,stage_name):
    manifest=read(raw/'manifest.json');assert all(sha(raw/n)==h for n,h in manifest.items())
    plan=read(raw/plan_name);result=read(raw/stage_name/'run01/result.json')
    assert not result['errors'] and result['capture_protocol_complete'] and result['plan_sha256']==sha(raw/plan_name)
    assert all(sha(raw/n)==h for n,h in plan['sources'].items()) and sha(raw/'observer.exe')==plan['observer_sha256']
    cases={};cadence={}
    for spec in plan['cases']:
        p=raw/stage_name/'run01'/spec['id'];record=read(p/'record.json');rows=[json.loads(l) for l in (p/'samples.jsonl').read_text().splitlines()] if spec['mode']=='on' else []
        v=case_result(record,read(p/'target/roi.json'),read(p/'target/complete.json'),rows,plan,ROOT);assert v==read(p/'analysis.json') and v['case_pass'];cases[spec['id']]=v
        if rows:
            first=rows[0];samples=[s for s in rows if s['kind']=='sample'];f=first['qpc_frequency'];gaps=[(b['qpc_begin']-a['qpc_begin'])*1000/f for a,b in zip(samples,samples[1:])]
            cadence[spec['id']]=dict(requested=first['period_ms']==plan['period_ms'] and first['requested_count']==plan['count'] and first['requested_tid']==record['ready']['tid'],actual_gap_ms=gaps,within_predeclared_pacing_budget=all(plan['period_ms']-1<=x<=plan['period_ms']+50 for x in gaps))
    pairs=ordered_pairs(plan['cases'],cases)
    estimate=stats.contrast(pairs)
    return dict(scope=plan['scope'],stage=stage_name,cases=len(cases),all_recomputed=True,estimate=estimate,drift=stats.drift(list(cases.values())),cadence=cadence,all_cadence_checks=all(c['requested'] and c['within_predeclared_pacing_budget'] for c in cadence.values()),actual_load_disturbance_pass=False,field_attribution_ready=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--plan',required=True);p.add_argument('--stage',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();v=stage(a.raw,a.plan,a.stage);write(a.output,v)
    print(json.dumps(dict(stage=v['stage'],n=v['estimate']['independent_pairs'],whole_wall=v['estimate']['metrics']['wall_ns'],drift=v['drift'],cadence_pass=v['all_cadence_checks']),indent=2))
