import copy
"""Bounded read-only startup CPU ledger; no CPU workload or OS-policy changes."""
import ctypes as c
from ctypes import wintypes as w
from functools import wraps
import os
import threading
import time

class NativeReader:
    def __init__(self):
        if os.name!='nt':raise OSError('Windows native reader required')
        assert c.sizeof(w.FILETIME)==8 and w.FILETIME.dwHighDateTime.offset==4
        # These short counter queries retain the caller GIL. WinDLL would release
        # and reacquire it around every query, adding observer-induced waits.
        self.k=c.PyDLL('kernel32',use_last_error=True)
        for name in ('GetCurrentProcess','GetCurrentThread'):getattr(self.k,name).restype=w.HANDLE
        for name in ('GetProcessTimes','GetThreadTimes'):
            fn=getattr(self.k,name);fn.argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4;fn.restype=w.BOOL
        for name in ('QueryProcessCycleTime','QueryThreadCycleTime'):
            fn=getattr(self.k,name);fn.argtypes=[w.HANDLE,c.POINTER(c.c_uint64)];fn.restype=w.BOOL
        for name in ('GetCurrentProcessId','GetCurrentThreadId'):
            getattr(self.k,name).argtypes=[];getattr(self.k,name).restype=w.DWORD
        self.process=self.k.GetCurrentProcess();self.thread=self.k.GetCurrentThread
    def _counter(self,handle,times_name,cycles_name):
        values=[w.FILETIME() for _ in range(4)];cycles=c.c_uint64()
        if not getattr(self.k,times_name)(handle,*[c.byref(v) for v in values]):raise c.WinError(c.get_last_error())
        if not getattr(self.k,cycles_name)(handle,c.byref(cycles)):raise c.WinError(c.get_last_error())
        numbers=[(v.dwHighDateTime<<32)|v.dwLowDateTime for v in values]
        return dict(creation_100ns=numbers[0],kernel_100ns=numbers[2],user_100ns=numbers[3],cycles=cycles.value)
    def __call__(self):
        begin=time.perf_counter_ns();py_process_before=time.process_time_ns();py_before=time.thread_time_ns()
        process=self._counter(self.process,'GetProcessTimes','QueryProcessCycleTime')
        thread=self._counter(self.thread(),'GetThreadTimes','QueryThreadCycleTime')
        py_after=time.thread_time_ns();py_process_after=time.process_time_ns()
        pid=self.k.GetCurrentProcessId();tid=self.k.GetCurrentThreadId();end=time.perf_counter_ns()
        return dict(pid=pid,tid=tid,identity_crosscheck=(pid,tid)==(os.getpid(),threading.get_native_id()),begin_ns=begin,end_ns=end,process=process,thread=thread,python_thread_before_ns=py_before,python_thread_after_ns=py_after,python_process_before_ns=py_process_before,python_process_after_ns=py_process_after,
            reader_gil='held for short readonly Win32 calls')

def validate_read(value,max_read_ns=1000000):
    if not 0<=value['end_ns']-value['begin_ns']<=max_read_ns:raise ValueError('CPU read bracket exceeded unchanged1ms')
    if value['pid']<=0 or value['tid']<=0 or not value['identity_crosscheck']:raise ValueError('CPU read identity missing')
    for role in ('process','thread'):
        v=value[role]
        if v['creation_100ns']<=0 or any(v[k]<0 for k in ('kernel_100ns','user_100ns','cycles')):raise ValueError('Invalid native CPU counters')
    cpu=(value['thread']['kernel_100ns']+value['thread']['user_100ns'])*100
    if not value['python_thread_before_ns']<=cpu<=value['python_thread_after_ns']:raise ValueError('GetThreadTimes/Python CPU crosscheck failed')
    process_cpu=(value['process']['kernel_100ns']+value['process']['user_100ns'])*100
    if not value['python_process_before_ns']<=process_cpu<=value['python_process_after_ns']:raise ValueError('GetProcessTimes/Python CPU crosscheck failed')
    return True

class Ledger:
    def __init__(self,reader,clock=time.perf_counter_ns):
        self.reader=reader;self.clock=clock;self.rows=[];self.calls=[];self.infer_count=0;self.model_adapters=set();self.lock=threading.RLock()
    def capture(self,label,adapter=None):
        begin=self.clock();row=dict(label=label,adapter=adapter,capture_begin_ns=begin)
        try:
            row['value']=self.reader();validate_read(row['value']);row['valid']=True
        except Exception as exc:row.update(valid=False,error=repr(exc))
        with self.lock:
            self.rows.append(row);row['capture_end_ns']=self.clock()
            if row['capture_end_ns']-begin>1000000:row.update(valid=False,error='Full CPU hook exceeded1ms')
        return row
    def wrap_open(self,original):
        @wraps(original)
        def call(adapter,*args,**kwargs):
            tag=id(adapter)
            with self.lock:self.model_adapters.add(tag)
            self.capture('before_open',tag);begin=self.clock();error=None
            try:return original(adapter,*args,**kwargs)
            except BaseException as exc:error=repr(exc);raise
            finally:
                end=self.clock();self.capture('after_open',tag)
                with self.lock:self.calls.append(dict(kind='open',adapter=tag,begin_ns=begin,end_ns=end,error=error))
        return call
    def wrap_infer(self,original):
        @wraps(original)
        def call(adapter,*args,**kwargs):
            with self.lock:self.infer_count+=1;ordinal=self.infer_count
            tag=id(adapter);selected=ordinal in (1,100,200)
            if ordinal==1:self.capture('before_infer1',tag)
            begin=self.clock() if selected else None;error=None
            try:return original(adapter,*args,**kwargs)
            except BaseException as exc:error=repr(exc);raise
            finally:
                if selected:
                    end=self.clock();self.capture('after_infer'+str(ordinal),tag)
                    with self.lock:self.calls.append(dict(kind='infer',ordinal=ordinal,adapter=tag,begin_ns=begin,end_ns=end,error=error))
        return call
    def install(self):
        from vision.mediapipe_pose import MediaPipePoseAdapter
        original=[(MediaPipePoseAdapter,'open',MediaPipePoseAdapter.open),(MediaPipePoseAdapter,'infer_bgr',MediaPipePoseAdapter.infer_bgr)]
        MediaPipePoseAdapter.open=self.wrap_open(original[0][2]);MediaPipePoseAdapter.infer_bgr=self.wrap_infer(original[1][2]);return original
    def payload(self):
        with self.lock:return copy.deepcopy(dict(rows=self.rows,calls=self.calls,infer_count=self.infer_count,infer_count_semantics='begun calls',model_adapters=list(self.model_adapters),actual_load_disturbance_pass=False))

def verify(value,phase_rows):
    expected={'before_open','after_open','before_infer1','after_infer1','after_infer100','after_infer200'}|{f'{role}/{n}' for role in ('gui','model','consumer') for n in (59904,65904)}
    rows=value['rows'];assert len(rows)==12 and {r['label'] for r in rows}==expected and all(r['valid'] for r in rows)
    for r in rows:validate_read(r['value']);assert 0<=r['capture_end_ns']-r['capture_begin_ns']<=1000000
    assert value['infer_count']>=200 and len(value['model_adapters'])==1
    model=[r for r in rows if r['adapter'] is not None];assert len({(r['value']['pid'],r['value']['tid'],r['value']['thread']['creation_100ns']) for r in model})==1
    assert len({(r['value']['pid'],r['value']['process']['creation_100ns']) for r in rows})==1
    ordered=sorted(model,key=lambda r:r['capture_begin_ns'])
    assert [r['label'] for r in ordered]==['before_open','after_open','before_infer1','after_infer1','after_infer100','after_infer200']
    for a,b in zip(ordered,ordered[1:]):
        assert a['capture_end_ns']<=b['capture_begin_ns']
        for role in ('process','thread'):assert all(a['value'][role][k]<=b['value'][role][k] for k in ('kernel_100ns','user_100ns','cycles'))
    assert len(value['calls'])==4 and all(c['error'] is None and c['begin_ns']<=c['end_ns'] and c['adapter']==value['model_adapters'][0] for c in value['calls'])
    labels={r['label']:r for r in rows}
    calls={('open' if c['kind']=='open' else str(c['ordinal'])):c for c in value['calls']}
    assert set(calls)=={'open','1','100','200'}
    for key,before,after in [('open','before_open','after_open'),('1','before_infer1','after_infer1')]:
        assert labels[before]['capture_end_ns']<=calls[key]['begin_ns']<=calls[key]['end_ns']<=labels[after]['capture_begin_ns']
    for key in ('100','200'):assert calls[key]['end_ns']<=labels['after_infer'+key]['capture_begin_ns']
    for role in ('process','thread'):
        a,b=labels['before_open']['value'][role],labels['after_infer200']['value'][role]
        assert b['kernel_100ns']+b['user_100ns']>a['kernel_100ns']+a['user_100ns'] and b['cycles']>a['cycles'], 'Counters did not respond to actual work'

    model_id=(model[0]['value']['pid'],model[0]['value']['tid'])
    for phase in phase_rows:
        r=next(r for r in rows if r['label']==f"{phase['role']}/{phase['ordinal']}")
        assert r['value']['pid']==phase['pid'] and r['value']['tid']==phase['tid'] and phase['cpu_hook_total_ns']<=50000000
        if phase['role']=='model':assert (phase['pid'],phase['tid'])==model_id
    return dict(startup_cpu_ledger_pass=True,reads=12,max_native_read_ns=max(r['value']['end_ns']-r['value']['begin_ns'] for r in rows),max_capture_hook_ns=max(r['capture_end_ns']-r['capture_begin_ns'] for r in rows),actual_load_disturbance_pass=False,
        scope='Raw process/native-pool and caller-thread accounting with bounded reads; no CPU/GIL percentage, instruction count, GHz orzero-observer claim.')
