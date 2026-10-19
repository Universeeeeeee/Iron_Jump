"""Retained-thread accounting for one fixed workload, not full lifecycle attribution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'experiments/thread_accounting_controls'));from inventory02 import summarize
    sys.path.insert(0,str(ROOT/'experiments/fixed_work_accounting'));from counters import validate
    plan=read(HERE/'plan03.json');r=read(HERE/'workload03.json');a=read(HERE/'accounting03.json')
    prior_root=ROOT/'experiments/fixed_work_variance/runs/evidence01';manifest=read(prior_root/'manifest.json');assert all(sha(prior_root/n)==v for n,v in manifest.items())
    prior=read(prior_root/'runs/pair01_a/result.json')
    assert all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items()) and all(sha(HERE/n)==v for n,v in plan['sources'].items())
    exact=all(r[k]==prior[k] for k in ('frame_evidence','model_result_sha256','report_sha256'))
    assert r['complete'] and r['full_original_chain_exact'] and not r['errors'] and not r['worker_alive'] and exact
    assert a['workload_returncode']==0 and not a['errors'] and a['source_unchanged'] and a['handles_closed']
    assert len(a['reads'])==2
    before,after=a['reads'];assert before['process']==r['process_before'] and after['process']==r['process_after']
    summary=summarize(before['threads'],after['threads'],plan['per_read_ns'],plan['group_ns']);assert summary==a['retained_accounting']
    process=validate(r);assert process['accounting_pass'] and process==r['process_accounting']
    c,m=r['consumer'],r['model'];assert before['threads']['after_ns']<=min(c['begin_ns'],m['begin_ns'])
    assert max(c['end_ns'],m['end_ns'],m['work_done_ns'])<=after['threads']['before_ns']
    assert a['enumeration_before']['after_ns']<=before['process']['begin_ns']<=before['process']['end_ns']<=before['threads']['before_ns']
    assert after['threads']['after_ns']<=after['process']['begin_ns']<=after['process']['end_ns']<=a['enumeration_after']['before_ns']
    rows=[dict(**x,role='consumer' if x['tid']==c['tid'] else 'model_entry' if x['tid']==m['tid'] else 'other_retained') for x in summary['threads']]
    cpu=process['process_cpu_ns']/1e6
    result=dict(original_complete_work_exact=exact,retained_threads_pass=summary['retained_threads_pass'],reasons=summary['reasons'],threads=rows,
        process_cpu_ms=cpu,retained_cpu_ms=summary['sum_cpu_ms'],unassigned_cpu_difference_ms=cpu-summary['sum_cpu_ms'],
        role_cpu_ms={role:sum(x['cpu_ms'] for x in rows if x['role']==role) for role in ('consumer','model_entry','other_retained')},
        process_cycles=process['process_cycles'],retained_cycles=summary['sum_cycles'],unassigned_cycles_difference=process['process_cycles']-summary['sum_cycles'],
        group_read_ms=[(x['threads']['after_ns']-x['threads']['before_ns'])/1e6 for x in (before,after)],
        enumeration_ms=[(a[k]['after_ns']-a[k]['before_ns'])/1e6 for k in ('enumeration_before','enumeration_after')],
        whole_process_lifetime_coverage_proven=False,actual_load_disturbance_pass=False,primary_root_identified=False,
        limits=['Other-retained is not proven model pool membership. No native thread start address or complete lifecycle trace was captured.',
                'Agreement of process and retained sum does not rule out short-lived threads, accounting quantization or offsetting differences.',
                'This single new diagnostic cannot explain historical pair variance quantitatively; do not substitute it for old failures.',
                'Original workload, native libraries, full report, fixed pixels and220 model results matched. This is not live GUI/SDK or field load.'],
        bindings={n:sha(HERE/n) for n in ['plan03.json','accounting03.json','workload03.json','review03.py']})
    with (HERE/'review03.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('threads','bindings','limits')},indent=2))
