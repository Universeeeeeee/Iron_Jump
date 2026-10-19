"""Two bounded current-thread context reads per role; no periodic sampler."""
import ctypes as c
from ctypes import wintypes as w
from functools import wraps
import os
import threading
import time

class Throttle(c.Structure):
    _fields_=[('version',w.DWORD),('control_mask',w.DWORD),('state_mask',w.DWORD)]

def snapshot(role,ordinal):
    k=c.WinDLL('kernel32',use_last_error=True);u=c.WinDLL('user32',use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE;k.GetCurrentThread.restype=w.HANDLE
    k.GetProcessInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.GetProcessInformation.restype=w.BOOL
    k.GetThreadInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.GetThreadInformation.restype=w.BOOL
    k.GetPriorityClass.argtypes=[w.HANDLE];k.GetPriorityClass.restype=w.DWORD
    k.ProcessIdToSessionId.argtypes=[w.DWORD,c.POINTER(w.DWORD)];k.ProcessIdToSessionId.restype=w.BOOL
    u.GetForegroundWindow.restype=w.HWND;u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
    begin=time.perf_counter_ns();session=w.DWORD();session_ok=bool(k.ProcessIdToSessionId(os.getpid(),c.byref(session)))
    r=dict(role=role,ordinal=ordinal,pid=os.getpid(),tid=threading.get_native_id(),begin_ns=begin,session_id=session.value if session_ok else None,priority_class=k.GetPriorityClass(k.GetCurrentProcess()))
    for name,func,handle,info in [('process',k.GetProcessInformation,k.GetCurrentProcess(),4),('thread',k.GetThreadInformation,k.GetCurrentThread(),3)]:
        v=Throttle();v.version=1;c.set_last_error(0);ok=bool(func(handle,info,c.byref(v),c.sizeof(v)))
        r[name]=dict(success=ok,error=0 if ok else c.get_last_error(),version=v.version,control_mask=v.control_mask,state_mask=v.state_mask)
    foreground=w.DWORD();window=u.GetForegroundWindow()
    if window:u.GetWindowThreadProcessId(window,c.byref(foreground))
    r.update(foreground_pid=foreground.value if window else None,end_ns=time.perf_counter_ns())
    return r

def wrap(original,role,rows,reader=snapshot):
    ordinal=0
    @wraps(original)
    def call(*args,**kwargs):
        nonlocal ordinal
        ordinal+=1
        if ordinal in (1,100):rows.append(reader(role,ordinal))
        return original(*args,**kwargs)
    return call

def install(rows):
    from ui.session_controller import _GroundFrameInbox
    from vision.live_walking import _PreviewAdapter
    from ui.annotation_canvas import AnnotationCanvas
    targets=[(_GroundFrameInbox,'_consume','consumer'),(_PreviewAdapter,'infer_bgr','model'),(AnnotationCanvas,'_draw_live_pose','gui')]
    originals=[]
    for cls,name,role in targets:
        original=getattr(cls,name);originals.append((cls,name,original));setattr(cls,name,wrap(original,role,rows))
    return originals

def restore(originals):
    for cls,name,original in originals:setattr(cls,name,original)
