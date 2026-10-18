"""Unmodified serve AST + real TrackingRuntime, fake hardware and gated stdin."""
import ast
import builtins
import hashlib
import io
import json
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from camera.tracking_runtime import TrackingRuntime


class Input:
    def __init__(self):
        self.queue=queue.Queue();self.condition=threading.Condition();self.sent=[];self.consumed=[];self.processed=[];self.previous=None
    def __iter__(self):return self
    def __next__(self):
        with self.condition:
            if self.previous is not None:self.processed.append(self.previous);self.condition.notify_all();self.previous=None
        item=self.queue.get(timeout=5)
        if item is None:raise StopIteration
        seq,line=item
        with self.condition:
            self.consumed.append(dict(sequence=seq,observed_ns=time.perf_counter_ns(),tid=threading.get_native_id(),line=line));self.previous=seq;self.condition.notify_all()
        return line
    def send(self,value):
        line=json.dumps(value,separators=(',',':'))+'\n';seq=len(self.sent)+1
        self.sent.append(dict(sequence=seq,observed_ns=time.perf_counter_ns(),value=value));self.queue.put((seq,line));return seq
    def wait_processed(self,seq):
        with self.condition:
            if not self.condition.wait_for(lambda:seq in self.processed,2):raise TimeoutError('Original reader did not finish line '+str(seq))
    def close(self):self.queue.put(None)


class Output:
    def __init__(self,prefix):self.prefix=prefix;self.condition=threading.Condition();self.buffer='';self.replies=[]
    def write(self,text):
        with self.condition:
            self.buffer+=text
            while '\n' in self.buffer:
                line,self.buffer=self.buffer.split('\n',1)
                if line.startswith(self.prefix):self.replies.append(dict(observed_ns=time.perf_counter_ns(),tid=threading.get_native_id(),value=json.loads(line[len(self.prefix):])))
            self.condition.notify_all()
        return len(text)
    def flush(self):pass
    def wait(self,predicate):
        with self.condition:
            if not self.condition.wait_for(lambda:any(predicate(x['value']) for x in self.replies),2):raise TimeoutError('Expected original protocol reply missing')


def compile_serve(source,input_stream,output,control_type,sdk_type,runtime_type):
    tree=ast.parse(source.read_text(encoding='utf-8'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='serve')
    constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('PREFIX','METHODS')}
    imports={'camera.tinyse_camera':SimpleNamespace(TinySeCameraControl=control_type),'camera.gimbal_control':SimpleNamespace(GimbalSdk=sdk_type),'camera.tracking_runtime':SimpleNamespace(TrackingRuntime=runtime_type)}
    original_import=builtins.__import__
    def importer(name,*args,**kwargs):return imports[name] if name in imports else original_import(name,*args,**kwargs)
    def printer(*args,**kwargs):return builtins.print(*args,file=output,**kwargs)
    env=dict(threading=threading,queue=queue,json=json,sys=SimpleNamespace(stdin=input_stream),**constants)
    env['__builtins__']=dict(builtins.__dict__,__import__=importer,print=printer)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),env)
    return env['serve'],hashlib.sha256(ast.dump(fn,include_attributes=False).encode()).hexdigest()


def ready_packet(generation=1):
    return dict(pose_packet=dict(generation=generation,barrier_sequence=2,barrier=dict(status='ready',inference=None,identity=None,framing=None),update=dict(status='ready',inference=None,identity=None,framing=None)))


def run_case(mode):
    input_stream=Input();output=Output('IRON_CAMERA_CONTROL ');setting_entered=threading.Event();release_setting=threading.Event();attach_entered=threading.Event();release_attach=threading.Event()
    calls=[];runtime_calls=[];result={};errors=[]
    class Control:
        def __init__(self):self._dll=object();self._idx=0
        def init(self):return True
        def set_fov(self,*args):
            setting_entered.set()
            if not release_setting.wait(3):raise TimeoutError('Synthetic setting gate unreleased')
            return 0
        def close(self):calls.append(dict(kind='control_closed',tid=threading.get_native_id()))
    class SDK:
        @classmethod
        def attach(cls,*args):
            attach_entered.set()
            if mode=='constructor_gap' and not release_attach.wait(3):raise TimeoutError('Synthetic attach gate unreleased')
            return cls()
        def set_speed(self,*args):calls.append(dict(kind='set_speed',args=args,tid=threading.get_native_id()))
        def disable_ai(self):calls.append(dict(kind='disable_ai',tid=threading.get_native_id()))
    class ObservedRuntime(TrackingRuntime):
        def submit_packet(self,packet):
            before=dict(active=self.active,generation=self.generation,barrier_sequence=self._barrier_sequence)
            value=super().submit_packet(packet)
            runtime_calls.append(dict(tid=threading.get_native_id(),packet=packet,before=before,after=dict(active=self.active,generation=self.generation,barrier_sequence=self._barrier_sequence)))
            return value
    source=ROOT/'camera/control_service.py';serve,ast_sha=compile_serve(source,input_stream,output,Control,SDK,ObservedRuntime)
    def target():
        try:result['returncode']=serve()
        except BaseException as exc:errors.append(repr(exc))
    thread=threading.Thread(target=target,name='SyntheticOriginalSDKServe');thread.start();early=None;late=None
    try:
        output.wait(lambda v:v.get('ready') is True)
        if mode=='before_runtime':
            input_stream.send(dict(method='set_fov',args=[0]));assert setting_entered.wait(1)
            early=input_stream.send(ready_packet());input_stream.wait_processed(early)
            result['early_line_read_without_runtime']=not runtime_calls and not attach_entered.is_set()
            input_stream.send(dict(method='tracking_start',args=[1]));release_setting.set()
        else:
            input_stream.send(dict(method='tracking_start',args=[1]))
            if mode=='constructor_gap':
                assert attach_entered.wait(1);early=input_stream.send(ready_packet());input_stream.wait_processed(early)
                result['early_line_read_without_runtime']=not runtime_calls;release_attach.set()
        output.wait(lambda v:v.get('method')=='tracking_start' and v.get('result')==0)
        if mode=='inactive_runtime':
            input_stream.send(dict(method='tracking_stop',args=[]));output.wait(lambda v:v.get('method')=='tracking_stop' and v.get('result')==0)
        late=input_stream.send(ready_packet(0 if mode=='wrong_generation' else 1));input_stream.wait_processed(late)
        input_stream.close();thread.join(2);assert not thread.is_alive()
    finally:
        release_setting.set();release_attach.set()
        if thread.is_alive():input_stream.close();thread.join(3)
    return dict(mode=mode,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),original_serve_ast_sha256=ast_sha,input_sent=input_stream.sent,raw_line_reads=input_stream.consumed,original_reader_processed_sequences=input_stream.processed,
                original_replies=output.replies,runtime_submit_calls=runtime_calls,fake_sdk_calls=calls,early_pose_sequence=early,late_pose_sequence=late,
                early_line_read_without_runtime=result.get('early_line_read_without_runtime'),returncode=result.get('returncode'),errors=errors,serve_thread_alive=thread.is_alive(),
                scope='Exact original serve AST, real TrackingRuntime body; fake native hardware, injected stdin/output. No GUI, model, sensor/camera acquisition or actual replay.',actual_load_disturbance_pass=False,field_attribution_ready=False)


if __name__=='__main__':
    folder=Path(__file__).resolve().parent/'runs/synthetic01';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    record=dict(cases={},errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        for mode in ('before_runtime','constructor_gap','inactive_runtime','wrong_generation'):
            data=run_case(mode)
            with (folder/(mode+'.json')).open('x') as f:json.dump(data,f,indent=2)
            record['cases'][mode]=mode+'.json';assert not data['errors'] and not data['serve_thread_alive'] and data['returncode']==0
        record['complete']=True
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        record['lock_retained']=(folder/'active.lock').is_dir()
        with (folder/'result01.json').open('x') as f:json.dump(record,f,indent=2)
    print(json.dumps(record,indent=2));raise SystemExit(bool(record['errors']))
