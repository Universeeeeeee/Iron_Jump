"""Fixed native loops separated by actual Sleep boundaries; no original workload."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import threading
from probe import CODE
from winapi import anchor,current_thread

HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    plan=json.loads((HERE/'capture_plan02.json').read_text())
    assert hashlib.sha256(CODE).hexdigest()==plan['code_sha256']
    k=c.WinDLL('kernel32',use_last_error=True)
    k.VirtualAlloc.argtypes=[c.c_void_p,c.c_size_t,w.DWORD,w.DWORD];k.VirtualAlloc.restype=c.c_void_p
    k.VirtualProtect.argtypes=[c.c_void_p,c.c_size_t,w.DWORD,c.POINTER(w.DWORD)];k.VirtualProtect.restype=w.BOOL
    k.VirtualFree.argtypes=[c.c_void_p,c.c_size_t,w.DWORD];k.VirtualFree.restype=w.BOOL
    k.GetCurrentProcess.restype=w.HANDLE
    k.FlushInstructionCache.argtypes=[w.HANDLE,c.c_void_p,c.c_size_t];k.FlushInstructionCache.restype=w.BOOL
    k.Sleep.argtypes=[w.DWORD]
    record=dict(pid=os.getpid(),tid=threading.get_native_id(),rows=[],errors=[],complete=False)
    pointer=None
    try:
        pointer=k.VirtualAlloc(None,len(CODE),0x3000,0x04);assert pointer
        c.memmove(pointer,CODE,len(CODE));old=w.DWORD()
        assert k.VirtualProtect(pointer,len(CODE),0x20,c.byref(old))
        assert k.FlushInstructionCache(k.GetCurrentProcess(),pointer,len(CODE))
        function=c.CFUNCTYPE(c.c_uint64,c.c_uint64)(pointer)
        record['positive_controls']={str(n):function(n) for n in (1,2,17)}
        assert all(v==int(n)*16 for n,v in record['positive_controls'].items())
        for ordinal,count in enumerate(plan['iterations']):
            k.Sleep(10)
            before=current_thread();begin=anchor()
            value=function(count)
            end=anchor();after=current_thread()
            # End boundary precedes sleep; save only after the thread has yielded.
            k.Sleep(10)
            assert value==count*16
            record['rows'].append(dict(ordinal=ordinal,iterations=count,value=value,before=before,begin=begin,end=end,after=after))
        record['complete']=True
    except BaseException as error:record['errors'].append(repr(error))
    finally:
        record['memory_released']=bool(pointer and k.VirtualFree(pointer,0,0x8000))
        with (HERE/'target01.json').open('x') as f:json.dump(record,f,indent=2)
    raise SystemExit(int(not record['complete'] or not record['memory_released']))
