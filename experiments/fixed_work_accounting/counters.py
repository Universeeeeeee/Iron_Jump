"""Current-process OS accounting with real-clock brackets, including native pools."""
import ctypes as c
from ctypes import wintypes as w
import os

def snapshot(real):
    k=c.WinDLL('kernel32',use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE
    k.GetProcessTimes.argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4;k.GetProcessTimes.restype=w.BOOL
    k.QueryProcessCycleTime.argtypes=[w.HANDLE,c.POINTER(c.c_uint64)];k.QueryProcessCycleTime.restype=w.BOOL
    handle=k.GetCurrentProcess();values=[w.FILETIME() for _ in range(4)];cycles=c.c_uint64();begin=real()
    if not k.GetProcessTimes(handle,*[c.byref(v) for v in values]):raise c.WinError(c.get_last_error())
    if not k.QueryProcessCycleTime(handle,c.byref(cycles)):raise c.WinError(c.get_last_error())
    end=real();numbers=[(v.dwHighDateTime<<32)|v.dwLowDateTime for v in values]
    return dict(pid=os.getpid(),creation_100ns=numbers[0],kernel_100ns=numbers[2],user_100ns=numbers[3],cycles=cycles.value,begin_ns=begin,end_ns=end)

def validate(record,max_bracket_ns=1000000):
    a=record['process_before'];b=record['process_after'];consumer=record['consumer'];model=record['model']
    checks=dict(same_process=a['pid']==b['pid'] and a['creation_100ns']==b['creation_100ns'],
                monotonic=all(b[k]>=a[k] for k in ('kernel_100ns','user_100ns','cycles')),
                brackets=0<=a['end_ns']-a['begin_ns']<=max_bracket_ns and 0<=b['end_ns']-b['begin_ns']<=max_bracket_ns,
                covers_all_work=a['end_ns']<=min(consumer['begin_ns'],model['begin_ns']) and max(consumer['end_ns'],model['end_ns'],model['work_done_ns'])<=b['begin_ns'],
                close_after_accounting=b['end_ns']<=record['close_release_ns']<=model['close_begin_ns']<=model['close_end_ns'])
    cpu=(b['kernel_100ns']+b['user_100ns']-a['kernel_100ns']-a['user_100ns'])*100
    checks['contains_named_thread_CPU']=cpu+50000000>=consumer['thread_cpu_ns']+model['thread_cpu_ns']
    return dict(checks=checks,accounting_pass=all(checks.values()),process_cpu_ns=cpu,process_cycles=b['cycles']-a['cycles'],
                wall_ns_bounds=[b['begin_ns']-a['end_ns'],b['end_ns']-a['begin_ns']],
                scope='Whole-process counters include model native threads. Named-thread comparison has50ms accounting tolerance, not a precision claim. Cycles are not frequency.')
