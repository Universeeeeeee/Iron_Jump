"""One fixed case through the shared GUI; original model and simulated hardware only."""
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]

def main():
    for folder in (ROOT,ROOT/'experiments/gil_gui_calibration',ROOT/'experiments/gil_workload_finalization',ROOT/'experiments/session_gui_vision',ROOT/'experiments/session_local_baseline',ROOT/'experiments/session_gui_comparison',HERE):sys.path.insert(0,str(folder))
    from gate import require_gate
    plan=require_gate(HERE);name=sys.argv[sys.argv.index('--case')+1];case=next(v for v in plan['cases'] if v['id']==name)
    stage=HERE/'runs/cohort01'/name/'capture';case_plan=dict(plan,backend=case['backend'])
    from camera.control_service import CameraControlService
    import links
    original=CameraControlService.__init__
    def control_init(control,*args,**kwargs):
        if kwargs.get('command') is not None:raise ValueError('Unexpected SDK override')
        kwargs['command']=[sys.executable,'-u',str(ROOT/'experiments/session_gui_vision/fake_sdk.py'),str(stage/'sdk_backend.json')]
        original(control,*args,**kwargs);links.attach(control)
    CameraControlService.__init__=control_init;links.sdk_patch_installed=True
    import local
    from local_failure import RetainingLocal
    original_local=local.LocalSession;local.LocalSession=RetainingLocal
    if case['backend']=='isolated':
        import client
        from actor_context import run_actor_context
        client.run_actor=run_actor_context
    from atomic_io03 import write
    from clocks import native_anchor
    from finalize import RetainedAudit,finalize
    from context import Phases,restore,check
    rows=[];observer=Phases(rows,plan['context_checkpoints'],clock=lambda:None if links.client is None else links.client.clock)
    audit=RetainedAudit();anchors=[native_anchor()];contexts=[]
    from install import Installation,verify as verify_install
    installation=Installation(ROOT)
    try:
        audit.install();contexts=observer.install(('gui','model','consumer') if case['backend']=='original' else ('gui','model'))
        from gui import run
        installation.start()
        raise SystemExit(run(case_plan,stage))
    finally:
        installation_result=installation.close()
        if stage.exists():write(stage/'bridge_safety.json',installation_result)
        exc=sys.exc_info()[1];outcome=dict(success=exc is None or isinstance(exc,SystemExit) and exc.code in (0,None),exception_type=None if exc is None else type(exc).__name__,exit_code=getattr(exc,'code',None),error=None if exc is None else repr(exc))
        if stage.exists():
            final=finalize(audit,lambda name,value:write(stage/name,value),90,outcome)
            anchors.append(native_anchor());last=json.loads((stage/'observer_tail.json').read_text(encoding='utf-8'));last['anchors']=anchors;write(stage/'workload_final.json',last)
            if case['backend']=='isolated' and (stage/'client/actor/phase_context.json').exists():rows+=json.loads((stage/'client/actor/phase_context.json').read_text())
            write(stage/'phase_context.json',rows)
            try:
                if case['backend']=='original':from pipeline_review import verify_pipeline
                else:from verify_pipeline02 import verify_pipeline
                review=verify_pipeline(stage,anchors);review['runtime_context']=check(rows,case['backend'])
                formal=json.loads((ROOT/plan['formal_baseline_manifest']).read_text(encoding='utf-8-sig'))['baseline_files']
                review['preview_bridge_safety']=verify_install(installation_result,review)
            except BaseException as failure:
                write(stage/'pipeline_failure.json',dict(error=repr(failure),traceback=__import__('traceback').format_exc()));raise
            write(stage/'pipeline_review.json',review)
            if not final['metadata_finalization_pass']:raise RuntimeError('Model finalization failed')
        restore(contexts);CameraControlService.__init__=original;local.LocalSession=original_local
if __name__=='__main__':main()
