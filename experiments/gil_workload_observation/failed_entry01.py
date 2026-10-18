"""Run the exact old replay with process-local workload metadata beside it."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent;OLD=HERE.parent/'gil_gui_calibration'
sys.path.insert(0,str(OLD))
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
        result['replay_serialized']=(output/'measurement.json').exists()
        write(output/'workload01.json',result)
