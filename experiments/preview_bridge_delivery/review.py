"""Review the single saved-model safety window; never score latency benefit."""
import hashlib
import json
from pathlib import Path
import zipfile
from install import verify

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');meta=read(HERE/'transport01.json');archive=HERE/'runs/evidence01.zip'
    assert sha(archive)==meta['sha256'] and all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert len(p['cases'])==1 and p['process_budget']==1 and not p['performance_AB']
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('manifest01.json'))
        assert len(manifest['files'])==meta['manifest_files']
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in manifest['files'].items())
        assert all(n+'/' in z.namelist() for n in meta['locks'])
        assert all(manifest['files'][n]==v for n,v in p['sources'].items())
        prefix='runs/cohort01/safety01/capture/'
        data=json.loads(z.read(prefix+'bridge_safety.json'));pipeline=json.loads(z.read(prefix+'pipeline_review.json'))
        verify(data,pipeline)
        record=json.loads(z.read('runs/cohort01/safety01/record.json'));process=json.loads(z.read('task01.status.json'))
        assert record['complete'] and not record['errors'] and not record['target_still_running'] and record['target_returncode']==0
        assert all(record['semantics'][k] for k in ('full_original_report','full_quality_runtime_state','raw_fields_exact'))
        assert pipeline['original_same_process_gui_delivery_pass'] and pipeline['final_model_cleanup_confirmed']
        assert pipeline['actual_model_calls']>0 and pipeline['actual_video_frames']>0
        assert pipeline['sdk_pid']!=pipeline['gui_and_measurement_pid']
        assert process['observation_complete'] and process['native_exit_code']==process['managed_exit_code']==0
        workload=json.loads(z.read(prefix+'workload_final.json'))
        assert not workload['rows']['callback_errors']
    result=dict(saved_GUI_safety_pass=True,preview_calls=data['calls'],pose_preview_calls=data['pose_calls'],
        real_model_calls=pipeline['actual_model_calls'],saved_video_frames=pipeline['actual_video_frames'],
        original_report_state_raw_exact=record['semantics'],restored=data['method_restored'],
        no_recorded_bridge_or_model_callback_errors=True,final_model_cleanup_confirmed=True,native_exit_code=0,
        real_native_SDK_qualified=False,performance_AB_started=False,severe_baseline_reproduction_evaluated=False,
        limitations=['One finite safety window cannot prove arbitrary callback/lifetime schedules safe.',
            'Runtime safety counters/checks add overhead; this is not the candidate performance fixture.',
            'Native OBSBOT service is simulated. Real native SDK still needs qualification before causalAB.',
            'Synthetic full pixels were verified separately; this window does not compare dynamic model pixel histories between modes.',
            'Original application-return model status is not rewritten by the confirmed later cleanup.',
            'No CPU/GIL share, severe-backlog benefit, 3%/1% calibration or formal repair follows.'],
        root_cause_or_fix_complete=False,
        bindings={v.name:sha(v) for v in (Path(__file__),HERE/'plan01.json',HERE/'transport01.json',HERE/'bridge_safety01.json',HERE/'pipeline_review01.json',HERE/'record01.json',HERE/'task_status01.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
