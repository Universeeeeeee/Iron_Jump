"""New independent entry; old workload windows/entry/acceptance stay unchanged."""
import hashlib
from pathlib import Path
import runpy
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];OLD=HERE.parent/'gil_gui_calibration'
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(OLD));sys.path.insert(0,str(HERE))
from atomic_io03 import write
from winapi import anchor
from finalize import RetainedAudit,finalize


output=Path(sys.argv[sys.argv.index('--output')+1]);audit=RetainedAudit();anchors=[anchor()]
try:
    audit.install();runpy.run_path(str(OLD/'entry02.py'),run_name='__main__')
finally:
    original=sys.exc_info()[1]
    outcome=dict(success=original is None or isinstance(original,SystemExit) and original.code in (0,None),exception_type=None if original is None else type(original).__name__,exit_code=getattr(original,'code',None),error=None if original is None else repr(original))
    if output.exists():
        result=finalize(audit,lambda name,value:write(output/name,value),90,outcome)
        last=__import__('json').loads((output/'observer_tail.json').read_text())
        last['anchors']=anchors+[anchor()];last['replay_serialized']=(output/'measurement.json').exists()
        last['sources']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'finalize.py',Path(__file__))}
        write(output/'workload_final.json',last)
        if not result['metadata_finalization_pass']:raise RuntimeError('Metadata tail incomplete; preserve original and final snapshots')
