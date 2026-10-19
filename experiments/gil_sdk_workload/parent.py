"""Diagnostic SDK command and full accepted write stream beside original replay."""
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE.parent/'gil_wire_receipts'))
from receipts import WriteReceipts


class Parent:
    def __init__(self,output,child_entry):self.output=Path(output);self.child_entry=Path(child_entry);self.controls=[]
    def install(self):
        from camera.control_service import CameraControlService
        from qtpy.QtCore import QProcess
        original=CameraControlService.__init__;audit=self
        def init(control,*args,**kwargs):
            if kwargs.get('command') is not None:raise ValueError('Unexpected existing SDK command')
            index=len(audit.controls);folder=audit.output/'wire';folder.mkdir(parents=True,exist_ok=True)
            child_output=folder/('child_'+str(index));command=[sys.executable,'-u',str(audit.child_entry),str(child_output)]
            kwargs['command']=command;value=original(control,*args,**kwargs);process=control._process
            state=dict(control=index,command=command,child_output=str(child_output),writes=[],chunks=[],started=[],finished=[],errors=[])
            audit.controls.append(state);original_write=process.write
            def write(data):state['chunks'].append(bytes(data).hex());return original_write(data)
            tap=WriteReceipts(write);process.write=tap;state['writes']=tap.rows
            def started():
                marker=dict(gui_pid=os.getpid(),sdk_pid=int(process.processId()),host_ns=time.perf_counter_ns(),tid=threading.get_native_id(),command=command)
                state['started'].append(marker)
                with (folder/('started_'+str(index)+'.json')).open('x') as f:json.dump(marker,f,indent=2)
            def finished(code,status):
                state['finished'].append(dict(host_ns=time.perf_counter_ns(),tid=threading.get_native_id(),exit_code=code,normal=status==QProcess.NormalExit,stop_confirmed=control._stop_confirmed))
            process.started.connect(started);process.finished.connect(finished);control.failed.connect(state['errors'].append)
            return value
        CameraControlService.__init__=init
    def finish(self):
        state=dict(pid=os.getpid(),controls=self.controls,actual_load_disturbance_pass=False,field_attribution_ready=False)
        with (self.output/'wire/parent.json').open('x') as f:json.dump(state,f,indent=2)
        return state
