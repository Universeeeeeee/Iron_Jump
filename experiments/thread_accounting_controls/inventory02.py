"""Retain current-process Windows thread identities; endpoint enumeration is not a lifecycle trace."""
import ctypes as c
from ctypes import wintypes as w
import os
import time

class Inventory:
    def __init__(self):
        if os.name!='nt':raise OSError('Windows only')
        self.k=c.PyDLL('kernel32',use_last_error=True);self.handles={}
        class Entry(c.Structure):
            _fields_=[('size',w.DWORD),('usage',w.DWORD),('tid',w.DWORD),('pid',w.DWORD),('base',w.LONG),('delta',w.LONG),('flags',w.DWORD)]
        self.Entry=Entry;assert c.sizeof(Entry)==28
        for name,args,ret in [('CreateToolhelp32Snapshot',[w.DWORD,w.DWORD],w.HANDLE),('Thread32First',[w.HANDLE,c.POINTER(Entry)],w.BOOL),('Thread32Next',[w.HANDLE,c.POINTER(Entry)],w.BOOL),('OpenThread',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),('GetProcessIdOfThread',[w.HANDLE],w.DWORD),('CloseHandle',[w.HANDLE],w.BOOL),('GetThreadTimes',[w.HANDLE]+[c.POINTER(w.FILETIME)]*4,w.BOOL),('QueryThreadCycleTime',[w.HANDLE,c.POINTER(c.c_uint64)],w.BOOL)]:
            f=getattr(self.k,name);f.argtypes=args;f.restype=ret
        try:
            for tid in self.enumerate():
                h=self.k.OpenThread(0x0800,False,tid)
                if not h:raise c.WinError(c.get_last_error())
                self.handles[tid]=h
                if self.k.GetProcessIdOfThread(h)!=os.getpid():raise ValueError('Wrong owning PID')
        except BaseException:self.close();raise
    def enumerate(self):
        h=self.k.CreateToolhelp32Snapshot(4,0)
        if h==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
        try:
            entry=self.Entry();entry.size=c.sizeof(entry);out=[]
            if not self.k.Thread32First(h,c.byref(entry)):raise c.WinError(c.get_last_error())
            while True:
                if entry.pid==os.getpid():out.append(entry.tid)
                entry.size=c.sizeof(entry)
                if not self.k.Thread32Next(h,c.byref(entry)):
                    if c.get_last_error()!=18:raise c.WinError(c.get_last_error())
                    break
            return sorted(out)
        finally:
            if not self.k.CloseHandle(h):raise c.WinError(c.get_last_error())
    def snapshot(self):
        start=time.perf_counter_ns();rows=[]
        for tid,h in self.handles.items():
            before=time.perf_counter_ns();v=[w.FILETIME() for _ in range(4)];cycles=c.c_uint64()
            if not self.k.GetThreadTimes(h,*[c.byref(x) for x in v]):raise c.WinError(c.get_last_error())
            if not self.k.QueryThreadCycleTime(h,c.byref(cycles)):raise c.WinError(c.get_last_error())
            values=[(x.dwHighDateTime<<32)|x.dwLowDateTime for x in v]
            rows.append(dict(pid=os.getpid(),tid=tid,creation_100ns=values[0],exit_100ns=values[1],kernel_100ns=values[2],user_100ns=values[3],cycles=cycles.value,before_ns=before,after_ns=time.perf_counter_ns()))
        return dict(before_ns=start,after_ns=time.perf_counter_ns(),rows=rows)
    def close(self):
        errors=[]
        for tid,h in list(self.handles.items()):
            if self.k.CloseHandle(h):del self.handles[tid]
            else:errors.append((tid,c.get_last_error()))
        if errors:raise RuntimeError(('Handle close unconfirmed',errors))

def summarize(a,b,per_read_ns=1000000,group_ns=10000000):
    amap={x['tid']:x for x in a['rows']};bmap={x['tid']:x for x in b['rows']};reasons=[]
    if len(amap)!=len(a['rows']) or len(bmap)!=len(b['rows']) or set(amap)!=set(bmap):reasons.append('retained_set_changed')
    if any(set(x['enumerated_tids'])!=set(amap) for x in (a,b)):reasons.append('endpoint_enumeration_changed')
    if any(not 0<=x['after_ns']-x['before_ns']<=group_ns for x in (a,b)):reasons.append('group_read_width')
    if a['after_ns']>b['before_ns']:reasons.append('overlapping_boundaries')
    rows=[]
    for tid in sorted(set(amap)&set(bmap)):
        x,y=amap[tid],bmap[tid]
        if (x['pid'],x['creation_100ns'])!=(y['pid'],y['creation_100ns']):reasons.append('identity_changed')
        if x['exit_100ns'] or y['exit_100ns']:reasons.append('retained_thread_exited')
        if any(not 0<=z['after_ns']-z['before_ns']<=per_read_ns for z in (x,y)):reasons.append('individual_read_width')
        d={k:y[k]-x[k] for k in ('kernel_100ns','user_100ns','cycles')}
        if min(d.values())<0:reasons.append('counter_regressed')
        rows.append(dict(tid=tid,cpu_ms=(d['kernel_100ns']+d['user_100ns'])/10000,cycles=d['cycles']))
    return dict(retained_threads_pass=not reasons,reasons=sorted(set(reasons)),threads=rows,sum_cpu_ms=sum(x['cpu_ms'] for x in rows),sum_cycles=sum(x['cycles'] for x in rows),whole_process_lifetime_coverage_proven=False)


def enumerate_timed(inventory):
    before=time.perf_counter_ns();cpu=time.thread_time_ns();tids=inventory.enumerate()
    return dict(before_ns=before,after_ns=time.perf_counter_ns(),thread_cpu_ns=time.thread_time_ns()-cpu,tids=tids)
