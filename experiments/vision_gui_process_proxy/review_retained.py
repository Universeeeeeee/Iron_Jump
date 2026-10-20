"""Recheck the immutable plan02 GUI window; never starts or retries a target."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan=read(HERE/'plan03.json');source=Path(plan['retained_window_path']);manifest=read(HERE/plan['retained_manifest_file'])
    assert sha(HERE/plan['retained_manifest_file'])==plan['retained_manifest_sha256']
    assert all(sha(source/name)==digest for name,digest in manifest['files'].items())
    assert sha(source/'plan02.json')==plan['retained_plan_sha256'] and manifest['status']['complete'] is False
    stage=source/'runs01';gui=read(stage/'gui_result.json');vision=read(stage/'vision/result.json');child=read(stage/'vision/child_result.json')
    client=read(stage/'client/status.json');actor=read(stage/'client/actor/result.json');sdk=read(stage/'sdk_backend.json');old_status=read(source/'status01.json')
    assert old_status['steps'][0]['name']=='gui' and old_status['steps'][0]['complete'] and old_status['steps'][0]['returncode']==0
    assert old_status['steps'][1]['name']=='verify' and not old_status['steps'][1]['complete'] and old_status['steps'][1]['returncode']==1
    assert gui['complete'] and not gui['errors'] and vision['complete'] and not vision['errors'] and child['closed'] and not child['errors']
    assert len({gui['pid'],gui['measurement_pid'],vision['child_pid'],sdk['pid']})==4
    assert vision['parent_pid']==gui['pid'] and vision['child_pid']==child['pid'] and vision['child_exitcode']==0 and not vision['child_alive']
    assert not gui['vision_receiver_alive'] and vision['model_closed'] and vision['shared_memory_unlinked']
    assert vision['preview_count']==child['previews']==plan['counts']['preview_frames'] and vision['pose_count']==child['poses']==plan['counts']['inferences']
    assert gui['video_frame_ids']==read(HERE/'selection01.json')['preview_frame_ids'] and gui['pose_ordinals']==list(range(plan['counts']['inferences']))
    assert gui['draws']['valid']>0 and gui['draws']['disabled_calls']==0 and gui['expected_active_publications']==gui['painted_active_publications']
    assert gui['sdk']['start_success'] and gui['sdk']['stop_success'] and gui['sdk']['tracking_decisions']>0 and gui['sdk']['nonzero_speeds']>0 and not gui['sdk']['errors']
    assert sdk['backend']=='simulated_native_SDK' and sdk['no_native_device_opened'] and sdk['serve_returncode']==0 and 'error' not in sdk and sdk['calls']['close']==1
    assert client['complete'] and client['actor_exitcode']==0 and actor['complete'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['writer_stop_confirmed']
    assert gui['semantics']['full_original_report'] and gui['semantics']['full_quality_runtime_state'] and gui['semantics']['raw_fields_exact']
    result=dict(gui_video_model_process_delivery_pass=True,retained_failed_verifier_window_reused=True,target_rerun=False,
        preview_frames=vision['preview_count'],inferences=vision['pose_count'],pose_draws=gui['draws'],sdk_tracking_decisions=gui['sdk']['tracking_decisions'],sdk_nonzero_speeds=gui['sdk']['nonzero_speeds'],
        four_distinct_process_roles=dict(gui=gui['pid'],measurement=gui['measurement_pid'],vision=vision['child_pid'],sdk=sdk['pid']),
        exact_saved_preview_and_pose_oracle=True,original_GUI_pose_draws=True,original_SDK_tracking_decisions=True,
        original_measurement_report_quality_and_raw_exact=True,model_close_child_exit_and_shared_memory_cleanup=True,
        prior_failure_class='offline verifier schema mismatch: absent optional error key',actual_camera_recording_qualified=False,
        timed_latest_only_qualification=False,performance_qualification=False,field_fix_verified=False,
        conclusion='Supports semantic feasibility of the saved-video/model child behind the original experimental GUI and SDK protocol. It is insufficient for timing or backlog benefit.',
        next_step='Freeze timed original/process A/A and AB/BA; require comparable dynamic selection, severe original backlog, FIFO/contact-to-paint limits and unchanged report semantics.',
        bindings=dict(retained_manifest_sha256=plan['retained_manifest_sha256'],retained_archive_sha256=plan['retained_archive_sha256'],retained_plan_sha256=plan['retained_plan_sha256'],review_sha256=sha(Path(__file__))))
    with (HERE/'result03.json').open('x') as target:json.dump(result,target,indent=2)
    print(json.dumps(result,indent=2))
