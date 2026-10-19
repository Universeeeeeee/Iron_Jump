"""Independent archive and complete values review of every attempted fixed case."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_vision'))
from verify_pipeline02 import verify_pipeline as verify_child
sys.path.insert(0,str(ROOT/'experiments/session_local_baseline'))
from pipeline_review import verify_pipeline as verify_original
sys.path.insert(0,str(HERE))
from context import check
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json');collection=read(HERE/'collection01.json')
    assert sha(HERE/'evidence01.zip')==collection['archive_sha256'] and all(sha(archive/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan02.json');assert all(sha(archive/n)==v for n,v in plan['sources'].items()) and sha(archive/'plan02.json')==sha(HERE/'plan02.json')
    spec=importlib.util.spec_from_file_location('prior_value_review',ROOT/'experiments/session_gui_vision/review02.py');values=importlib.util.module_from_spec(spec);spec.loader.exec_module(values)
    stage=archive/'runs/cohort01';status=read(stage/'status.json');result=read(HERE/'result01.json');reviews={}
    for case in plan['cases']:
        folder=stage/case['id']
        if not (folder/'record.json').exists():
            assert result['cases'][case['id']]['not_attempted'];reviews[case['id']]=dict(not_attempted=True);continue
        record=read(folder/'record.json');capture=folder/'capture'
        if not record.get('complete'):
            assert result['cases'][case['id']]['failed'];reviews[case['id']]=dict(failed=True,errors=record['errors'],all_available_files_manifest_bound=True);continue
        assert record['target_returncode']==0 and not record['target_still_running'] and not record['errors']
        assert b'Traceback' not in (folder/'target.stderr').read_bytes()
        gui=read(capture/'gui_result.json');context=read(capture/'gui_context.json');work=read(capture/'workload_final.json')
        assert context['pid']==gui['pid'] and context['session_id']!=0 and context['priority_class']==16384 and context['qpa']=='windows'
        verify=verify_original if case['backend']=='original' else verify_child
        review=verify(capture,work['anchors']);review['runtime_context']=check(read(capture/'phase_context.json'),case['backend'])
        assert review==read(capture/'pipeline_review.json')
        reviews[case['id']]=dict(complete=True,full_values=values.values(capture),runtime_context=review['runtime_context'],original_return_model_confirmed=review['original_return_model_confirmed'],final_model_cleanup_confirmed=review['final_model_cleanup_confirmed'])
    assert result['all_cases_complete']==status['complete']
    if not status['complete']:assert result['symptom_decision'] is None
    review=dict(archive_and_plan_exact=True,all_attempted_cases_independently_reviewed=True,all_cases_complete=status['complete'],cases=reviews,
        no_window_replaced=True,no_new_capture=True,actual_load_disturbance_pass=False,field_fix_verified=False,
        bindings=dict(plan_sha256=sha(HERE/'plan02.json'),archive_sha256=sha(HERE/'evidence01.zip'),result_sha256=sha(HERE/'result01.json'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(review,f,indent=2)
    print(json.dumps(dict(complete=status['complete'],attempted=len(status['cases']),independent_full_value_cases=sum(v.get('complete',False) for v in reviews.values()),archive_and_plan_exact=True)))
