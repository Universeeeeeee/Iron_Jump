"""Read-only PDH performance/power observations; never changes OS policy."""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import sys
import time

class Value(c.Structure):
    _fields_ = [('status',w.DWORD),('value',c.c_double)]

class Power(c.Structure):
    _fields_ = [('ac',c.c_ubyte),('flag',c.c_ubyte),('percent',c.c_ubyte),
                ('reserved',c.c_ubyte),('life',w.DWORD),('full',w.DWORD)]

def run(output, stop, seconds):
    pdh=c.WinDLL('pdh');kernel=c.WinDLL('kernel32',use_last_error=True)
    pdh.PdhOpenQueryW.argtypes=[w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
    pdh.PdhAddEnglishCounterW.argtypes=[w.HANDLE,w.LPCWSTR,c.c_size_t,c.POINTER(w.HANDLE)]
    pdh.PdhCollectQueryData.argtypes=[w.HANDLE]
    pdh.PdhGetFormattedCounterValue.argtypes=[w.HANDLE,w.DWORD,c.POINTER(w.DWORD),c.POINTER(Value)]
    pdh.PdhCloseQuery.argtypes=[w.HANDLE]
    kernel.GetSystemPowerStatus.argtypes=[c.POINTER(Power)]
    query=w.HANDLE();assert pdh.PdhOpenQueryW(None,0,c.byref(query))==0
    counters={};start=time.perf_counter_ns()
    try:
        for key,path in {
            'performance_pct':r'\Processor Information(_Total)\% Processor Performance',
            'busy_pct':r'\Processor Information(_Total)\% Processor Time',
            'queue':r'\System\Processor Queue Length',
        }.items():
            handle=w.HANDLE();code=pdh.PdhAddEnglishCounterW(query,path,0,c.byref(handle))
            counters[key]=(handle,code)
        with output.open('x') as f:
            ordinal=0
            while time.perf_counter_ns()-start < seconds*1e9 and not stop.exists():
                begin=time.perf_counter_ns();cpu=time.process_time_ns();collect=pdh.PdhCollectQueryData(query);values={}
                for key,(handle,added) in counters.items():
                    value=Value();code=pdh.PdhGetFormattedCounterValue(handle,0x200|0x8000,None,c.byref(value)) if added==0 else added
                    valid=added==0 and collect==0 and code==0 and value.status in (0,1)
                    values[key]=dict(value=value.value if valid else None,add_status=added,format_status=code,data_status=value.status,valid=valid)
                power=Power();ok=bool(kernel.GetSystemPowerStatus(c.byref(power)))
                row=dict(ordinal=ordinal,begin_ns=begin,end_ns=time.perf_counter_ns(),collect_status=collect,
                         values=values,power=dict(valid=ok,ac=power.ac if ok else None,percent=power.percent if ok else None),
                         observer_cpu_ns=time.process_time_ns()-cpu)
                f.write(json.dumps(row)+'\n');f.flush();ordinal+=1
                time.sleep(max(0,1-(time.perf_counter_ns()-begin)/1e9))
    finally:pdh.PdhCloseQuery(query)

if __name__=='__main__':run(Path(sys.argv[1]),Path(sys.argv[2]),int(sys.argv[3]))
