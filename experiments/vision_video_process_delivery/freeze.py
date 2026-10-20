"""Freeze one same-process reference and one child delivery window before model work."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    old=json.loads((ROOT/'experiments/session_gui_comparison/plan02.json').read_text())
    selection=json.loads((HERE/'selection01.json').read_text())
    sources={p.name:sha(p) for p in sorted(HERE.iterdir()) if p.suffix=='.py'}
    plan=dict(
        input_root=old['input_root'],
        media_sha256={k:old['input_sha256'][k] for k in ('camera.csv','camera.mjpg')},
        model_path='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/models/pose_landmarker_full.task',
        model_sha256=old['existing_sources']['models/pose_landmarker_full.task'],
        selection_sha256=sha(HERE/'selection01.json'),
        reference_archive_sha256=sha(ROOT/'experiments/session_gui_comparison/evidence01.zip'),
        reference_source_sha256=selection['source_sha256'],
        counts=selection['counts'],
        shared_frame_capacity_bytes=8_388_608,
        sources=sources,
        budget='Exactly one same-process reference andone child-process delivery. Stop onidentity/runtime/cleanup failure; no replacement, performance claim orGUI/device run.',
        acceptance='Every preview source/decoded pixel identity andevery full pose hash must match; actual childPID, message order, shared-memory acknowledgement, close/exit/unlink all required.',
        scope='Saved video decode plus original PreviewAdapter only. No camera recording,GUI,SDK,USB,human orformal change.',
        performance_qualification=False,field_fix_verified=False)
    plan['supersedes_preparation_plan']='plan01.json; no preflight, model or media work was started under it.'
    with (HERE/'plan02.json').open('x') as f:json.dump(plan,f,indent=2)
    print(json.dumps(dict(sources=len(sources),counts=plan['counts'])))
