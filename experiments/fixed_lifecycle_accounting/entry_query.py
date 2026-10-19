"""Read live newly enumerated threads after the fixed work boundary; no stack claims."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path

def query_new(tids,clock):
    k=c.PyDLL('kernel32',use_last_error=True);nt=c.PyDLL('ntdll')
    for name,args,ret in [('OpenThread',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),('CloseHandle',[w.HANDLE],w.BOOL),('GetProcessIdOfThread',[w.HANDLE],w.DWORD),('GetThreadTimes',[w.HANDLE]+[c.POINTER(w.FILETIME)]*4,w.BOOL),('GetModuleHandleExW',[w.DWORD,c.c_void_p,c.POINTER(w.HANDLE)],w.BOOL),('GetModuleFileNameW',[w.HANDLE,w.LPWSTR,w.DWORD],w.DWORD)]:
        f=getattr(k,name);f.argtypes=args;f.restype=ret
    query=nt.NtQueryInformationThread;query.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)];query.restype=c.c_long
    rows=[]
    for tid in tids:
        row=dict(tid=tid,before_ns=clock());rows.append(row);h=None
        try:
            h=k.OpenThread(0x0800,False,tid)
            if not h:raise c.WinError(c.get_last_error())
            row['owner_pid']=k.GetProcessIdOfThread(h);assert row['owner_pid']==os.getpid()
            address=c.c_void_p();length=w.ULONG();status=query(h,9,c.byref(address),c.sizeof(address),c.byref(length))
            row.update(query_status=status,query_size=length.value,entry=address.value);assert status==0 and length.value==8
            values=[w.FILETIME() for _ in range(4)]
            if not k.GetThreadTimes(h,*[c.byref(t) for t in values]):raise c.WinError(c.get_last_error())
            numbers=[(t.dwHighDateTime<<32)|t.dwLowDateTime for t in values];row.update(creation_100ns=numbers[0],exit_100ns=numbers[1],lifetime_kernel_100ns=numbers[2],lifetime_user_100ns=numbers[3])
            module=w.HANDLE()
            if not k.GetModuleHandleExW(6,address,c.byref(module)):raise c.WinError(c.get_last_error())
            path=c.create_unicode_buffer(32768);size=k.GetModuleFileNameW(module,path,len(path));assert 0<size<len(path)
            row.update(module_base=module.value,module_path=path.value,rva=address.value-module.value)
        except BaseException as exc:row['error']=repr(exc)
        finally:
            row['handle_closed']=h is None or bool(k.CloseHandle(h));row['after_ns']=clock()
    # File reads occur after timing each query, still before model close.
    for row in rows:
        if 'module_path' in row:
            try:row['module_sha256']=hashlib.sha256(Path(row['module_path']).read_bytes()).hexdigest()
            except OSError as exc:row['module_hash_error']=repr(exc)
    return rows
