"""Synthetic CPU/GIL/Qt/system wait witnesses; no application, USB or camera imports."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import threading
import time
from winapi import anchor, current_thread


def main(output, seconds):
    from PySide6.QtCore import QMutex, QWaitCondition
    output.mkdir(exist_ok=False)
    barrier = threading.Barrier(5)
    stop = threading.Event()
    reports = {}
    def worker(role):
        mutex, condition = QMutex(), QWaitCondition()
        sleep = ctypes.WinDLL('kernel32').Sleep
        barrier.wait()
        before = current_thread()
        count, value = 0, 1
        if role.startswith('cpu'):
            while not stop.is_set():
                for _ in range(10000):
                    value = (value * 13 + 7) % 10000019
                count += 10000
        else:
            while not stop.is_set():
                if role == 'qt_wait':
                    mutex.lock()
                    condition.wait(mutex, 25)
                    mutex.unlock()
                else:
                    sleep(25)  # ctypes releases the GIL, genuine native timer wait
                count += 1
        after = current_thread()
        reports[role] = dict(before=before, after=after, work=count, checksum=value)
    threads = [threading.Thread(target=worker, args=(role,)) for role in
               ('cpu_a', 'cpu_b', 'qt_wait', 'system_wait')]
    for t in threads:
        t.start()
    start = anchor()
    barrier.wait()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join()
    result = dict(pid=os.getpid(), parent_pid=os.getppid(), start=start, end=anchor(),
                  seconds_requested=seconds, threads=reports, synthetic_only=True)
    (output / 'fixture.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('output', type=Path)
    p.add_argument('--seconds', type=float, default=6)
    a = p.parse_args()
    main(a.output, a.seconds)
