"""Fixed wall-time gaps, never an active compute primer or optional retry."""
import ctypes as C
import time


class Power(C.Structure):
    _fields_=[('ac',C.c_ubyte),('flag',C.c_ubyte),('percent',C.c_ubyte),('reserved',C.c_ubyte),
              ('life',C.c_uint32),('full',C.c_uint32)]


class SystemReader:
    def __init__(self):
        assert C.sizeof(Power)==12
        self.k=C.PyDLL('kernel32',use_last_error=True)
        self.k.GetSystemTimes.argtypes=[C.POINTER(C.c_uint64)]*3;self.k.GetSystemTimes.restype=C.c_int
        self.k.GetSystemPowerStatus.argtypes=[C.POINTER(Power)];self.k.GetSystemPowerStatus.restype=C.c_int
    def read(self):
        begin=time.perf_counter_ns();idle=C.c_uint64();kernel=C.c_uint64();user=C.c_uint64();power=Power()
        if not self.k.GetSystemTimes(C.byref(idle),C.byref(kernel),C.byref(user)):raise C.WinError(C.get_last_error())
        if not self.k.GetSystemPowerStatus(C.byref(power)):raise C.WinError(C.get_last_error())
        return dict(begin_ns=begin,end_ns=time.perf_counter_ns(),idle_100ns=idle.value,kernel_including_idle_100ns=kernel.value,
                    user_100ns=user.value,ac=power.ac,battery_percent=power.percent)


def busy(a,b):
    total=b['kernel_including_idle_100ns']+b['user_100ns']-a['kernel_including_idle_100ns']-a['user_100ns']
    idle=b['idle_100ns']-a['idle_100ns']
    assert total>0 and 0<=idle<=total
    return 100*(total-idle)/total


def gap(exit_ns,seconds,reader,emit):
    deadline=exit_ns+int(seconds*1e9);rows=[];next_notice=time.perf_counter_ns()
    while True:
        now=time.perf_counter_ns()
        if now>=deadline:break
        rows.append(reader.read())
        if now>=next_notice:
            emit(dict(event='spacing_wait',remaining_seconds=round((deadline-now)/1e9,1)))
            next_notice=now+30_000_000_000
        time.sleep(min(5,max(0,(deadline-time.perf_counter_ns())/1e9)))
    return dict(previous_exit_observed_ns=exit_ns,requested_gap_seconds=seconds,deadline_ns=deadline,
                wait_finished_ns=time.perf_counter_ns(),system_samples=rows,
                scope='System aggregate CPU/power during no-target interval only. Does not guarantee per-core idleness or stable temperature/frequency.')
