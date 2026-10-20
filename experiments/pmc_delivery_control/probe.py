"""Bounded local x64 integer dependency-chain throughput; never a GHz estimator."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import platform
import time
import uuid

HERE=Path(__file__).resolve().parent
# Windows x64 RCX argument, RAX result; only volatile registers changed.
# xor eax,eax; 16*(add rax,1); dec rcx; jnz back to first add; ret.
CODE=b'\x31\xc0'+b'\x48\x83\xc0\x01'*16+b'\x48\xff\xc9\x75\xbb\xc3'

class GUID(c.Structure):
    _fields_=[('raw',c.c_ubyte*16)]

def run():
    assert platform.system()=='Windows' and platform.machine().upper()=='AMD64' and c.sizeof(c.c_void_p)==8
    plan=json.loads((HERE/'plan01.json').read_text());assert hashlib.sha256(CODE).hexdigest()==plan['code_sha256']
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==plan['source_sha256']
    k=c.WinDLL('kernel32',use_last_error=True);p=c.WinDLL('powrprof')
    k.VirtualAlloc.argtypes=[c.c_void_p,c.c_size_t,w.DWORD,w.DWORD];k.VirtualAlloc.restype=c.c_void_p
    k.VirtualProtect.argtypes=[c.c_void_p,c.c_size_t,w.DWORD,c.POINTER(w.DWORD)];k.VirtualProtect.restype=w.BOOL
    k.VirtualFree.argtypes=[c.c_void_p,c.c_size_t,w.DWORD];k.VirtualFree.restype=w.BOOL
    k.GetCurrentThread.restype=w.HANDLE;k.GetCurrentProcess.restype=w.HANDLE
    k.FlushInstructionCache.argtypes=[w.HANDLE,c.c_void_p,c.c_size_t];k.FlushInstructionCache.restype=w.BOOL
    k.QueryThreadCycleTime.argtypes=[w.HANDLE,c.POINTER(c.c_uint64)];k.QueryThreadCycleTime.restype=w.BOOL
    k.GetCurrentProcessorNumber.restype=w.DWORD
    p.PowerGetEffectiveOverlayScheme.argtypes=[c.POINTER(GUID)];p.PowerGetEffectiveOverlayScheme.restype=w.DWORD
    result=dict(rows=[],errors=[],complete=False,frequency_estimate=False)
    guid=GUID();status=p.PowerGetEffectiveOverlayScheme(c.byref(guid))
    result['overlay']=dict(status=status,guid=str(uuid.UUID(bytes_le=bytes(guid.raw))) if status==0 else None)
    pointer=None
    def cycles():
        value=c.c_uint64();assert k.QueryThreadCycleTime(k.GetCurrentThread(),c.byref(value));return value.value
    try:
        pointer=k.VirtualAlloc(None,len(CODE),0x3000,0x04);assert pointer
        c.memmove(pointer,CODE,len(CODE));old=w.DWORD()
        assert k.VirtualProtect(pointer,len(CODE),0x20,c.byref(old))
        assert k.FlushInstructionCache(k.GetCurrentProcess(),pointer,len(CODE))
        function=c.CFUNCTYPE(c.c_uint64,c.c_uint64)(pointer)
        result['positive_controls']={str(n):function(n) for n in [1,2,17]}
        assert all(v==int(n)*16 for n,v in result['positive_controls'].items())
        for count in plan['iterations']:
            assert 1<=count<=32000000
            core_before=k.GetCurrentProcessorNumber();cycle_before=cycles();cpu=time.thread_time_ns();begin=time.perf_counter_ns()
            value=function(count)
            end=time.perf_counter_ns();cpu_after=time.thread_time_ns();cycle_after=cycles();core_after=k.GetCurrentProcessorNumber()
            assert value==count*16 and end>begin and cycle_after>=cycle_before
            result['rows'].append(dict(iterations=count,dependent_adds=count*16,result=value,begin_ns=begin,end_ns=end,
                thread_cpu_ns=cpu_after-cpu,thread_cycles=cycle_after-cycle_before,core_before=core_before,core_after=core_after,
                billion_adds_per_wall_second=count*16/(end-begin)))
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result['memory_released']=bool(pointer and k.VirtualFree(pointer,0,0x8000))
        with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2));return int(not result['complete'] or not result['memory_released'])

if __name__=='__main__':raise SystemExit(run())
