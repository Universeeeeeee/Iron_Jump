"""Diagnostic child entry. Execute the imported original serve, never a copied body."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE.parent/'gil_wire_receipts'))
from receipts import TextReceipts


class Observer:
    def __init__(self):self.local=threading.local();self.events=[];self.reader=None
    def call(self,stage,original,*args,**kwargs):
        row=dict(stage=stage,line_sequence=getattr(self.local,'sequence',None),pid=os.getpid(),tid=threading.get_native_id(),begin_ns=time.perf_counter_ns(),error=None)
        self.events.append(row)
        try:return original(*args,**kwargs)
        except BaseException as exc:row['error']=type(exc).__name__;raise
        finally:row['end_ns']=time.perf_counter_ns()
    def input(self,source):
        observer=self
        class Lines(TextReceipts):
            def __next__(self):
                observer.reader=threading.current_thread()
                observer.local.sequence=None
                line=super().__next__();observer.local.sequence=self.rows[-1]['sequence'];return line
        return Lines(source)


def run(output):
    # An isolated child owns these hooks; no production source or wire field changes.
    output=Path(output);output.mkdir(parents=True,exist_ok=False);(output/'active.lock').mkdir()
    from camera import control_service,tracking_runtime,pose_tracking
    observer=Observer();original_stdin=sys.stdin;tap=observer.input(original_stdin)
    hooks=[(tracking_runtime.TrackingRuntime,'submit_packet','runtime_packet'),
           (tracking_runtime.TrackingRuntime,'submit','runtime_submit'),
           (pose_tracking.PoseTrackingMailbox,'submit','mailbox_submit')]
    originals=[]
    for owner,name,stage in hooks:
        original=getattr(owner,name);originals.append((owner,name,original))
        def wrapped(*args,_stage=stage,_original=original,**kwargs):return observer.call(_stage,_original,*args,**kwargs)
        setattr(owner,name,wrapped)
    sys.stdin=tap;state=dict(errors=[],returncode=None,actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:state['returncode']=control_service.serve()
    except BaseException as exc:state['errors'].append(type(exc).__name__);raise
    finally:
        # Outside the original serve interval. Never call a native stop/kill here.
        if observer.reader is not None:observer.reader.join(2)
        reader_exited=observer.reader is not None and not observer.reader.is_alive()
        state.update(reader_exited=reader_exited,eof=tap.eof,read_errors=list(tap.errors),rows=list(tap.rows),events=[dict(x) for x in observer.events],
                     pid=os.getpid(),serve_tid=threading.get_native_id(),lock_retained=(output/'active.lock').is_dir(),
                     source_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('camera/control_service.py','camera/tracking_runtime.py','camera/pose_tracking.py')})
        state['observation_complete']=reader_exited and tap.eof and not state['errors'] and not tap.errors and all('end_ns' in x for x in state['events'])
        # No restoration while an unconfirmed reader could still execute a hook.
        if reader_exited:
            sys.stdin=original_stdin
            for owner,name,original in originals:setattr(owner,name,original)
        with (output/'receipts.json').open('x') as f:json.dump(state,f,indent=2)
    return state['returncode']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();raise SystemExit(run(a.output))
