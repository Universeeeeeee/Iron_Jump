"""Saved GUI replay with process-only QoS; no algorithm candidate or hardware."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
from context_gate import check_context
from run_gate import require_gate
from runtime_context import install,restore

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/process_qos_candidate'))
from qos import API,configure
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))

if __name__=='__main__':
    plan=require_gate(HERE)
    position=sys.argv.index('--qos-variant');variant=sys.argv[position+1];del sys.argv[position:position+2]
    assert variant=='default'
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    output=Path(sys.argv[sys.argv.index('--output')+1]);context_path=output.parent/'startup_context.json';saved_argv=list(sys.argv)
    try:
        sys.argv=['read_context.py',str(context_path)]
        runpy.run_path(str(ROOT/'experiments/qos_context_review/read_context.py'),run_name='__main__')
    finally:sys.argv=saved_argv
    context=read(context_path);check_context(context)
    api=API();configuration=configure(api,variant)
    from camera.control_service import CameraControlService
    from engine.device_quality_session import DeviceQualitySession
    original_control=CameraControlService.__init__;original_method=DeviceQualitySession.on_frame
    def control_init(self,*args,**kwargs):
        if kwargs.get('command') is not None:raise ValueError('Unexpected SDK override')
        kwargs['command']=[sys.executable,'-u',str(ROOT/'experiments/gil_boundary_ab/fake_sdk.py'),str(output/'sdk_backend.json')]
        return original_control(self,*args,**kwargs)
    CameraControlService.__init__=control_init
    runtime_rows=[];originals=install(runtime_rows)
    from boundary import Boundaries
    from vision.mediapipe_pose import MediaPipePoseAdapter
    phase_folder=output.parent/'native_phases';phase_folder.mkdir(exist_ok=False)
    boundaries=Boundaries(phase_folder);base_originals=boundaries.install(MediaPipePoseAdapter)
    try:runpy.run_path(str(ROOT/'experiments/gil_workload_finalization/entry01.py'),run_name='__main__')
    finally:
        CameraControlService.__init__=original_control
        restore(originals)
        boundaries.save()
        MediaPipePoseAdapter.open,MediaPipePoseAdapter.close=base_originals
        record=dict(configuration=configuration,at_end=api.read(),original_method_unchanged=DeviceQualitySession.on_frame is original_method,
                    original_module_unchanged=sha(ROOT/'engine/device_quality_session.py')==plan['original_module_sha256'],
                    backend='simulated_native_SDK',no_native_probe=False,context=context,runtime_context=runtime_rows)
        with (output.parent/'qos_activation.json').open('x') as f:json.dump(record,f,indent=2)
        assert record['at_end']==configuration['after'] and record['original_method_unchanged'] and record['original_module_unchanged']
