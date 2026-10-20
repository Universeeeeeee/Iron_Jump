"""Two-second idle observation, independent perCPU OS counters at endpoints."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import time
from winapi import anchor
HERE=Path(__file__).resolve().parent
class Processor(c.Structure):
    _fields_=[('idle',c.c_int64),('kernel_including_idle',c.c_int64),('user',c.c_int64),('DPC',c.c_int64),('interrupt',c.c_int64),('interrupt_count',c.c_uint32)]

def snapshot():
    assert c.sizeof(Processor)==48
    n=os.cpu_count();assert n==8
    buffer=(Processor*n)();length=w.ULONG();nt=c.WinDLL('ntdll')
    nt.NtQuerySystemInformation.argtypes=[c.c_int,w.LPVOID,w.ULONG,c.POINTER(w.ULONG)];nt.NtQuerySystemInformation.restype=c.c_long
    before=anchor();status=nt.NtQuerySystemInformation(8,buffer,c.sizeof(buffer),c.byref(length));after=anchor()
    assert status==0 and length.value==c.sizeof(buffer)
    return dict(before=before,after=after,rows=[{name:getattr(v,name) for name,_ in Processor._fields_} for v in buffer])
if __name__=='__main__':
    plan=json.loads((HERE/'capture_plan02.json').read_text());r=dict(before=snapshot(),pid=os.getpid())
    time.sleep(plan['idle_seconds']);r['after']=snapshot()
    with (HERE/'target01.json').open('x') as f:json.dump(r,f,indent=2)
