"""Windows observer and reversible machine-wide timer sampling interval."""
import ctypes as c
from ctypes import wintypes as w
import time


def kernel():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentThread.restype = w.HANDLE
    k.GetCurrentProcess.restype = w.HANDLE
    k.GetThreadTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
    k.QueryThreadCycleTime.argtypes = [w.HANDLE, c.POINTER(c.c_uint64)]
    return k


def anchor():
    k = kernel()
    q, f, utc = c.c_int64(), c.c_int64(), w.FILETIME()
    k.QueryPerformanceFrequency(c.byref(f))
    perf_before = time.perf_counter_ns()
    k.QueryPerformanceCounter(c.byref(q))
    before = q.value
    k.GetSystemTimePreciseAsFileTime(c.byref(utc))
    k.QueryPerformanceCounter(c.byref(q))
    perf_after = time.perf_counter_ns()
    return dict(qpc_before=before, qpc_after=q.value, frequency=f.value,
                filetime_100ns=(utc.dwHighDateTime << 32) | utc.dwLowDateTime,
                perf_ns=perf_after, perf_before_ns=perf_before, perf_after_ns=perf_after)


def current_thread():
    k = kernel()
    handle = k.GetCurrentThread()
    times = [w.FILETIME() for _ in range(4)]
    cycles = c.c_uint64()
    if not k.GetThreadTimes(handle, *[c.byref(t) for t in times]):
        raise c.WinError(c.get_last_error())
    if not k.QueryThreadCycleTime(handle, c.byref(cycles)):
        raise c.WinError(c.get_last_error())
    values = [(t.dwHighDateTime << 32) | t.dwLowDateTime for t in times]
    return dict(tid=k.GetCurrentThreadId(), creation_100ns=values[0],
                kernel_100ns=values[2], user_100ns=values[3], cycles=cycles.value,
                clock=anchor())


def profile_interval(value=None):
    # Same public API used by Microsoft TraceEventSession. Timer source = 0.
    class Interval(c.Structure):
        _fields_ = [('source', w.ULONG), ('interval', w.ULONG)]
    adv = c.WinDLL('advapi32', use_last_error=True)
    adv.TraceQueryInformation.argtypes = [c.c_uint64, c.c_int, c.c_void_p, w.ULONG, c.c_void_p]
    adv.TraceSetInformation.argtypes = [c.c_uint64, c.c_int, c.c_void_p, w.ULONG]
    data = Interval(0, 0)
    if value is not None:
        # Enable SeSystemProfilePrivilege only in this controller process.
        class Luid(c.Structure):
            _fields_ = [('low', w.DWORD), ('high', w.LONG)]
        class Privilege(c.Structure):
            _fields_ = [('count', w.DWORD), ('luid', Luid), ('attributes', w.DWORD)]
        assert c.sizeof(Privilege) == 16 and Privilege.luid.offset == 4
        token, luid = w.HANDLE(), Luid()
        adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
        if not adv.OpenProcessToken(kernel().GetCurrentProcess(), 0x28, c.byref(token)):
            raise c.WinError(c.get_last_error())
        try:
            if not adv.LookupPrivilegeValueW(None, 'SeSystemProfilePrivilege', c.byref(luid)):
                raise c.WinError(c.get_last_error())
            privilege = Privilege(1, luid, 2)
            c.set_last_error(0)
            if not adv.AdjustTokenPrivileges(token, False, c.byref(privilege), 0, None, None) or c.get_last_error():
                raise c.WinError(c.get_last_error())
        finally:
            kernel().CloseHandle.argtypes = [w.HANDLE]
            kernel().CloseHandle(token)
        data.interval = value
        code = adv.TraceSetInformation(0, 5, c.byref(data), c.sizeof(data))
        if code:
            raise OSError(code, 'TraceSetInformation interval')
    code = adv.TraceQueryInformation(0, 5, c.byref(data), c.sizeof(data), None)
    if code:
        raise OSError(code, 'TraceQueryInformation interval')
    return data.interval
