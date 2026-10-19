"""Authorized one-expression intervention; common simulated SDK and original GUI."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
plan=json.loads((HERE/'ab_plan01.json').read_text());position=sys.argv.index('--equality-variant');variant=sys.argv[position+1];del sys.argv[position:position+2];assert variant in ('original','candidate')
output=Path(sys.argv[sys.argv.index('--output')+1]);from camera.control_service import CameraControlService
from engine.device_quality_session import DeviceQualitySession
original_method=DeviceQualitySession.on_frame;original_control=CameraControlService.__init__
def control_init(self,*args,**kwargs):
    if kwargs.get('command') is not None:raise ValueError('Unexpected SDK command override')
    kwargs['command']=[sys.executable,'-u',str(HERE/'fake_sdk.py'),str(output/'sdk_backend.json')]
    return original_control(self,*args,**kwargs)
CameraControlService.__init__=control_init
import candidate
prepared_method=candidate.prepare(original_method,plan['original_function_source_sha256'])
if variant=='candidate':
    DeviceQualitySession.on_frame=prepared_method
active_method=DeviceQualitySession.on_frame
assert (active_method is not original_method)==(variant=='candidate')
try:runpy.run_path(str(HERE.parent/'gil_workload_finalization/entry01.py'),run_name='__main__')
finally:
    if output.exists():
        with (output/'activation.json').open('x') as f:json.dump(dict(variant=variant,candidate_installed=active_method is not original_method,
            original_source_file_unchanged=hashlib.sha256((ROOT/'engine/device_quality_session.py').read_bytes()).hexdigest()==plan['original_module_sha256'],
            candidate_sha256=hashlib.sha256((HERE/'candidate.py').read_bytes()).hexdigest(),SDK_backend='simulated_native_SDK',sampler_enabled=False),f,indent=2)
    DeviceQualitySession.on_frame=original_method
