"""Strict GUI, child vision, SDK, measurement and report delivery verification."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan=read(HERE/'plan01.json');stage=HERE/'runs01';gui=read(stage/'gui_result.json');vision=read(stage/'vision/result.json')
    child=read(stage/'vision/child_result.json');client=read(stage/'client/status.json');actor=read(stage/'client/actor/result.json');sdk=read(stage/'sdk_backend.json')
    assert all(sha(HERE/name)==digest for name,digest in plan['sources'].items())
    assert gui['complete'] and not gui['errors'] and vision['complete'] and not vision['errors'] and child['closed'] and not child['errors']
    assert len({gui['pid'],gui['measurement_pid'],vision['child_pid'],sdk['pid']})==4
    assert vision['parent_pid']==gui['pid'] and vision['child_pid']==child['pid'] and vision['child_exitcode']==0 and not vision['child_alive']
    assert not gui['vision_receiver_alive']
    assert vision['preview_count']==child['previews']==plan['counts']['preview_frames'] and vision['pose_count']==child['poses']==plan['counts']['inferences']
    assert vision['model_closed'] and vision['shared_memory_unlinked']
    assert gui['video_frame_ids']==read(HERE/'selection01.json')['preview_frame_ids'] and gui['pose_ordinals']==list(range(plan['counts']['inferences']))
    assert gui['draws']['valid']>0 and gui['draws']['disabled_calls']==0 and gui['expected_active_publications']==gui['painted_active_publications']
    assert gui['no_physical_camera_capture'] and not gui['actual_camera_recording_qualified']
    assert gui['sdk']['start_success'] and gui['sdk']['stop_success'] and gui['sdk']['tracking_decisions']>0 and gui['sdk']['nonzero_speeds']>0 and not gui['sdk']['errors']
    assert sdk['backend']=='simulated_native_SDK' and sdk['no_native_device_opened'] and sdk['serve_returncode']==0 and sdk['error'] is None and sdk['calls']['close']==1
    assert client['complete'] and client['actor_exitcode']==0 and actor['complete'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['writer_stop_confirmed']
    assert gui['semantics']['full_original_report'] and gui['semantics']['full_quality_runtime_state'] and gui['semantics']['raw_fields_exact']
    result=dict(gui_video_model_process_delivery_pass=True,preview_frames=vision['preview_count'],inferences=vision['pose_count'],
        four_distinct_process_roles=dict(gui=gui['pid'],measurement=gui['measurement_pid'],vision=vision['child_pid'],sdk=sdk['pid']),
        exact_saved_preview_and_pose_oracle=True,original_GUI_pose_draws=True,original_SDK_tracking_decisions=True,
        original_measurement_report_quality_and_raw_exact=True,model_close_child_exit_and_shared_memory_cleanup=True,
        actual_camera_recording_qualified=False,performance_qualification=False,field_fix_verified=False,
        next_step='Freeze a timed same-input original/process A/A and AB/BA only after this semantic gate; require severe original backlog and unchanged report semantics.',
        bindings={name:sha(path) for name,path in {'plan01.json':HERE/'plan01.json','gui_result.json':stage/'gui_result.json','vision_result.json':stage/'vision/result.json','actor_result.json':stage/'client/actor/result.json'}.items()})
    with (HERE/'result01.json').open('x') as target:json.dump(result,target,indent=2)
    print(json.dumps(result,indent=2))
