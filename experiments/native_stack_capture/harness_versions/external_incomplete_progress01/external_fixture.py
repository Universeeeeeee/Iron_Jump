"""Cooperating synthetic target for the final external observer; no application/devices."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import threading
import time
from winapi import anchor


def main(a):
    from PySide6.QtCore import QMutex,QWaitCondition
    a.output.mkdir(parents=True,exist_ok=False)
    clock_start=anchor()
    stop=threading.Event()
    ready=threading.Barrier(5)
    progress={}
    tids={}
    def worker(name):
        mutex,condition=QMutex(),QWaitCondition()
        sleep=ctypes.WinDLL('kernel32').Sleep
        tids[name]=threading.get_native_id()
        progress[name]=0
        ready.wait()
        value=1
        while not stop.is_set():
            if name.startswith('cpu'):
                for _ in range(10000):value=(value*13+7)%10000019
                progress[name]+=10000
            elif name=='qt_wait':
                mutex.lock();condition.wait(mutex,25);mutex.unlock()
                progress[name]+=1
            else:
                sleep(25);progress[name]+=1
    names=['cpu_a','cpu_b','qt_wait','system_wait']
    threads=[threading.Thread(target=worker,args=(n,)) for n in names]
    for thread in threads:thread.start()
    ready.wait()
    roles=dict(cpu_a='gui',cpu_b='consumer',qt_wait='reader',system_wait='gui')
    targets=[dict(pid=os.getpid(),tid=tids[n],role='sdk' if a.process=='sdk' else roles[n],name=n,
                  synthetic_only=True,fixture_process=a.process) for n in names]
    print(json.dumps(dict(pid=os.getpid(),targets=targets,synthetic_only=True)),flush=True)
    history=[]
    deadline=time.monotonic()+90
    try:
        while not a.stop.exists() and time.monotonic()<deadline:
            before=time.perf_counter_ns()
            work=dict(progress)
            after=time.perf_counter_ns()
            history.append(dict(host_before_ns=before,host_after_ns=after,work=work))
            time.sleep(.05)
        if not a.stop.exists():raise TimeoutError('Synthetic fixture watchdog')
    finally:
        stop.set()
        for thread in threads:thread.join(2)
        if any(t.is_alive() for t in threads):raise RuntimeError('Synthetic thread did not stop')
        (a.output/'progress.json').write_text(json.dumps(dict(pid=os.getpid(),process=a.process,
            targets=targets,history=history,anchors=[clock_start,anchor()],synthetic_only=True),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('process',choices=['gui','sdk'])
    p.add_argument('output',type=Path)
    p.add_argument('stop',type=Path)
    main(p.parse_args())
