"""Known native entry addresses, queried while both threads are alive."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from winapi import anchor

def main(a):
    a.output.mkdir(parents=True,exist_ok=False);plan=json.loads((HERE/'plan01.json').read_text());assert hashlib.sha256((HERE/'EntryOracle.dll').read_bytes()).hexdigest()==plan['dll_sha256']
    k=c.WinDLL('kernel32',use_last_error=True);nt=c.WinDLL('ntdll');dll=c.WinDLL(str(HERE/'EntryOracle.dll'))
    for name,args,ret in [('CreateEventW',[c.c_void_p,w.BOOL,w.BOOL,w.LPCWSTR],w.HANDLE),('CreateThread',[c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)],w.HANDLE),('SetEvent',[w.HANDLE],w.BOOL),('WaitForSingleObject',[w.HANDLE,w.DWORD],w.DWORD),('GetExitCodeThread',[w.HANDLE,c.POINTER(w.DWORD)],w.BOOL),('GetProcessIdOfThread',[w.HANDLE],w.DWORD),('GetThreadTimes',[w.HANDLE]+[c.POINTER(w.FILETIME)]*4,w.BOOL),('CloseHandle',[w.HANDLE],w.BOOL)]:
        f=getattr(k,name);f.argtypes=args;f.restype=ret
    query=nt.NtQueryInformationThread;query.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)];query.restype=c.c_long
    result=dict(pid=os.getpid(),threads=[],errors=[],start=anchor());handles=[];gate=None
    try:
        gate=k.CreateEventW(None,True,False,None)
        if not gate:raise c.WinError(c.get_last_error())
        for name,expected_exit in [('EntryA',11),('EntryB',22)]:
            address=c.cast(getattr(dll,name),c.c_void_p).value;tid=w.DWORD();h=k.CreateThread(None,0,address,gate,0,c.byref(tid))
            if not h:raise c.WinError(c.get_last_error())
            row=dict(name=name,tid=tid.value,expected_entry=address,expected_exit=expected_exit);result['threads'].append(row);handles.append((h,row))
            before=anchor();got=c.c_void_p();size=w.ULONG();status=query(h,9,c.byref(got),c.sizeof(got),c.byref(size));after=anchor()
            code=w.DWORD();times=[w.FILETIME() for _ in range(4)]
            if not k.GetExitCodeThread(h,c.byref(code)) or not k.GetThreadTimes(h,*[c.byref(t) for t in times]):raise c.WinError(c.get_last_error())
            row.update(query_status=status,query_size=size.value,queried_entry=got.value,query_before=before,query_after=after,owner_pid=k.GetProcessIdOfThread(h),exit_before=code.value,creation_100ns=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
            assert status==0 and size.value==c.sizeof(got) and got.value==address and code.value==259 and row['owner_pid']==os.getpid()
        assert result['threads'][0]['expected_entry']!=result['threads'][1]['expected_entry']
        if not k.SetEvent(gate):raise c.WinError(c.get_last_error())
        for h,row in handles:
            assert k.WaitForSingleObject(h,5000)==0
            code=w.DWORD();assert k.GetExitCodeThread(h,c.byref(code));row['exit_after']=code.value;assert code.value==row['expected_exit']
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        if gate:k.SetEvent(gate)
        for h,row in handles:
            row['exit_confirmed']=k.WaitForSingleObject(h,5000)==0
            row['handle_closed']=bool(k.CloseHandle(h))
        result['gate_closed']=gate is None or bool(k.CloseHandle(gate));result['end']=anchor()
        with (a.output/'fixture.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']) or not result['gate_closed'] or any(not r['exit_confirmed'] or not r['handle_closed'] for _,r in handles))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--seconds',type=float);raise SystemExit(main(p.parse_args()))
