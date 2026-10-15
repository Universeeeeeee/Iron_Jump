"""Validate the measurement clocks, not the algorithm's performance."""
from collections import Counter
import ctypes
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentThread.restype = ctypes.c_void_p
kernel.QueryThreadCycleTime.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64))
kernel.QueryThreadCycleTime.restype = ctypes.c_int
handle = kernel.GetCurrentThread()


def cycles():
    result = ctypes.c_uint64()
    assert kernel.QueryThreadCycleTime(handle, ctypes.byref(result))
    return result.value


if __name__ == '__main__':
    busy = []
    for i in range(2000):
        start, cpu, c = time.perf_counter_ns(), time.thread_time_ns(), cycles()
        while time.perf_counter_ns() - start < 50000:
            pass
        busy.append((time.perf_counter_ns() - start, time.thread_time_ns() - cpu, cycles() - c))
    idle = []
    for i in range(10):
        start, cpu, c = time.perf_counter_ns(), time.thread_time_ns(), cycles()
        time.sleep(.01)
        idle.append((time.perf_counter_ns() - start, time.thread_time_ns() - cpu, cycles() - c))
    result = {'declared_thread_clock': str(time.get_clock_info('thread_time')),
              'busy_wall_cpu_cycles': busy, 'sleep_wall_cpu_cycles': idle,
              'busy_cpu_delta_histogram': dict(Counter(x[1] for x in busy)),
              'scope': 'Clock granularity/independence only; not an algorithm microbenchmark'}
    (HERE / 'windows_clocks.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k:v for k,v in result.items() if 'wall_cpu' not in k}, indent=2), flush=True)
