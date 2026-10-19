"""Read-only startup context. Does not create GUI, import IronJump, or set QoS."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import sys
import time

class Throttle(c.Structure):
    _fields_=[('version',w.DWORD),('control_mask',w.DWORD),('state_mask',w.DWORD)]

if __name__=='__main__':
    output=Path(sys.argv[1]);assert not output.exists()
    k=c.WinDLL('kernel32',use_last_error=True);u=c.WinDLL('user32',use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE;k.GetCurrentThread.restype=w.HANDLE
    k.GetProcessInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.GetProcessInformation.restype=w.BOOL
    k.GetThreadInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.GetThreadInformation.restype=w.BOOL
    k.ProcessIdToSessionId.argtypes=[w.DWORD,c.POINTER(w.DWORD)];k.ProcessIdToSessionId.restype=w.BOOL
    k.GetPriorityClass.argtypes=[w.HANDLE];k.GetPriorityClass.restype=w.DWORD
    u.GetForegroundWindow.restype=w.HWND;u.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)];u.GetWindowThreadProcessId.restype=w.DWORD
    session=w.DWORD();assert k.ProcessIdToSessionId(os.getpid(),c.byref(session))
    fg=w.DWORD();window=u.GetForegroundWindow()
    if window:u.GetWindowThreadProcessId(window,c.byref(fg))
    r=dict(pid=os.getpid(),session_id=session.value,foreground_pid=fg.value if window else None,
        priority_class=k.GetPriorityClass(k.GetCurrentProcess()),qpa=os.environ.get('QT_QPA_PLATFORM'),
        perf_counter_ns=time.perf_counter_ns(),utc_ns=time.time_ns(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='Fresh startup process only. NoGUI/model/SDK or actual workload policy measurement.')
    for name,func,handle,info in [('process',k.GetProcessInformation,k.GetCurrentProcess(),4),('thread',k.GetThreadInformation,k.GetCurrentThread(),3)]:
        v=Throttle();v.version=1;c.set_last_error(0);ok=bool(func(handle,info,c.byref(v),c.sizeof(v)))
        r[name]=dict(success=ok,error=0 if ok else c.get_last_error(),version=v.version,control_mask=v.control_mask,state_mask=v.state_mask)
    with output.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r))
