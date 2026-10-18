"""Two declared GIL-holding phases and a native waiter; no application imports."""
import ctypes as C
import json
import mmap
import os
from pathlib import Path
import sys
import threading
import time


def write(p,v):
    with p.open('x') as f:json.dump(v,f)


def main(folder,dll):
    folder.mkdir(exist_ok=False)
    with (folder/'oracle.bin').open('xb') as f:f.write(b'\0'*64)
    with (folder/'oracle.bin').open('r+b') as backing:
        shared=mmap.mmap(backing.fileno(),64);state=(C.c_uint64*8).from_buffer(shared)
        raw=C.CDLL(str(dll));held=C.PyDLL(str(dll))
        raw.Prepare.argtypes=[C.POINTER(C.c_uint64)];raw.Prepare.restype=C.c_uint32
        raw.Finish.argtypes=[];raw.Finish.restype=C.c_int
        held.HoldNative.argtypes=[C.POINTER(C.c_uint64),C.c_int];held.HoldNative.restype=None
        waiter=raw.Prepare(state);assert waiter>0 and state[6]>0
        tids={'waiter':waiter,'native_beat':state[6]};barrier=threading.Barrier(3)
        turns=[threading.Event(),threading.Event()]
        def hold_a():held.HoldNative(state,1)
        def hold_b():held.HoldNative(state,2)
        def owner(i):
            tids[str(i+1)]=threading.get_native_id();barrier.wait()
            assert turns[i].wait(30)
            (hold_a if i==0 else hold_b)()
        workers=[threading.Thread(target=owner,args=(i,)) for i in range(2)]
        for t in workers:t.start()
        barrier.wait();write(folder/'ready.json',dict(pid=os.getpid(),tids=tids,oracle_address=C.addressof(state)))
        for phase in (1,2):
            deadline=time.monotonic()+20
            while not (folder/f'go{phase}').exists():
                if time.monotonic()>deadline:raise TimeoutError('Controller phase not received')
                time.sleep(.005)
            turns[phase-1].set();workers[phase-1].join(8);assert not workers[phase-1].is_alive()
            deadline=time.monotonic()+3
            while state[5]!=phase:
                if time.monotonic()>deadline:raise TimeoutError('Native waiter did not acquire after release')
                time.sleep(.005)
            write(folder/f'done{phase}.json',dict(phase=phase,host_ns=time.perf_counter_ns(),acquired=state[5]))
        assert raw.Finish()
        write(folder/'complete.json',dict(pid=os.getpid(),completed=True,host_ns=time.perf_counter_ns(),heartbeat=state[3],acquired=state[5]))
        del state;shared.close()


if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
