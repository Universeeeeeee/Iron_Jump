"""Independent complete-value/lifecycle/CPU-ledger checks after all targets exit."""
import hashlib,importlib.util,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
for p in (ROOT/'experiments/session_gui_vision',ROOT/'experiments/session_local_baseline',ROOT/'experiments/session_gui_comparison',HERE):sys.path.insert(0,str(p))
from pipeline_review import verify_pipeline
from context import check
from ledger import verify
from delta import interval
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json')
    assert all(sha(archive/n)==v for n,v in manifest.items()) and all(sha(archive/n)==v for n,v in p['sources'].items())
    collection=read(HERE/'collection01.json');assert sha(HERE/'evidence01.zip')==collection['archive_sha256']
    spec=importlib.util.spec_from_file_location('original_values_review',ROOT/'experiments/session_gui_vision/review02.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    stage=archive/'runs/cohort01';status=read(stage/'status.json');cases={}
    for c in p['cases']:
        folder=stage/c['id']
        if not (folder/'record.json').exists():cases[c['id']]=dict(not_attempted=True);continue
        record=read(folder/'record.json')
        if not record.get('complete'):cases[c['id']]=dict(failed=True,record=record);continue
        capture=folder/'capture';w=read(capture/'workload_final.json');gui=read(capture/'gui_result.json');ctx=read(capture/'gui_context.json');cpu=read(capture/'cpu_ledger.json');first=read(capture/'cpu_application_return.json');phases=read(capture/'phase_context.json')
        assert record['target_returncode']==0 and not record['errors'] and not record['target_still_running']
        assert ctx['pid']==gui['pid'] and ctx['session_id']!=0 and ctx['priority_class']==16384 and ctx['qpa']=='windows'
        assert b'Traceback' not in (folder/'target.stderr').read_bytes()
        proof=verify_pipeline(capture,w['anchors']);proof['runtime_context']=check(phases,'original');proof['cpu_ledger']=verify(cpu,phases)
        assert proof==read(capture/'pipeline_review.json')
        assert cpu['rows'][:len(first['rows'])]==first['rows'] and cpu['calls'][:len(first['calls'])]==first['calls'] and cpu['infer_count']>=first['infer_count']
        assert cpu['infer_count']==len(w['rows']['adapter_calls'])==len(w['rows']['inferences']) and all(r['record']['error'] is None for r in w['rows']['inferences'])
        for call in cpu['calls']:
            row=w['rows']['model_open'][0] if call['kind']=='open' else w['rows']['adapter_calls'][call['ordinal']-1]
            assert row['adapter']==call['adapter'] and row['begin_ns']<=call['begin_ns']<=call['end_ns']<=row['end_ns']
        by={r['label']:r for r in cpu['rows']};consumer=[next(r for r in phases if r['role']=='consumer' and r['ordinal']==n) for n in (59904,65904)]
        interval(by['consumer/59904'],by['consumer/65904'])
        cases[c['id']]=dict(complete=True,full_values=v.values(capture),cpu_proof=proof['cpu_ledger'],consumer_prefix_start=consumer[0]['completed_sample'],consumer_prefix_end=consumer[1]['completed_sample'],consumer_actual_frames_between=consumer[1]['completed_sample']-consumer[0]['completed_sample'],original_return_model_confirmed=proof['original_return_model_confirmed'],final_model_cleanup_confirmed=proof['final_model_cleanup_confirmed'])
    review=dict(all_completed_windows_independently_checked=True,cohort_complete=status['complete'],cases=cases,no_new_capture=True,formal_files_unchanged=collection['audit']['formal_files_unchanged'],actual_load_disturbance_pass=False,field_fix_verified=False,bindings=dict(plan_sha256=sha(HERE/'plan01.json'),archive_sha256=sha(HERE/'evidence01.zip'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(review,f,indent=2)
    print(json.dumps(review,indent=2))
