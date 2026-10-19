"""Current-process execution-speed opt-out only; no system policy changes."""
import ctypes as c
from ctypes import wintypes as w

class Throttle(c.Structure):
    _fields_=[('version',w.DWORD),('control_mask',w.DWORD),('state_mask',w.DWORD)]

class API:
    def __init__(self):
        self.k=c.WinDLL('kernel32',use_last_error=True)
        self.k.GetCurrentProcess.restype=w.HANDLE
        for name in ('GetProcessInformation','SetProcessInformation'):
            f=getattr(self.k,name);f.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD];f.restype=w.BOOL
        self.handle=self.k.GetCurrentProcess()
    def read(self):
        v=Throttle();v.version=1
        if not self.k.GetProcessInformation(self.handle,4,c.byref(v),c.sizeof(v)):raise c.WinError(c.get_last_error())
        return dict(version=v.version,control_mask=v.control_mask,state_mask=v.state_mask)
    def set(self,value):
        v=Throttle(**value)
        if not self.k.SetProcessInformation(self.handle,4,c.byref(v),c.sizeof(v)):raise c.WinError(c.get_last_error())

def configure(api,variant):
    if variant not in ('default','optout'):raise ValueError('Unknown variant')
    before=api.read()
    if before['version']!=1 or before['control_mask']&1 or before['state_mask']&1:raise ValueError('Unexpected baseline execution-speed policy')
    expected=dict(before)
    if variant=='optout':
        expected['control_mask']|=1;expected['state_mask']&=~1
        api.set(expected)
    after=api.read()
    if after!=expected:raise ValueError('QoS configuration not delivered')
    return dict(variant=variant,before=before,after=after)
