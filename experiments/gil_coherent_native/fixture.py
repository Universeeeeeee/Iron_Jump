"""Synthetic native GIL owner with no Python evaluation frame; no application imports."""
import ctypes as C
import json
import mmap
import os
from pathlib import Path
import sys
import threading
import time


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream)


def main(folder, dll):
    assert os.name == 'nt'
    folder.mkdir(exist_ok=False)
    with (folder / 'oracle.bin').open('xb') as out:
        out.write(b'\0' * 32)
    with (folder / 'oracle.bin').open('r+b') as backing:
        shared = mmap.mmap(backing.fileno(), 32)
        state = (C.c_uint64 * 4).from_buffer(shared)
        native = C.CDLL(str(dll))
        native.Prepare.argtypes = [C.POINTER(C.c_uint64)]
        native.Prepare.restype = C.c_uint32
        native.Go.argtypes = native.Finish.argtypes = []
        native.Go.restype = native.Finish.restype = C.c_int
        tid = native.Prepare(state)
        assert tid > 0
        stop = threading.Event()
        ready = threading.Event()
        tids = {}
        def heartbeat():
            tids['heartbeat'] = threading.get_native_id()
            ready.set()
            while not stop.is_set():
                state[3] += 1
                time.sleep(.005)
        thread = threading.Thread(target=heartbeat, name='IndependentHeartbeat')
        thread.start(); ready.wait()
        write(folder / 'ready.json', dict(pid=os.getpid(), tids=dict(native=tid, **tids)))
        deadline = time.monotonic() + 20
        while not (folder / 'go').exists():
            if time.monotonic() > deadline:
                raise TimeoutError('Controller go not received')
            time.sleep(.01)
        assert native.Go()
        assert native.Finish()
        # Recovery is independently visible in the shared heartbeat after release.
        time.sleep(.1)
        stop.set(); thread.join()
        write(folder / 'complete.json', dict(pid=os.getpid(), completed=True, host_ns=time.perf_counter_ns(), heartbeat=state[3]))
        del state
        shared.close()


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
