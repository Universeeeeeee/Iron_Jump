"""Independently reconstruct the frozen dynamic selection directly from the retained archive."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sha_bytes=lambda value:hashlib.sha256(value).hexdigest()

if __name__=='__main__':
    plan=json.loads((HERE/'plan02.json').read_text())
    selection=json.loads((HERE/'selection01.json').read_text())
    archive=ROOT/'experiments/session_gui_comparison/evidence01.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==plan['reference_archive_sha256']
    names=dict(gui='runs/cohort01/aa01/capture/gui_result.json',work='runs/cohort01/aa01/capture/workload_final.json')
    with zipfile.ZipFile(archive) as z:
        raw={key:z.read(name) for key,name in names.items()}
    assert sha_bytes(raw['gui'])==selection['source_sha256']['gui_result.json']
    assert sha_bytes(raw['work'])==selection['source_sha256']['workload_final.json']
    gui=json.loads(raw['gui']);work=json.loads(raw['work'])['rows']
    assert gui['backend']=='original' and gui['complete']
    assert selection['preview_frame_ids']==gui['video_frame_ids']
    assert selection['counts']==dict(preview_frames=gui['camera']['decoded_frames'],
        inferences=len(work['inferences']),stale_frames_skipped=gui['camera']['stale_frames_skipped'])
    assert len(work['inferences'])==len(work['adapter_calls'])==len(selection['inferences'])
    preview=set(selection['preview_frame_ids']);previous_timestamp=None
    for ordinal,(expected,inference,call) in enumerate(zip(selection['inferences'],work['inferences'],work['adapter_calls'])):
        record=inference['record'];meta=record['metadata']
        actual=dict(ordinal=ordinal,frame_index=meta['frame_index'],sample_time_s=meta['sample_time_s'],
            timestamp_ms=call['timestamp_ms'],has_pose=record['has_pose'],error=record['error'],shape=call['shape'],dtype=call['dtype'])
        assert actual==expected and actual['frame_index'] in preview
        assert previous_timestamp is None or actual['timestamp_ms']>previous_timestamp
        assert inference['tid']==call['tid'] and call['begin_ns']<=call['end_ns']
        previous_timestamp=actual['timestamp_ms']
    output=dict(reference_archive_exact=True,source_member_hashes_exact=True,preview_sequence_exact=True,
        all_inference_records_reconstructed_exactly=True,strict_inference_timestamps=True,
        actual_counts=selection['counts'],workload_started=False,
        bindings=dict(archive_sha256=plan['reference_archive_sha256'],selection_sha256=plan['selection_sha256'],
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    with (HERE/'selection_verification01.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output,indent=2))
