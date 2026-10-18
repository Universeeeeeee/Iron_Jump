"""Real FootVisionService, gated Python-only adapter; no model, Qt, SDK or input frames."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import weakref

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE.parent/'gil_workload_observation'))
from workload import Audit
from vision.service import FootVisionService
from vision.foot_reference import VisionConfig
from snapshot import FrozenAudit


class NativeThread:
    def __init__(self,tid):
        self.handle=None;self.tid=tid
        if sys.platform!='win32':return
        k=self.kernel=C.WinDLL('kernel32',use_last_error=True)
        k.OpenThread.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenThread.restype=W.HANDLE
        k.GetProcessIdOfThread.argtypes=[W.HANDLE];k.GetProcessIdOfThread.restype=W.DWORD
        k.GetExitCodeThread.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
        k.GetThreadTimes.argtypes=[W.HANDLE]+[C.POINTER(W.FILETIME)]*4
        k.QueryThreadCycleTime.argtypes=[W.HANDLE,C.POINTER(C.c_uint64)]
        k.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];k.WaitForSingleObject.restype=W.DWORD
        k.CloseHandle.argtypes=[W.HANDLE]
        self.handle=k.OpenThread(0x100800,False,tid)
        assert self.handle and k.GetProcessIdOfThread(self.handle)==os.getpid()

    def read(self):
        if self.handle is None:return dict(available=False,platform=sys.platform,tid=self.tid)
        k=self.kernel;values=[W.FILETIME() for _ in range(4)];status=W.DWORD();cycles=C.c_uint64()
        assert k.GetThreadTimes(self.handle,*[C.byref(x) for x in values])
        assert k.GetExitCodeThread(self.handle,C.byref(status)) and k.QueryThreadCycleTime(self.handle,C.byref(cycles))
        count=lambda x:(x.dwHighDateTime<<32)|x.dwLowDateTime
        return dict(available=True,pid=k.GetProcessIdOfThread(self.handle),tid=self.tid,creation_100ns=count(values[0]),exit_code=status.value,kernel_100ns=count(values[2]),user_100ns=count(values[3]),cycles=cycles.value)

    def wait_exit(self):
        if self.handle is not None:assert self.kernel.WaitForSingleObject(self.handle,1000)==0,'Native thread exit unconfirmed'

    def close(self):
        if self.handle is not None:assert self.kernel.CloseHandle(self.handle);self.handle=None


def run_case(kind,stop_listener=False,close_error=False,use_default_stop=False):
    audit=Audit() if kind=='legacy' else FrozenAudit()
    entered=threading.Event();release=threading.Event();stopped_callback=threading.Event();leave_callback=threading.Event();ready=threading.Event()
    class Adapter:
        def __init__(self,path):self.is_open=False
        def open(self):
            b=time.perf_counter_ns();self.is_open=True
            audit.event('model_open',adapter=id(self),begin_ns=b,end_ns=time.perf_counter_ns(),is_open=True,error=None)
        def infer_bgr(self,*args):raise AssertionError('No input/inference permitted in this control')
        def close_body(self):
            b=time.perf_counter_ns();entered.set();error=None
            try:
                if not release.wait(5):raise TimeoutError('Synthetic close release missing')
                if close_error:raise RuntimeError('injected close failure')
                self.is_open=False
            except Exception as exc:error=type(exc).__name__;raise
            finally:audit.event('model_close',adapter=id(self),begin_ns=b,end_ns=time.perf_counter_ns(),is_open=self.is_open,error=error)
    Adapter.close=Adapter.close_body if kind=='legacy' else audit.close_entry(Adapter.close_body)
    service=FootVisionService(VisionConfig(),Path('synthetic-no-model'),adapter_factory=Adapter)
    audit.services.append(weakref.ref(service));audit.tags[service]=0
    def status(value):
        audit.event('service_status',service=0,status=value)
        if value=='ready':ready.set()
        if value=='stopped':
            stopped_callback.set()
            if stop_listener:assert leave_callback.wait(3),'Terminal listener release missing'
    service.status_changed.connect(status)
    handle=None;worker=None
    try:
        service.start();assert ready.wait(2);worker=service._thread
        handle=NativeThread(worker.native_id);before=handle.read()
        if use_default_stop:service.stop()
        else:service.stop(timeout_s=.001)
        assert entered.wait(2)
        first=audit.finish();first_bytes=json.dumps(first,sort_keys=True).encode();first_hash=hashlib.sha256(first_bytes).hexdigest()
        blocked=dict(service_running=service.is_running,python_thread_alive=worker.is_alive(),native=handle.read(),close_enter_oracle=entered.is_set())
        release.set();listener_snapshot=None;listener_native=None
        if stop_listener:
            assert stopped_callback.wait(2);listener_snapshot=audit.finish();listener_native=handle.read();leave_callback.set()
        worker.join(2);assert not worker.is_alive();handle.wait_exit();after=handle.read()
        second=audit.finish();first_after_bytes=json.dumps(first,sort_keys=True).encode()
        return dict(kind=kind,stop_listener=stop_listener,close_error=close_error,used_original_default_stop_timeout=use_default_stop,
                    first_snapshot=first,first_value_at_return=json.loads(first_bytes),first_serialized_sha_before=first_hash,
                    first_serialized_sha_after=hashlib.sha256(first_after_bytes).hexdigest(),
                    first_snapshot_changed=first_bytes!=first_after_bytes,blocked=blocked,
                    listener_snapshot=listener_snapshot,listener_native=listener_native,second_snapshot=second,
                    native_before=before,native_after=after,
                    legacy_first_rows_after_exit_include_close=bool(first['rows']['model_close']),
                    target_was_real_FootVisionService=True,no_inputs_submitted=True,
                    actual_load_disturbance_pass=False,field_attribution_ready=False)
    finally:
        release.set();leave_callback.set()
        if worker is not None:worker.join(3)
        if handle is not None:handle.close()


if __name__=='__main__':
    folder=HERE/'runs/synthetic01';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    result=dict(cases={},errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        plan=json.loads((HERE/'synthetic_plan01.json').read_text())
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
        assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
        for name,kind,listener,error in [('legacy_alias','legacy',False,False),('frozen_delay','frozen',False,False),('stopped_but_alive','frozen',True,False),('close_failure','frozen',False,True)]:
            item=run_case(kind,listener,error,use_default_stop=True)
            with (folder/(name+'.json')).open('x') as f:json.dump(item,f,indent=2)
            result['cases'][name]=name+'.json'
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result['lock_retained']=(folder/'active.lock').is_dir()
        with (folder/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']))
