"""One real-widget semantic control, no timing/performance endpoints."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    reference=json.loads((HERE/'reference_plan01.json').read_text())
    modules=reference['exact_modules'];assert all(sha(Path(n))==v for n,v in modules.items())
    root=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01')
    formal=json.loads((root/'experiments/gil_gui_analysis/stack_plan01.json').read_text())['baseline_files']
    names=['ui/annotation_canvas.py','ui/embedded_camera_panel.py','camera/video_annotations.py','vision/pose_overlay.py','vision/foot_reference.py']
    assert all(sha(root/n)==formal[n] for n in names)
    def case(name,**options):
        row=dict(id=name,image=True,pose=False,low=False,mirrored=False,angles=False,interval=False,draft=False,drag=False,integrated=False)
        row.update(options);return row
    cases=[case('empty',image=False),case('image_only'),case('pose',pose=True),case('low_quality',pose=True,low=True),
        case('mirrored',pose=True,mirrored=True),case('angle_drag_draft',angles=True,drag=True,draft=True),
        case('interval',interval=True),case('combined',pose=True,angles=True,interval=True,draft=True,integrated=True)]
    own=['derive.py','bridge.py','binding_review01.json','control.py','check.py','test_derive.py','freeze.py','reference_plan01.json','process_helper.ps1','launch01.ps1']
    plan=dict(base_commit='d9fdbe9ef5126413b6009c0c162d1c6727cc766b',project_root=root.as_posix(),formal_sources={n:formal[n] for n in names},
        sources={n:sha(HERE/n) for n in own},exact_modules=modules,cases=cases,process_budget=1,retries=0,
        process_QT_SCALE_FACTOR='1.25',observed_widget_size=[784,441],source_image_size=[640,360],pixmap_dpr=1,
        maximum_render_calls=20,performance_endpoints=[],performance_AB=False,field_fix_verified=False,
        scope='Original AnnotationCanvas plus an experimental subclass with one base-call AST replacement. Synthetic RGB and dataclass pose only; no model, live SDK/device, human, USB or Run.')
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    print(json.dumps(plan,indent=2))
