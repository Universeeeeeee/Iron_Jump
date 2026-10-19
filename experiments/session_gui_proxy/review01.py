"""Offline independent checks of GUI paint/receipt and original saved-session values."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(value):
    value=copy.deepcopy(value)
    for item in (value['report_config_snapshot']['device'],value['report_config_snapshot']['beam_quality']['preflight']):del item['checked_monotonic_ns']
    return value

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    gui=read(raw/'runs/gui_result.json');client=read(raw/'runs/client/status.json');actor=read(raw/'runs/client/actor/result.json');context=read(raw/'runs/gui_context.json')
    assert gui['complete'] and not gui['errors'] and gui['qt_platform']=='windows' and not gui['actor_alive']
    assert context['pid']==gui['pid'] and context['session_id']!=0 and context['priority_class']==16384 and context['qpa']=='windows'
    assert gui['pid']!=gui['actor_pid']==actor['pid']==client['actor_pid']
    assert set(gui['expected_active_publications'])==set(gui['painted_active_publications'])=={int(v) for v in gui['paint_first_ns']}
    assert gui['original_paint_calls']>0 and gui['no_camera_preview'] and gui['no_vision'] and gui['no_sdk']
    assert client['complete'] and client['actor_exitcode']==0 and client['parent_application_receipt_confirmed']
    assert actor['complete'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['writer_stop_confirmed']
    assert [v['sequence'] for v in client['events']]==list(range(1,client['confirmed_sequence']+1))
    assert client['events'][-1]['kind']=='payload_end'
    assert client['receiver']['reader_done'] and not client['receiver']['queued_messages'] and not client['receiver']['incoming_bytes']
    assert actor['outbox']['accepted']==actor['outbox']['write_calls_returned']==client['confirmed_sequence']==client['receiver']['received_packets']
    assert actor['commands_received']==client['command_writer']['accepted']==client['command_writer']['write_calls_returned']
    assert not client['command_writer']['writer_alive'] and client['command_writer']['failure'] is None
    reference=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture';folder=raw/'runs/client/actor'
    report=read(folder/'report.json');assert canonical(report)==canonical(read(reference/'report.json'))
    a=read(folder/'state.json');b=read(reference/'measurement.json')['state']
    for value in (a,b):del value['quality']['preflight']['checked_monotonic_ns']
    assert a==b
    with np.load(folder/'raw_frames.npz') as a,np.load(reference/'raw_frames.npz') as b:
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(a[key],b[key])
        frames=len(a['sample_indices'])
    expected={v['contact_id'] for v in report['walking_summary']['event_publications'] if v['active']};assert expected==set(gui['painted_active_publications'])
    result=dict(original_execution_view_delivery_pass=True,actual_interactive_session=context['session_id'],parent_priority_class=context['priority_class'],
        gui_pid=gui['pid'],actor_pid=actor['pid'],raw_frames_exact=frames,all_active_publication_ids_painted=sorted(expected),original_paint_calls=gui['original_paint_calls'],
        all_actor_sequences_received=client['confirmed_sequence'],command_count=actor['commands_received'],complete_original_report_and_quality_history_exact=True,
        gui_receiver=client['receiver'],all_native_and_python_resources_confirmed=True,
        vision_sdk_clock_handshake_qualified=False,full_production_controller_compatibility=False,real_gui_concurrent_load_or_latency_qualified=False,
        field_fix_verified=False,original_preflight_encoding_failure_retained=True,
        limits=['This is one no-preview/no-model/noSDK saved-input GUI delivery, not performanceAB orcamera-ready timing.','Report travels as verified dict; originalMainWindow report type and engine/config/starttime interfaces are not fully implemented.','PaintID witnesses show originalpaint executed, not pixel-identical history orclinicalsteptruth.'],
        bindings=dict(manifest_sha256=sha(raw/'manifest.json'),plan_sha256=sha(HERE/'plan01.json'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
