"""Decompose prior fixed-cohort counters without changing its failed precision gate."""
import hashlib
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    old=ROOT/'experiments/fixed_work_variance';raw=old/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==h for n,h in manifest.items())
    plan=read(raw/'plan01.json');prior=read(old/'result01.json');assert prior['all_case_qualification_pass'];cases={}
    for name in plan['cases']:
        r=read(raw/'runs'/name/'result.json');a,b=r['process_before'],r['process_after'];consumer=r['consumer'];model=r['model']
        user=(b['user_100ns']-a['user_100ns'])/10000;kernel=(b['kernel_100ns']-a['kernel_100ns'])/10000
        cpu=user+kernel;assert cpu*1e6==prior['cases'][name]['accounting']['process_cpu_ns']
        named=(consumer['thread_cpu_ns']+model['thread_cpu_ns'])/1e6
        during=[x for x in model['calls'] if consumer['begin_ns']<=x['begin_ns'] and x['end_ns']<=consumer['end_ns']]
        after=[x for x in model['calls'] if x['begin_ns']>=consumer['end_ns']]
        boundary=[x for x in model['calls'] if x not in during and x not in after]
        assert len(during)+len(after)+len(boundary)==plan['model_calls']
        cases[name]=dict(process_user_ms=user,process_kernel_ms=kernel,process_cpu_ms=cpu,
            process_cycles=b['cycles']-a['cycles'],consumer_cpu_ms=consumer['thread_cpu_ns']/1e6,
            model_entry_thread_cpu_ms=model['thread_cpu_ns']/1e6,unassigned_cpu_difference_ms=cpu-named,
            consumer_wall_ms=(consumer['end_ns']-consumer['begin_ns'])/1e6,
            model_wall_ms=(model['end_ns']-model['begin_ns'])/1e6,
            model_during_consumer=dict(count=len(during),median_wall_ms=statistics.median((x['end_ns']-x['begin_ns'])/1e6 for x in during)),
            model_after_consumer=dict(count=len(after),median_wall_ms=statistics.median((x['end_ns']-x['begin_ns'])/1e6 for x in after)),
            boundary_calls_retained=boundary)
    pairs=[]
    for a,b in plan['pairs']:
        x,y=cases[a],cases[b]
        pairs.append(dict(names=[a,b],differences={k:y[k]-x[k] for k in ('process_user_ms','process_kernel_ms','process_cpu_ms','consumer_cpu_ms','model_entry_thread_cpu_ms','unassigned_cpu_difference_ms')},cycles_relative_change=y['process_cycles']/x['process_cycles']-1))
    result=dict(cases=cases,pairs=pairs,source_sha256=sha(Path(__file__)),prior_result_sha256=sha(old/'result01.json'),manifest_sha256=sha(raw/'manifest.json'),
        old_precision_failure_unchanged=True,primary_root_identified=False,
        limits=['Unassigned difference is an accounting residual, not an exclusive native-model pool category; named thread intervals and process intervals differ and OS accounting is quantized.',
                'Process CPU quantization uncertainty is not bounded by one scalar15.625ms tick; native-thread count/lifetime accounting is missing. No claim that quantization is ruled out.',
                'Model during/after consumer is a temporal association, not randomized intervention; frame order/history and other time trends differ. Boundary calls retained separately.',
                'No transfer of these counters to GUI AB or human windows; no GIL/CPU attribution percentages.'])
    with (HERE/'prior_accounting_result02.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(pairs,indent=2))
