"""Experiment-only prepared model process; original frames transferred once before ready."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]

def _serve(connection,model,frames,folder):
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/fixed_work_accounting'))
    from counters import snapshot
    from vision.live_walking import _PreviewAdapter
    adapter=_PreviewAdapter(Path(model));record=dict(pid=os.getpid(),tid=threading.get_native_id(),calls=[],errors=[],closed=False,
        frame_sha256=[hashlib.sha256(f.tobytes()).hexdigest() for f in frames])
    try:
        adapter.open();record['ready_ns']=time.perf_counter_ns()
        connection.send(dict(kind='ready',pid=record['pid'],tid=record['tid'],frame_sha256=record['frame_sha256']))
        while True:
            command=connection.recv()
            if command[0]=='infer':
                _,ordinal,slot,stamp=command
                if ordinal!=len(record['calls']) or not 0<=slot<len(frames):raise ValueError('Unexpected inference identity')
                if ordinal==0:record['process_before']=snapshot(time.perf_counter_ns)
                begin=time.perf_counter_ns();pose=adapter.infer_bgr(frames[slot],stamp);end=time.perf_counter_ns()
                record['calls'].append(dict(ordinal=ordinal,slot=slot,timestamp_ms=stamp,begin_ns=begin,end_ns=end))
                if ordinal==219:record['process_after']=snapshot(time.perf_counter_ns)
                connection.send(dict(kind='pose',ordinal=ordinal,pose=pose))
            elif command==('close',):
                adapter.close();record['closed']=not adapter.is_open
                connection.send(dict(kind='closed',closed=record['closed']));break
            else:raise ValueError('Unexpected model command')
    except BaseException as exc:
        record['errors'].append(repr(exc))
        try:connection.send(dict(kind='error',error=repr(exc)))
        except (OSError,EOFError):pass
    finally:
        if adapter.is_open:
            try:adapter.close();record['closed']=not adapter.is_open
            except BaseException as exc:record['errors'].append(repr(exc))
        with (Path(folder)/'result.json').open('x') as f:json.dump(record,f,indent=2)
        connection.close()
    if record['errors']:raise SystemExit(1)

def receive(connection,kind,ordinal=None):
    if not connection.poll(180):raise TimeoutError('Model response unconfirmed; retain process and lock')
    message=connection.recv()
    if message.get('kind')!=kind or ordinal is not None and message.get('ordinal')!=ordinal:raise ValueError('Unexpected model response: '+repr(message.get('kind')))
    return message

class PreparedModel:
    def __init__(self,model,frames,folder):
        self.model=model;self.frames=frames;self.folder=Path(folder);self.process=None;self.is_open=False;self.ordinal=0
    def open(self):
        self.folder.mkdir(exist_ok=False);(self.folder/'active.lock').mkdir()
        context=multiprocessing.get_context('spawn');self.connection,child=context.Pipe()
        self.process=context.Process(target=_serve,args=(child,str(self.model),self.frames,str(self.folder)))
        self.process.start();child.close()
        with (self.folder/'controller.json').open('x') as f:json.dump(dict(parent_pid=os.getpid(),child_pid=self.process.pid),f)
        message=receive(self.connection,'ready')
        if message['pid']==os.getpid() or message['pid']!=self.process.pid:raise ValueError('Model process identity mismatch')
        if message['frame_sha256']!=[hashlib.sha256(f.tobytes()).hexdigest() for f in self.frames]:raise ValueError('Prepared frames changed')
        self.slots={id(frame):i for i,frame in enumerate(self.frames)};self.is_open=True
    def infer_bgr(self,frame,stamp):
        self.connection.send(('infer',self.ordinal,self.slots[id(frame)],stamp))
        message=receive(self.connection,'pose',self.ordinal);self.ordinal+=1;return message['pose']
    def close(self):
        if self.process is None:return
        if self.is_open:
            self.connection.send(('close',));message=receive(self.connection,'closed');self.is_open=not message['closed']
        self.process.join(180)
        if self.process.is_alive() or self.process.exitcode!=0:raise RuntimeError('Model process termination not confirmed')
        self.connection.close()
