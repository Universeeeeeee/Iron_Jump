"""All eight frozen cases, common metrics; no post-hoc performance subsets."""
import hashlib
import json
from pathlib import Path
import sys
from decision import decide
from boundary import verify

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');archive=HERE/'runs/evidence01'
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    manifest=read(archive/'manifest01.json');assert all(sha(archive/n)==v for n,v in manifest['files'].items())
    assert all(manifest['files'][n]==v for n,v in plan['sources'].items())
    sys.path.insert(0,str(ROOT/'experiments/session_gui_comparison'));from metrics import measure
    original=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz'
    assert sha(original)==plan['input_sha256']['raw_frames.npz']
    status=read(archive/'runs/cohort01/status.json');rows={}
    for case in plan['cases']:
        folder=archive/'runs/cohort01'/case['id'];record=folder/'record.json'
        if not record.exists():rows[case['id']]=dict(not_attempted=True);continue
        r=read(record)
        if not r.get('complete') or r['errors'] or r['target_still_running']:
            rows[case['id']]=dict(complete=False,record=r);continue
        capture=folder/'capture';pipeline=read(capture/'pipeline_review.json');sdk=read(capture/'sdk_backend.json')
        verify(read(capture/'boundary.json'),case['boundary'])
        assert sdk['backend']=='real_native_SDK' and sdk['serve_returncode']==0 and sdk['error'] is None
        assert all(v['sha256']==plan['existing_sources']['camera/bin/'+v['name']] for v in sdk['actual_loaded_modules'])
        m=measure(capture,original)
        m.update(complete=True,semantics_pass=all(r['semantics'][k] for k in ('full_original_report','full_quality_runtime_state','raw_fields_exact')),
            native_SDK_pass=pipeline['final_model_cleanup_confirmed'] and sdk['calls']['close']==1 and sdk['pid']==pipeline['sdk_pid'],
            mode=case['boundary'],pair=case['pair'])
        rows[case['id']]=m
    decision=decide(rows,plan)
    result=dict(decision=decision,cases=rows,cohort_complete=status['complete'],cohort_errors=status['errors'],
        interpretation='One finite paired causal experiment. Dynamic model/GUI/SDK policies are unchanged; delivered selections can be mediated by scheduling. No GIL duration/CPU shares.',
        old_calibration_upgraded=False,formal_program_modified=False,
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),analyzer_sha256=sha(Path(__file__)),archive_sha256=sha(HERE/'runs/evidence01.zip')))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(decision=decision,cases={n:{k:v.get(k) for k in ('mode','observed_queue_lower','queue_upper','scheduled_max_ms','input_lateness_ms','complete','not_attempted')} for n,v in rows.items()}),indent=2))
