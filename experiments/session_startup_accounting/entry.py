"""Original shared GUI with bounded passive startup CPU bookkeeping only."""
import ctypes
import json
from pathlib import Path
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def main():
    assert ctypes.sizeof(ctypes.c_void_p)==8,'Unified Win64 ABI required'
    for p in (ROOT,ROOT/'experiments/gil_gui_calibration',ROOT/'experiments/gil_workload_finalization',ROOT/'experiments/session_gui_vision',ROOT/'experiments/session_local_baseline',ROOT/'experiments/session_gui_comparison',HERE):sys.path.insert(0,str(p))
    from gate import require_gate
    plan=require_gate(HERE);name=sys.argv[sys.argv.index('--case')+1];case=next(v for v in plan['cases'] if v['id']==name);assert case['backend']=='original'
    stage=HERE/'runs/cohort01'/name/'capture';case_plan=dict(plan,backend='original')
    from camera.control_service import CameraControlService
    import links
    original_control=CameraControlService.__init__
    def control_init(control,*args,**kwargs):
        if kwargs.get('command') is not None:raise ValueError('Unexpected SDK override')
        kwargs['command']=[sys.executable,'-u',str(ROOT/'experiments/session_gui_vision/fake_sdk.py'),str(stage/'sdk_backend.json')]
        original_control(control,*args,**kwargs);links.attach(control)
    CameraControlService.__init__=control_init;links.sdk_patch_installed=True
    import local
    from local_failure import RetainingLocal
    original_local=local.LocalSession;local.LocalSession=RetainingLocal
    from ledger import NativeReader,Ledger,verify
    init=time.perf_counter_ns();reader=NativeReader();reader_init_ns=time.perf_counter_ns()-init
    cpu=Ledger(reader);cpu_patches=cpu.install()
    from atomic_io03 import write
    from clocks import native_anchor
    from finalize import RetainedAudit,finalize
    from context import Phases,restore,check
    from runtime_context import snapshot
    phase_rows=[]
    def context_reader(role,ordinal):
        begin=time.perf_counter_ns();r=snapshot(role,ordinal);cpu.capture(f'{role}/{ordinal}');r['cpu_hook_total_ns']=time.perf_counter_ns()-begin;return r
    observer=Phases(phase_rows,plan['context_checkpoints'],clock=lambda:None if links.client is None else links.client.clock,reader=context_reader)
    audit=RetainedAudit();anchors=[native_anchor()];contexts=[]
    try:
        audit.install();contexts=observer.install(('gui','model','consumer'))
        from gui import run
        raise SystemExit(run(case_plan,stage))
    finally:
        exc=sys.exc_info()[1];outcome=dict(success=exc is None or isinstance(exc,SystemExit) and exc.code in (0,None),exception_type=None if exc is None else type(exc).__name__,exit_code=getattr(exc,'code',None),error=None if exc is None else repr(exc))
        try:
            if stage.exists():
                first_cpu=cpu.payload();write(stage/'cpu_application_return.json',first_cpu)
                final=finalize(audit,lambda n,v:write(stage/n,v),90,outcome)
                anchors.append(native_anchor());last=json.loads((stage/'observer_tail.json').read_text(encoding='utf-8'));last['anchors']=anchors;write(stage/'workload_final.json',last)
                data=cpu.payload();assert data['rows'][:len(first_cpu['rows'])]==first_cpu['rows'] and data['calls'][:len(first_cpu['calls'])]==first_cpu['calls'] and data['infer_count']>=first_cpu['infer_count'];data['reader_initialization_ns']=reader_init_ns;write(stage/'cpu_ledger.json',data);write(stage/'phase_context.json',phase_rows)
                try:
                    from pipeline_review import verify_pipeline
                    review=verify_pipeline(stage,anchors);review['runtime_context']=check(phase_rows,'original');review['cpu_ledger']=verify(data,phase_rows)
                    assert cpu.infer_count==len(last['rows']['adapter_calls'])
                    from delta import interval
                    for role in ('gui','model','consumer'):
                        a=next(r for r in data['rows'] if r['label']==f'{role}/59904');b=next(r for r in data['rows'] if r['label']==f'{role}/65904');interval(a,b)
                    for call in data['calls']:
                        row=last['rows']['model_open'][0] if call['kind']=='open' else last['rows']['adapter_calls'][call['ordinal']-1]
                        assert row['tid']==next(r for r in data['rows'] if r['label']=='before_open')['value']['tid'] and row['adapter']==call['adapter'] and row['begin_ns']<=call['begin_ns']<=call['end_ns']<=row['end_ns']
                    assert final['metadata_finalization_pass']
                except BaseException as failure:
                    write(stage/'pipeline_failure.json',dict(error=repr(failure),traceback=__import__('traceback').format_exc()));raise
                write(stage/'pipeline_review.json',review)
        finally:
            restore(contexts);restore(cpu_patches);CameraControlService.__init__=original_control;local.LocalSession=original_local
if __name__=='__main__':main()
