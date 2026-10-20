"""Original same-process role/clock/work confirmation; not an IPC or speed pass."""
import json
from pathlib import Path
from clocks import validate_anchors
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
def verify_pipeline(stage,parent_anchors):
    stage=Path(stage);gui=read(stage/'gui_result.json');local=read(stage/'client/actor/result.json');status=read(stage/'client/status.json')
    sdk=read(stage/'sdk_backend.json');work=read(stage/'workload_final.json');final=read(stage/'finalization.json')
    assert gui['complete'] and local['complete'] and status['complete'] and final['metadata_finalization_pass']
    assert gui['backend']=='original' and local['backend']=='original_same_process' and not local['ipc_enabled'] and not status['ipc_enabled']
    assert gui['pid']==local['pid']==gui['measurement_pid']==status['measurement_pid'] and gui['actor_pid'] is None
    assert local['thread_ids']['gui']!=local['thread_ids']['consumer']
    roles=local['prepared_roles'];assert roles['controller_class']=='ui.session_controller.SessionController' and roles['controller_on_gui'] and roles['source_on_measurement_thread'] and roles['quality_on_measurement_thread']
    assert local['reader_stopped'] and local['qt_thread_stopped'] and local['controller_released']
    assert len(local['source_clock_history'])==2 and status['source_clock_history']==local['source_clock_history']
    assert sdk['pid']!=gui['pid'] and sdk['parent_pid']==gui['pid']
    assert sdk['backend']=='real_native_SDK' and not sdk['no_native_device_opened'] and sdk['serve_returncode']==0 and sdk['calls']['close']==1
    assert sdk['error'] is None and {v['name'] for v in sdk['actual_loaded_modules']}=={'libdev.dll','obsbot_c_api.dll'}
    expected={'libdev.dll':'e2648a930fdefe033efe8284fe56f04a55cbef45c0a47763ccca25663b0d66df','obsbot_c_api.dll':'c05b4d551fd5ba178a3bfce2cef9f35c81fd2322c010756c53114d924415bfaf'}
    assert all(v['sha256']==expected[v['name']] for v in sdk['actual_loaded_modules'])
    assert local['source_ready_info']==status['sdk_ready_info']==gui['sdk']['ready_events'][0]
    assert local['source_ready_info']['sdk_pid']==sdk['pid'] and local['source_ready_info']['gui_pid']==gui['pid']
    assert gui['sdk']['start_success'] and gui['sdk']['stop_success'] and not gui['sdk']['errors'] and gui['sdk']['tracking_decisions']>0 and gui['sdk']['nonzero_speeds']>0
    rows=work['rows'];assert len(rows['model_open'])==len(rows['model_close'])==1 and rows['inferences'] and not rows['callback_errors']
    assert {r['pid'] for r in rows['control_lifecycle'] if r['event']=='started'}=={sdk['pid']}
    assert gui['camera']['decoded_frames']>0 and gui['video_frame_ids'] and gui['draws']['valid']>0 and gui['draws']['disabled_calls']==0
    assert gui['no_physical_camera_capture'] and gui['saved_preview_replay'] and gui['expected_active_publications']==gui['painted_active_publications'] and gui['original_paint_calls']>0
    import numpy as np
    with np.load(stage/'client/actor/raw_frames.npz') as z:first_receipt=int(z['received_ns'][0])
    assert local['source_ready_info']['observed_ns']<=local['source_clock_history'][0]['anchor_ns']<=first_receipt
    clocks=validate_anchors(parent_anchors+local['process_clock_anchors']+sdk['clock_anchors'])
    return dict(original_same_process_gui_delivery_pass=True,original_controller_and_qthread=True,no_measurement_ipc=True,gui_and_measurement_pid=gui['pid'],sdk_pid=sdk['pid'],thread_ids=local['thread_ids'],qpc=clocks,
        actual_model_calls=len(rows['inferences']),actual_video_frames=len(gui['video_frame_ids']),original_return_model_confirmed=final['application_return_model_confirmed'],final_model_cleanup_confirmed=True,
        matched_performance_comparison_pass=False,actual_load_disturbance_pass=False,field_fix_verified=False)
