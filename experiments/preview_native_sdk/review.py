"""Independent archive inspection of the original native SDK safety delivery."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');meta=read(HERE/'transport01.json');archive=HERE/'runs/evidence01.zip'
    assert sha(archive)==meta['sha256'] and all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert p['real_native_SDK'] and not p['performance_AB'] and p['process_budget']==1
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('manifest01.json'))
        assert len(manifest['files'])==meta['manifest_files']
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in manifest['files'].items())
        assert all(n+'/' in z.namelist() for n in meta['locks'])
        assert all(manifest['files'][n]==v for n,v in p['sources'].items())
        prefix='runs/cohort01/native_safety01/capture/'
        sdk=json.loads(z.read(prefix+'sdk_backend.json'));gui=json.loads(z.read(prefix+'gui_result.json'))
        bridge=json.loads(z.read(prefix+'bridge_safety.json'));pipeline=json.loads(z.read(prefix+'pipeline_review.json'))
        record=json.loads(z.read('runs/cohort01/native_safety01/record.json'));process=json.loads(z.read('task01.status.json'))
        work=json.loads(z.read(prefix+'workload_final.json'))
        assert sdk['backend']=='real_native_SDK' and not sdk['no_native_device_opened'] and sdk['error'] is None and sdk['serve_returncode']==0
        assert sdk['parent_pid']==gui['pid'] and sdk['pid']!=gui['pid']
        assert {v['name'] for v in sdk['actual_loaded_modules']}=={'libdev.dll','obsbot_c_api.dll'}
        assert all(v['sha256']==p['existing_sources']['camera/bin/'+v['name']] for v in sdk['actual_loaded_modules'])
        assert sdk['calls']['init']==sdk['calls']['close']==sdk['calls']['disable_ai']==1 and sdk['calls']['set_speed']>0
        assert gui['sdk']['start_success'] and gui['sdk']['stop_success'] and not gui['sdk']['errors']
        assert gui['sdk']['nonzero_speeds']>0 and gui['sdk']['tracking_decisions']>0
        assert gui['no_physical_camera_capture'] and gui['complete']
        assert bridge['calls']>0 and bridge['pose_calls']>0 and not bridge['errors'] and bridge['depth_at_restore']==0
        assert bridge['method_restored'] and bridge['installed_method_unchanged'] and bridge['gui_tid']==pipeline['thread_ids']['gui']
        assert not work['rows']['callback_errors'] and pipeline['final_model_cleanup_confirmed']
        assert record['complete'] and not record['target_still_running'] and record['target_returncode']==0
        assert all(record['semantics'][k] for k in ('full_original_report','full_quality_runtime_state','raw_fields_exact'))
        assert process['observation_complete'] and process['native_exit_code']==process['managed_exit_code']==0
    result=dict(real_native_SDK_safety_window_pass=True,GUI_pid=gui['pid'],SDK_pid=sdk['pid'],actual_loaded_modules=sdk['actual_loaded_modules'],
        native_successful_call_counts=sdk['calls'],SDK_stop_and_close_confirmed=True,preview_calls=bridge['calls'],pose_preview_calls=bridge['pose_calls'],
        real_model_calls=pipeline['actual_model_calls'],saved_video_frames=pipeline['actual_video_frames'],full_original_semantics=record['semantics'],
        model_final_cleanup_confirmed=True,method_restored=True,process_exit_code=0,
        prior_subchecker_real_native_SDK_flag_scope='Reused bridge-only checker conservatively returns false; this archive review independently verifies native loaded images, replies, close and PID.',
        limits=['One safety window is not proof of arbitrary reentry/lifecycle schedules.','Passive SDK and bridge bookkeeping add overhead; not a performance AB fixture.',
            'No severe-baseline reproduction orlatency benefit has been evaluated.','No old native-stack or3%/1% gate is upgraded.'],
        performance_AB_started=False,root_cause_or_fix_complete=False,
        bindings={v.name:sha(v) for v in (Path(__file__),HERE/'plan01.json',HERE/'transport01.json',HERE/'sdk_backend01.json',HERE/'pipeline_review01.json',HERE/'bridge_safety01.json',HERE/'record01.json',HERE/'task_status01.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
