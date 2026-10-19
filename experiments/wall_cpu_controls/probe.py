"""Boundary-only Windows CPU accounting; never changes scheduler policy."""
import ctypes as c
from ctypes import wintypes as w
import os
import threading
import time

class Probe:
    def __init__(self):
        if os.name!='nt':raise OSError('Windows only')
        # Keep GIL across the short counter read; measurement code must not
        # itself introduce a release/reacquire boundary between these calls.
        self.k=c.PyDLL('kernel32',use_last_error=True)
        for name in ('GetCurrentThread','GetCurrentProcess'):
            getattr(self.k,name).restype=w.HANDLE
        for name in ('GetThreadTimes','GetProcessTimes'):
            getattr(self.k,name).argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4
        for name in ('QueryThreadCycleTime','QueryProcessCycleTime'):
            getattr(self.k,name).argtypes=[w.HANDLE,c.POINTER(c.c_uint64)]
    def snapshot(self):
        before=time.perf_counter_ns();result=dict(pid=os.getpid(),tid=threading.get_native_id(),thread_time_before_ns=time.thread_time_ns())
        for kind in ('thread','process'):
            handle=getattr(self.k,'GetCurrent'+kind.title())();times=[w.FILETIME() for _ in range(4)];cycles=c.c_uint64()
            if not getattr(self.k,'Get'+kind.title()+'Times')(handle,*[c.byref(t) for t in times]):raise c.WinError(c.get_last_error())
            if not getattr(self.k,'Query'+kind.title()+'CycleTime')(handle,c.byref(cycles)):raise c.WinError(c.get_last_error())
            vals=[(t.dwHighDateTime<<32)|t.dwLowDateTime for t in times]
            result[kind]=dict(creation_100ns=vals[0],exit_100ns=vals[1],kernel_100ns=vals[2],user_100ns=vals[3],cycles=cycles.value)
        result.update(thread_time_after_ns=time.thread_time_ns(),before_ns=before,after_ns=time.perf_counter_ns())
        return result

def delta(a,b,max_read_ns=1000000):
    if (a['pid'],a['tid'])!=(b['pid'],b['tid']):raise ValueError('Target identity changed')
    if any(not 0<=x['after_ns']-x['before_ns']<=max_read_ns for x in (a,b)):raise ValueError('Counter read bracket failed')
    if a['after_ns']>b['before_ns']:raise ValueError('Boundaries overlap or reverse')
    out=dict(wall_ms_bounds=[(b['before_ns']-a['after_ns'])/1e6,(b['after_ns']-a['before_ns'])/1e6])
    for kind in ('thread','process'):
        x,y=a[kind],b[kind]
        if x['creation_100ns']!=y['creation_100ns'] or x['exit_100ns'] or y['exit_100ns']:raise ValueError('Lifetime mismatch')
        d={k:y[k]-x[k] for k in ('kernel_100ns','user_100ns','cycles')}
        if min(d.values())<0:raise ValueError('Counter regressed')
        out[kind]=dict(cpu_ms=(d['kernel_100ns']+d['user_100ns'])/10000,cycles=d['cycles'])
    lo=(b['thread_time_before_ns']-a['thread_time_after_ns'])/1e6
    hi=(b['thread_time_after_ns']-a['thread_time_before_ns'])/1e6
    if lo<0 or hi<lo:raise ValueError('Thread clock regressed')
    out['thread_time_ms_bounds']=[lo,hi]
    return out
