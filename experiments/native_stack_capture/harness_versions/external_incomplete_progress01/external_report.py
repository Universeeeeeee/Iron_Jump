"""Bounded work/counter comparisons for frozen final-observer synthetic pairs."""
import argparse
import hashlib
import json
from pathlib import Path
from align_clock import main as record_mapping, mapping as anchor_mapping

HERE=Path(__file__).resolve().parent


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def work_bounds(history,name,before,after,mapping):
    if not history:raise ValueError('Missing synthetic progress evidence')
    values=[p['work'][name] for p in history]
    if any(b<a for a,b in zip(values,values[1:])):raise ValueError('Work counter regressed')
    frequency=mapping['qpc_frequency']
    def bounds(snapshot):
        early=snapshot['start']['qpc_before']*1000000000//frequency+mapping['host_ns_offset_lower']
        late=snapshot['end']['qpc_after']*1000000000//frequency+mapping['host_ns_offset_upper']
        lows=[p['work'][name] for p in history if p['host_after_ns']<=early]
        highs=[p['work'][name] for p in history if p['host_before_ns']>=late]
        if not lows or not highs:raise ValueError('Progress does not bracket the counter window')
        return max(lows),min(highs)
    start_low,start_high=bounds(before)
    end_low,end_high=bounds(after)
    low,high=max(0,end_low-start_high),end_high-start_low
    if high<low:raise ValueError('Inconsistent work bounds')
    return dict(lower=low,upper=high)


def case_result(case):
    record=read(case/'window/record.json')
    mapping=record_mapping(record)
    fixtures={process:read(case/'synthetic'/process/'progress.json') for process in ['gui','sdk']}
    child_maps={process:anchor_mapping(f['anchors']) for process,f in fixtures.items()}
    maps=[mapping]+list(child_maps.values())
    if any(m['qpc_frequency']!=mapping['qpc_frequency'] for m in maps):raise ValueError('Cross-process frequency mismatch')
    mapping=dict(mapping,host_ns_offset_lower=max(m['host_ns_offset_lower'] for m in maps),
                 host_ns_offset_upper=min(m['host_ns_offset_upper'] for m in maps))
    mapping['uncertainty_ns']=mapping['host_ns_offset_upper']-mapping['host_ns_offset_lower']
    if mapping['uncertainty_ns']<0:raise ValueError('Cross-process perf clock mismatch')
    result=dict(mode=record['mode'],processes={},clock_mapping=mapping,cross_process_clock_maps=child_maps,
                plan_reference=read(case/'plan_reference.json'),synthetic_only=True)
    rows=record['external_observation']
    for process in ['gui','sdk']:
        fixture=fixtures[process]
        pid=fixture['pid']
        observations=[(a,b) for a,b in zip(rows['before'],rows['after']) if a['pid']==pid]
        threads={}
        for a,b in observations:
            name=a['name']
            threads[name]=dict(tid=a['tid'],cpu_s=(b['user_100ns']+b['kernel_100ns']-a['user_100ns']-a['kernel_100ns'])/1e7,
                cycles=b['cycles']-a['cycles'],work=work_bounds(fixture['history'],name,a,b,mapping),
                counter_bracket_us_max=max((r['end']['qpc_after']-r['start']['qpc_before'])/mapping['qpc_frequency']*1e6 for r in [a,b]))
        p=dict(pid=pid,threads=threads)
        if result['mode']!='off':
            quality=read(case/'split'/str(pid)/'quality.json')
            p['quality_checks']=quality['quality_checks']
            p['measurement_acceptance_pass']=quality['measurement_acceptance_pass']
            p['trace_metrics']={name:{k:v for k,v in t.items() if k not in ['witnesses','families','work']} for name,t in quality['threads'].items()}
            p['families']={name:t['families'] for name,t in quality['threads'].items()}
            p['independent_scan']=quality['independent_scan']
            p['clock_max_residual_ms']=quality['clock_max_residual_ms']
        result['processes'][process]=p
    if result['mode']!='off':result['acceptance']=read(case/'split/acceptance.json')
    return result


def pair_result(off,on,limits):
    processes={}
    for process in ['gui','sdk']:
        a,b=off['processes'][process],on['processes'][process]
        def total(p,key):return sum(p['threads'][name][key] for name in ['cpu_a','cpu_b'])
        low_off=sum(a['threads'][name]['work']['lower'] for name in ['cpu_a','cpu_b'])
        high_off=sum(a['threads'][name]['work']['upper'] for name in ['cpu_a','cpu_b'])
        low_on=sum(b['threads'][name]['work']['lower'] for name in ['cpu_a','cpu_b'])
        high_on=sum(b['threads'][name]['work']['upper'] for name in ['cpu_a','cpu_b'])
        if min(low_off,high_off,low_on,high_on)<=0:raise ValueError('Insufficient CPU work')
        work=dict(lower=low_on/high_off-1,upper=high_on/low_off-1)
        changes={key:total(b,key)/total(a,key)-1 for key in ['cpu_s','cycles']}
        passed=work['lower']>=-limits['work'] and work['upper']<=limits['work'] and all(abs(v)<=limits[k] for k,v in changes.items())
        processes[process]=dict(work_relative_change_bounds=work,relative_changes=changes,perturbation_pass=passed,
                                measurement_acceptance_pass=b['measurement_acceptance_pass'])
    return dict(processes=processes,passed=all(p['perturbation_pass'] and p['measurement_acceptance_pass'] for p in processes.values()))


def main(a):
    plan=read(a.plan)
    cases={}
    for mode in ['cpu','wait']:
        for i in range(1,4):
            for setting in ['off',mode]:
                name=f'{mode}_pair{i}_{setting}'
                cases[name]=case_result(a.runs/name)
                if cases[name]['plan_reference']['external_plan_sha256']!=hashlib.sha256(a.plan.read_bytes()).hexdigest():
                    raise ValueError('Case used a different frozen plan')
    pairs={mode:[dict(pair=i,**pair_result(cases[f'{mode}_pair{i}_off'],cases[f'{mode}_pair{i}_{mode}'],plan['pair_limits'])) for i in range(1,4)] for mode in ['cpu','wait']}
    result=dict(scope=plan['scope'],cases=cases,pairs=pairs,
                final_external_synthetic_qualification_pass={m:all(p['passed'] for p in pairs[m]) for m in pairs},
                quantitative_field_attribution_ready=False,external_plan_sha256=hashlib.sha256(a.plan.read_bytes()).hexdigest())
    with a.output.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(dict(qualification=result['final_external_synthetic_qualification_pass'],pairs=pairs),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('runs',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--plan',type=Path,default=HERE/'external_plan.json')
    main(p.parse_args())
