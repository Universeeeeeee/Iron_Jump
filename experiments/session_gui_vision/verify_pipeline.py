"""Same-window role, clock, ready, model/SDK work and cleanup checks; no speed claim."""
import json
from pathlib import Path
from clocks import validate_anchors

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def verify_pipeline(stage,parent_anchors):
    stage=Path(stage);gui=read(stage/'gui_result.json');client=read(stage/'client/status.json');actor=read(stage/'client/actor/result.json')
    sdk=read(stage/'sdk_backend.json');work=read(stage/'workload_final.json');final=read(stage/'finalization.json')
    assert gui['complete'] and client['complete'] and actor['complete'] and final['metadata_finalization_pass']
    assert gui['sdk']['start_success'] and gui['sdk']['stop_success'] and not gui['sdk']['errors']
    assert gui['sdk']['tracking_decisions']>0 and gui['sdk']['nonzero_speeds']>0
    assert sdk['backend']=='simulated_native_SDK' and sdk['no_native_device_opened'] and sdk['serve_returncode']==0 and sdk['calls']['close']==1
    assert len({gui['pid'],actor['pid'],sdk['pid']})==3 and sdk['parent_pid']==gui['pid']
    assert actor['source_ready_info']['sdk_pid']==sdk['pid'] and actor['source_ready_info']['gui_pid']==gui['pid']
    assert actor['source_ready_info']==client['sdk_ready_info']==gui['sdk']['ready_events'][0]
    assert actor['source_clock_revisions']==len(actor['source_clock_history'])==2
    assert actor['source_clock_history']==client['source_clock_history'] and client['actor_ready_anchor']==actor['process_clock_anchors'][0]
    rows=work['rows'];assert len(rows['model_open'])==len(rows['model_close'])==1 and rows['inferences'] and not rows['callback_errors']
    sdk_pids={v['pid'] for v in rows['control_lifecycle'] if v['event']=='started'};assert sdk_pids=={sdk['pid']}
    assert gui['camera']['decoded_frames']>0 and len(gui['video_frame_ids'])>0 and gui['draws']['valid']>0 and gui['draws']['disabled_calls']==0
    assert gui['no_physical_camera_capture'] and gui['saved_preview_replay']
    clock=validate_anchors(parent_anchors+actor['process_clock_anchors']+sdk['clock_anchors'])
    # Receipt and clock facts come from the child witness and retained actual raw values.
    import numpy as np
    with np.load(stage/'client/actor/raw_frames.npz') as z:first_receipt=int(z['received_ns'][0])
    assert actor['source_ready_info']['observed_ns']<=actor['source_clock_history'][0]['anchor_ns']<=first_receipt
    return dict(gui_vision_sdk_delivery_pass=True,three_distinct_process_roles=dict(gui=gui['pid'],measurement=actor['pid'],sdk=sdk['pid']),
        qpc=clock,source_revisions=2,actual_model_calls=len(rows['inferences']),actual_video_frames=len(gui['video_frame_ids']),
        original_return_model_confirmed=final['application_return_model_confirmed'],final_model_cleanup_confirmed=True,
        dynamic_work_policy='Actual frame choices andwork counts retained, notposthoc matched to anotherwindow.',
        actual_load_disturbance_pass=False,performance_or_field_fix_qualification=False)
