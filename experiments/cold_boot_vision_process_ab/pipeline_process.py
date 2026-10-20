"""Same-process measurement and GUI with timed video/model child delivery checks."""
import json
from pathlib import Path
from clocks import validate_anchors

read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def verify_pipeline(stage,parent_anchors,boundary):
    stage=Path(stage);gui=read(stage/'gui_result.json');local=read(stage/'client/actor/result.json');status=read(stage/'client/status.json')
    sdk=read(stage/'sdk_backend.json');final=read(stage/'finalization.json');vision=boundary['proxy']
    assert gui['complete'] and local['complete'] and status['complete']
    assert gui['backend']=='original' and local['backend']=='original_same_process' and not local['ipc_enabled'] and not status['ipc_enabled']
    assert gui['pid']==local['pid']==gui['measurement_pid']==status['measurement_pid'] and gui['actor_pid'] is None
    assert local['thread_ids']['gui']!=local['thread_ids']['consumer'] and local['reader_stopped'] and local['qt_thread_stopped'] and local['controller_released']
    assert len(local['source_clock_history'])==2 and status['source_clock_history']==local['source_clock_history']
    assert vision['complete'] and not vision['errors'] and vision['parent_pid']==gui['pid'] and vision['child_pid'] not in (gui['pid'],sdk['pid'])
    assert vision['child_exitcode']==0 and not vision['child_alive'] and vision['model_closed'] and vision['shared_memory_unlinked']
    assert vision['preview_count']==len(vision['preview_ids'])==gui['camera']['decoded_frames']==len(gui['video_frame_ids']) and vision['preview_ids']==gui['video_frame_ids']
    assert vision['inference_count']==len(vision['inference_ids'])>0 and vision['snapshot_messages']>0
    assert sdk['pid']!=gui['pid'] and sdk['parent_pid']==gui['pid'] and sdk['backend']=='real_native_SDK' and not sdk['no_native_device_opened']
    assert sdk['serve_returncode']==0 and sdk['error'] is None and sdk['calls']['close']==1
    expected={'libdev.dll':'e2648a930fdefe033efe8284fe56f04a55cbef45c0a47763ccca25663b0d66df','obsbot_c_api.dll':'c05b4d551fd5ba178a3bfce2cef9f35c81fd2322c010756c53114d924415bfaf'}
    assert {v['name'] for v in sdk['actual_loaded_modules']}==set(expected) and all(v['sha256']==expected[v['name']] for v in sdk['actual_loaded_modules'])
    assert local['source_ready_info']==status['sdk_ready_info']==gui['sdk']['ready_events'][0]
    assert gui['sdk']['start_success'] and gui['sdk']['stop_success'] and not gui['sdk']['errors'] and gui['sdk']['tracking_decisions']>0 and gui['sdk']['nonzero_speeds']>0
    assert gui['draws']['valid']>0 and gui['draws']['disabled_calls']==0 and gui['no_physical_camera_capture'] and gui['saved_preview_replay']
    assert gui['expected_active_publications']==gui['painted_active_publications'] and gui['original_paint_calls']>0
    import numpy as np
    with np.load(stage/'client/actor/raw_frames.npz') as values:first_receipt=int(values['received_ns'][0])
    assert local['source_ready_info']['observed_ns']<=local['source_clock_history'][0]['anchor_ns']<=first_receipt
    clocks=validate_anchors(parent_anchors+local['process_clock_anchors']+sdk['clock_anchors'])
    return dict(timed_video_model_process_delivery_pass=True,original_controller_and_qthread=True,no_measurement_ipc=True,
        gui_and_measurement_pid=gui['pid'],vision_pid=vision['child_pid'],sdk_pid=sdk['pid'],qpc=clocks,
        actual_model_calls=vision['inference_count'],actual_video_frames=vision['preview_count'],stale_frames_skipped=vision['stale_frames_skipped'],
        parent_model_observer_not_applicable=not final['metadata_finalization_pass'],final_model_cleanup_confirmed=True,
        actual_load_disturbance_pass=False,performance_or_field_fix_qualification=False)
