"""Read inherited QoS of a new SSH Python process; not historical target evidence."""
import ctypes as c
from ctypes import wintypes as w
import json

class Throttle(c.Structure):
    _fields_=[('version',w.DWORD),('control_mask',w.DWORD),('state_mask',w.DWORD)]

k=c.WinDLL('kernel32',use_last_error=True)
k.GetCurrentProcess.restype=w.HANDLE;k.GetCurrentThread.restype=w.HANDLE
k.GetProcessInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.GetProcessInformation.restype=w.BOOL
k.GetThreadInformation.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];k.GetThreadInformation.restype=w.BOOL
k.GetPriorityClass.argtypes=[w.HANDLE];k.GetPriorityClass.restype=w.DWORD
result=dict(scope='New read-only SSH Python process, not a workload-window measurement',priority_class=k.GetPriorityClass(k.GetCurrentProcess()))
for name,func,handle,info in [('process',k.GetProcessInformation,k.GetCurrentProcess(),4),('thread',k.GetThreadInformation,k.GetCurrentThread(),3)]:
    v=Throttle();v.version=1;c.set_last_error(0);ok=bool(func(handle,info,c.byref(v),c.sizeof(v)))
    result[name]=dict(success=ok,error=0 if ok else c.get_last_error(),version=v.version,control_mask=v.control_mask,state_mask=v.state_mask)
print(json.dumps(result,indent=2))
