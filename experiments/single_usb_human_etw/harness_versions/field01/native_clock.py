"""Same two boundary observers as the unmanned calibration; Windows only."""
import ctypes,time
from ctypes import wintypes

def thread_cpu(tids):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenThread.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenThread.restype=wintypes.HANDLE
    kernel.GetThreadTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4;kernel.GetThreadTimes.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    result={}
    for name,tid in tids.items():
        handle=kernel.OpenThread(0x0800,False,tid)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        values=[wintypes.FILETIME() for _ in range(4)]
        try:
            if not kernel.GetThreadTimes(handle,*[ctypes.byref(v) for v in values]):raise ctypes.WinError(ctypes.get_last_error())
            result[name]={'tid':tid,'kernel_100ns':(values[2].dwHighDateTime<<32)+values[2].dwLowDateTime,'user_100ns':(values[3].dwHighDateTime<<32)+values[3].dwLowDateTime}
        finally:kernel.CloseHandle(handle)
    return result

def clock_anchor():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);value=wintypes.FILETIME()
    before=time.perf_counter_ns();kernel.GetSystemTimePreciseAsFileTime(ctypes.byref(value));after=time.perf_counter_ns()
    return {'perf_before_ns':before,'perf_after_ns':after,'utc_filetime_100ns':(value.dwHighDateTime<<32)+value.dwLowDateTime}
