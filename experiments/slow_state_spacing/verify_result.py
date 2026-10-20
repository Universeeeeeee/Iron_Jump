"""Recompute gap/state evidence from the delivered six windows, preserving null result."""
import hashlib
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');result=read(HERE/'result01.json');root=HERE/'runs/evidence01'
    manifest=read(root/'manifest01.json');meta=read(HERE/'transport01.json')
    assert sha(HERE/'runs/evidence01.zip')==meta['sha256']
    assert all(sha(root/n)==v for n,v in manifest['files'].items())
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert result['bindings']['analysis_sha256']==sha(HERE/'analyze.py')
    assert read(HERE/'transport_execution01.json')['ssh_returncode']==0
    state_labels=[];case_rows=[];gaps=[]
    for case,outcome in zip(plan['schedule'],result['cases']):
        name=case['id'];record=read(root/'runs'/(name+'.record.json'));data=read(root/'runs'/name/'result.json')
        assert outcome['id']==name and record['complete'] and not record['errors'] and record['returncode']==0 and not record['child_still_running']
        assert data['complete'] and not data['worker_alive'] and data['full_original_chain_exact']
        assert data['variant']=='serial' and len(data['model']['calls'])==220 and data['consumer']['frames']==6824
        assert data['preparation']['frames']==42237 and data['opencv_threads']==8
        assert data['model']['begin_ns']>=data['consumer']['end_ns']
        prep=(data['preparation']['end_ns']-data['preparation']['begin_ns'])/1e6
        model=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in data['model']['calls'])
        assert prep>=4300 and model>=30 and outcome['state']['label']=='slow'
        assert prep==outcome['state']['prepare_wall_ms'] and model==outcome['state']['model_call_median_ms']
        state_labels.append('slow')
        if case['gap_seconds'] is not None:
            gap=record['spacing'];actual=(gap['child_launch_before_ns']-gap['previous_exit_observed_ns'])/1e9
            assert case['gap_seconds']<=actual<=case['gap_seconds']+2
            if case['gap_seconds']==300:
                samples=gap['system_samples'];pct=[]
                for a,b in zip(samples,samples[1:]):
                    assert 0<b['begin_ns']-a['begin_ns']<=6_000_000_000
                    total=b['user_100ns']+b['kernel_including_idle_100ns']-a['user_100ns']-a['kernel_including_idle_100ns']
                    idle=b['idle_100ns']-a['idle_100ns'];assert 0<=idle<=total and total>0
                    pct.append(100*(total-idle)/total)
                assert len(pct)>=50 and statistics.median(pct)<=15 and max(pct)<=50 and {v['ac'] for v in samples}=={1}
                gaps.append(dict(case=name,actual_seconds=actual,system_busy_median_percent=statistics.median(pct),system_busy_max_percent=max(pct)))
        case_rows.append(dict(case=name,prepare_wall_ms=prep,model_call_median_ms=model,model_open_ms=outcome['model_open_ms']))
    assert len(state_labels)==6 and not result['controlled_five_minute_condition_supported']
    first=case_rows[0]['model_open_ms'];later=[v['model_open_ms'] for v in case_rows[1:]]
    verified=dict(six_original_windows_match=True,all_slow=True,qualified_long_gaps=gaps,
        model_open_first_ms=first,model_open_subsequent_range_ms=[min(later),max(later)],
        distinction='Model-open became shorter while preparation/consumer/model execution stayed slow. Startup/open overhead and persistent slow execution cannot be conflated.',
        fast_to_slow_condition_identified=False,root_mechanism_identified=False,
        bindings={p.name:sha(p) for p in (Path(__file__),HERE/'plan01.json',HERE/'result01.json',HERE/'transport01.json')})
    with (HERE/'verification01.json').open('x') as f:json.dump(verified,f,indent=2)
    print(json.dumps(verified,indent=2))
