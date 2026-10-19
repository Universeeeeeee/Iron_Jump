"""Saved-input full GUI entry; fake hardware is mandatory before any control construction."""
import json
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]

def main():
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
    sys.path.insert(0,str(ROOT/'experiments/gil_workload_finalization'));sys.path.insert(0,str(HERE))
    from gate import require_gate
    require_gate(HERE)
    from camera.control_service import CameraControlService
    import links
    original=CameraControlService.__init__
    def control_init(control,*args,**kwargs):
        if kwargs.get('command') is not None:raise ValueError('Unexpected SDK override')
        kwargs['command']=[sys.executable,'-u',str(HERE/'fake_sdk.py'),str(HERE/'runs/sdk_backend.json')]
        original(control,*args,**kwargs);links.attach(control)
    CameraControlService.__init__=control_init;links.sdk_patch_installed=True
    from atomic_io03 import write
    from clocks import native_anchor
    from finalize import RetainedAudit,finalize
    audit=RetainedAudit();anchors=[native_anchor()];stage=HERE/'runs';outcome=None
    try:
        audit.install();runpy.run_path(str(HERE/'gui01.py'),run_name='__main__')
    finally:
        exc=sys.exc_info()[1]
        outcome=dict(success=exc is None or isinstance(exc,SystemExit) and exc.code in (0,None),exception_type=None if exc is None else type(exc).__name__,exit_code=getattr(exc,'code',None),error=None if exc is None else repr(exc))
        if stage.exists():
            final=finalize(audit,lambda name,value:write(stage/name,value),90,outcome)
            anchors.append(native_anchor());last=json.loads((stage/'observer_tail.json').read_text(encoding='utf-8'))
            last['anchors']=anchors;write(stage/'workload_final.json',last)
            try:
                from verify_pipeline import verify_pipeline
                review=verify_pipeline(stage,anchors)
            except BaseException as failure:
                write(stage/'pipeline_failure.json',dict(error=repr(failure),exception_type=type(failure).__name__))
                raise
            write(stage/'pipeline_review.json',review)
            if not final['metadata_finalization_pass']:raise RuntimeError('Model finalization failed')
        CameraControlService.__init__=original

if __name__=='__main__':main()
