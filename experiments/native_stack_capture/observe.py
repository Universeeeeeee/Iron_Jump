"""Read retained Windows thread handles for external short windows; no target injection."""
import ctypes as c
from ctypes import wintypes as w
import time
from winapi import anchor, kernel


class Observer:
    def __init__(self, targets):
        if not targets or len({(t['pid'],t['tid']) for t in targets})!=len(targets):
            raise ValueError('Empty or duplicate PID/TID')
        if len({(t['pid'],t.get('name',t['role'])) for t in targets})!=len(targets):
            raise ValueError('Duplicate role in a process')
        sdk = {t['pid'] for t in targets if t['role']=='sdk'}
        gui = {t['pid'] for t in targets if t['role']!='sdk'}
        if sdk & gui:
            raise ValueError('SDK must be analyzed as a distinct process')
        self.targets, self.handles = targets, []
        k = kernel()
        k.OpenThread.argtypes = [w.DWORD,w.BOOL,w.DWORD]
        k.OpenThread.restype = w.HANDLE
        k.GetProcessIdOfThread.argtypes = [w.HANDLE]
        k.GetProcessIdOfThread.restype = w.DWORD
        k.CloseHandle.argtypes = [w.HANDLE]
        try:
            for target in targets:
                if target['role'] not in ('gui','consumer','reader','sdk'):
                    raise ValueError('Use distinct gui/consumer/reader/sdk roles')
                h = k.OpenThread(0x0800,False,target['tid'])
                if not h: raise c.WinError(c.get_last_error())
                self.handles.append(h)
                if k.GetProcessIdOfThread(h) != target['pid']:
                    raise ValueError('PID/TID ownership mismatch')
        except BaseException:
            self.close()
            raise

    def snapshot(self):
        k, rows = kernel(), []
        k.GetExitCodeThread.argtypes = [w.HANDLE,c.POINTER(w.DWORD)]
        for target,h in zip(self.targets,self.handles):
            start = anchor()
            values, cycles, status = [w.FILETIME() for _ in range(4)],c.c_uint64(),w.DWORD()
            if not k.GetThreadTimes(h,*[c.byref(v) for v in values]): raise c.WinError(c.get_last_error())
            if not k.QueryThreadCycleTime(h,c.byref(cycles)): raise c.WinError(c.get_last_error())
            if not k.GetExitCodeThread(h,c.byref(status)): raise c.WinError(c.get_last_error())
            end = anchor()
            rows.append(dict(**target,creation_100ns=(values[0].dwHighDateTime<<32)|values[0].dwLowDateTime,
                             kernel_100ns=(values[2].dwHighDateTime<<32)|values[2].dwLowDateTime,
                             user_100ns=(values[3].dwHighDateTime<<32)|values[3].dwLowDateTime,
                             cycles=cycles.value,active=status.value==259,start=start,end=end))
        return rows

    def close(self):
        k=kernel();k.CloseHandle.argtypes=[w.HANDLE]
        for h in self.handles: k.CloseHandle(h)
        self.handles=[]


def observe(targets, seconds):
    observer=Observer(targets)
    try:
        before=observer.snapshot()
        time.sleep(seconds)
        after=observer.snapshot()
        if any(not t['active'] for t in before+after): raise ValueError('Target thread exited')
        if any(a['creation_100ns']!=b['creation_100ns'] for a,b in zip(before,after)): raise ValueError('Thread identity changed')
        return dict(before=before,after=after)
    finally:
        observer.close()
