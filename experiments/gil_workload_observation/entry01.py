"""Run the exact old replay with process-local workload metadata beside it."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'gil_gui_calibration'
sys.path.insert(0,str(OLD))
sys.path.insert(0,str(HERE.parents[1]))
from atomic_io03 import write
from winapi import anchor
from workload import Audit


output=Path(sys.argv[sys.argv.index('--output')+1]);audit=Audit();anchors=[anchor()]
try:
    audit.install();runpy.run_path(str(OLD/'entry02.py'),run_name='__main__')
finally:
    if output.exists():
        result=audit.finish()
        result['anchors']=anchors+[anchor()]
        result['sources']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'workload.py',Path(__file__))}
        result['loaded_modules']={}
        for name in ('numpy','numpy._core._multiarray_umath','cv2','mediapipe','PySide6'):
            module=sys.modules.get(name)
            if module is None:continue
            native=getattr(module,'_native',module);filename=getattr(native,'__file__',None)
            result['loaded_modules'][name]=dict(version=getattr(module,'__version__',None),file=filename,sha256=hashlib.sha256(Path(filename).read_bytes()).hexdigest() if filename and Path(filename).is_file() else None)
        result['replay_serialized']=(output/'measurement.json').exists()
        write(output/'workload01.json',result)
