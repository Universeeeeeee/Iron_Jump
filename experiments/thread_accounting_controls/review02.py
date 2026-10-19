"""Recompute controls and retain known thread-lifetime incompleteness."""
import hashlib
import json
from pathlib import Path
import sys
from inventory02 import summarize

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    sys.path.insert(0,str(HERE.parent/'wall_cpu_controls'));from probe import delta
    plan=read(HERE/'plan02.json');result=read(HERE/'result02.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert sha(HERE/'plan01.json')==plan['prior_plan_sha256'] and sha(HERE/'result01.json')==plan['prior_failure_sha256']
    assert result.get('complete') and not result['errors'] and list(result['cases'])==plan['cases']
    out={}
    for name,c in result['cases'].items():
        assert c['expected_control_pass'] and not c['workers_alive'] and c['handles_closed'] and 'error' not in c and 'cleanup_error' not in c
        s=summarize(c['before'],c['after'],plan['per_read_ns'],plan['group_ns']);assert s==c['summary']
        d=delta(c['process_before'],c['process_after']);assert d==c['process_delta']
        assert c['enumeration_before']['after_ns']<=c['process_before']['before_ns']<=c['before']['before_ns']<=c['before']['after_ns']
        assert c['after']['after_ns']<=c['process_after']['before_ns']<=c['process_after']['after_ns']<=c['enumeration_after']['before_ns']
        assert all(c['before']['after_ns']<=w['begin_ns']<=w['end_ns']<=c['after']['before_ns'] for w in c['workers'])
        allowed={'retained_thread_exited','endpoint_enumeration_changed'} if name=='exited_worker' else set()
        assert set(s['reasons'])<=allowed
        if name=='exited_worker':assert 'retained_thread_exited' in s['reasons']
        assert not s['whole_process_lifetime_coverage_proven']
        out[name]=dict(group_read_ms=[(c[k]['after_ns']-c[k]['before_ns'])/1e6 for k in ('before','after')],
            enumeration_ms=[(c[k]['after_ns']-c[k]['before_ns'])/1e6 for k in ('enumeration_before','enumeration_after')],
            enumeration_thread_cpu_ms=[c[k]['thread_cpu_ns']/1e6 for k in ('enumeration_before','enumeration_after')],
            retained_threads_pass=s['retained_threads_pass'],reasons=s['reasons'],process_cpu_ms=d['process']['cpu_ms'],retained_cpu_ms=s['sum_cpu_ms'],residual_cpu_ms=c['cpu_residual_ms'],whole_process_lifetime_coverage_proven=False)
    with (HERE/'review02.json').open('x') as f:json.dump(dict(cases=out,all_three_expected_controls_pass=True,old_failure_unchanged=True,actual_load_disturbance_pass=False,primary_root_identified=False,sources={n:sha(HERE/n) for n in ['review02.py','plan02.json','result02.json']}),f,indent=2)
    print(json.dumps(out,indent=2))
