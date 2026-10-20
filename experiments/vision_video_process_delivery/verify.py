"""Verify exact saved-video pixels and complete pose identity across process boundary."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    p=read(HERE/'plan05.json');runs=HERE/'runs';status=read(runs/'status.json')
    assert status['complete'] and not status['errors'] and len(status['steps'])==2
    assert all(v['complete'] and not v['errors'] and not v['target_still_running'] and v['returncode']==0 for v in status['steps'])
    assert all(sha(HERE/n)==v for n,v in p['sources'].items()) and sha(HERE/'selection01.json')==p['selection_sha256']
    reference=read(runs/'reference01.json');result=read(runs/'process01/result.json');child=read(runs/'process01/child_result.json');controller=read(runs/'process01/controller.json')
    assert reference['complete'] and not reference['errors'] and reference['model_closed']
    assert len(reference['previews'])==p['counts']['preview_frames'] and len(reference['inferences'])==p['counts']['inferences']
    assert result['complete'] and not result['errors'] and result['preview_count']==len(reference['previews']) and result['pose_count']==len(reference['inferences'])
    assert result['parent_pid']==controller['parent_pid']!=controller['child_pid']==result['child_pid']==child['pid']
    assert result['child_exitcode']==0 and not result['child_alive'] and result['shared_memory_unlinked']
    assert child['closed'] and not child['errors'] and child['preview_messages']==p['counts']['preview_frames'] and child['inference_messages']==p['counts']['inferences']
    out=dict(saved_video_and_model_process_delivery_pass=True,preview_frames=p['counts']['preview_frames'],inferences=p['counts']['inferences'],
        exact_source_encoded_and_decoded_pixel_identity=True,complete_pose_hash_identity=True,actual_separate_child_PID=True,
        shared_memory_acknowledgement_and_unlink=True,model_close_and_child_exit=True,
        actual_camera_recording_qualified=False,GUI_SDK_tracking_qualified=False,performance_qualification=False,field_fix_verified=False,
        next_step='Integrate the same child protocol behind an experiment-only camera/vision proxy; verify actual GUI preview,SDK decisions,recording andfull reports before any performance A/B.',
        bindings={f.name:sha(f) for f in (Path(__file__),HERE/'plan05.json',HERE/'selection01.json',runs/'reference01.json',runs/'process01/result.json')})
    with (HERE/'result01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
