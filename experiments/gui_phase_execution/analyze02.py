"""Two fixed phase windows; no latency efficacy or GHz inference."""
import hashlib
import json
from pathlib import Path
from verify_phases import verify_phases
from verify_runtime import verify_runtime

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def decide(ratios,threshold=.15):
    if len(ratios)!=2 or any(v<=0 for v in ratios):raise ValueError('Exactly two positive ratios required')
    return dict(after_open_to_before_open_ratios=ratios,same_direction_large_transition=all(v>=1+threshold for v in ratios) or all(v<=1-threshold for v in ratios),frequency_attribution=False,root_identified=False)

if __name__=='__main__':
    raw=HERE/'runs/evidence02';manifest=read(raw/'manifest.json')
    assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan02.json');assert sha(raw/'plan02.json')==sha(HERE/'plan02.json')
    assert all(sha(raw/n)==v for n,v in plan['sources'].items())
    status=read(raw/'runs/phase02/status.json');cases={}
    for case in plan['cases']:
        folder=raw/'runs/phase02'/case['id']
        if not (folder/'record.json').exists():cases[case['id']]=dict(not_attempted=True);continue
        record=read(folder/'record.json')
        if not record.get('complete') or record['errors'] or record['target_still_running']:cases[case['id']]=dict(failed=True,record=record);continue
        phase=verify_phases(folder/'native_phases');activation=read(folder/'qos_activation.json')
        runtime=verify_runtime(activation,'default',activation['context']['session_id'])
        model_tids={v['tid'] for v in activation['runtime_context'] if v['role']=='model'}
        assert model_tids=={phase['same_model_tid']}
        final=read(folder/'capture/finalization.json');assert final['metadata_finalization_pass'] and all(final['checks'].values())
        workload=read(folder/'capture/workload_final.json');opens=workload['rows']['model_open'];closes=workload['rows']['model_close']
        assert len(opens)==len(closes)==1 and opens[0]['error'] is None and closes[0]['error'] is None
        boundaries=read(folder/'native_phases/boundaries.json')['rows']
        assert opens[0]['begin_ns']<=boundaries[0]['begin_ns']<=boundaries[2]['end_ns']<=opens[0]['end_ns']
        assert closes[0]['begin_ns']<=boundaries[3]['begin_ns']<=boundaries[4]['end_ns']<=closes[0]['end_ns']
        a,b,c=[phase['stages'][n]['billion_adds_per_second'] for n in ('before_open','after_open','after_close')]
        cases[case['id']]=dict(complete=True,phase=phase,runtime=runtime,after_open_to_before_open=b/a,after_close_to_before_open=c/a,
            outer_audit_open_ms=(opens[0]['end_ns']-opens[0]['begin_ns'])/1e6,outer_audit_close_ms=(closes[0]['end_ns']-closes[0]['begin_ns'])/1e6,
            original_return_model_confirmed=final['application_return_model_confirmed'])
    complete=status['complete'] and not status['errors'] and len(cases)==2 and all(v.get('complete') for v in cases.values())
    result=dict(all_two_complete=complete,cases=cases,decision=decide([cases[v['id']]['after_open_to_before_open'] for v in plan['cases']]) if complete else None,
        statistics_withheld=not complete,latency_qualification=False,observer_disturbance_qualified=False,field_fix_verified=False,
        limits=['Three active native probes intentionally perturb ready and cleanup timing. They can themselves warm or change state.','Snapshots bracket initialization; they do not continuously measure during contact or infer CPU frequency.','Two windows do not identify a cause or exclude unobserved states; no optional additional windows.'],bindings=dict(plan_sha256=sha(HERE/'plan02.json'),analyzer_sha256=sha(Path(__file__))))
    with (HERE/'result02.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
