"""Synthetic native worker has no GIL request until an external native gate opens."""
import ctypes as C
import json
import mmap
import os
from pathlib import Path
import sys
import threading
import time


def write(path, value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('x') as f:json.dump(value, f, indent=2)
    assert not path.exists();temporary.rename(path)


def main(folder, dll):
    folder.mkdir(exist_ok=False)
    with (folder/'oracle.bin').open('xb') as f:f.write(b'\0'*128)
    with (folder/'oracle.bin').open('r+b') as f:
        shared=mmap.mmap(f.fileno(),128);state=(C.c_uint64*16).from_buffer(shared)
        raw=C.CDLL(str(dll));held=C.PyDLL(str(dll))
        raw.Prepare.argtypes=[C.POINTER(C.c_uint64)];raw.Prepare.restype=C.c_uint32
        raw.Finish.argtypes=[];raw.Finish.restype=C.c_int
        held.HoldNative.argtypes=[];held.HoldNative.restype=None
        waiter=raw.Prepare(state);assert waiter and state[6]
        tids=dict(waiter=waiter,native_beat=state[6]);ready=threading.Event();turn=threading.Event()
        def hold_native():
            tids['owner']=threading.get_native_id();ready.set()
            assert turn.wait(30)
            held.HoldNative()
        owner=threading.Thread(target=hold_native);owner.start();assert ready.wait(3)
        write(folder/'ready.json',dict(pid=os.getpid(),tids=tids,oracle_address=C.addressof(state)))
        deadline=time.monotonic()+25
        while not (folder/'go').exists():
            if time.monotonic()>deadline:raise TimeoutError('Controller go missing')
            time.sleep(.002)
        turn.set();owner.join(20);assert not owner.is_alive()
        assert raw.Finish()
        write(folder/'complete.json',dict(pid=os.getpid(),host_ns=time.perf_counter_ns(),state=list(state)))
        del state;shared.close()


if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
