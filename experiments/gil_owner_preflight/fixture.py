"""Known native sleep holder/releaser; shared heartbeat is independent of py-spy."""
import argparse
import ctypes as C
import json
import mmap
import os
from pathlib import Path
import threading
import time


def write(path, value):
    with path.open('x') as out:
        json.dump(value, out, indent=2)
        out.write('\n')


def held_sleep(milliseconds):
    library = C.PyDLL('kernel32')
    library.Sleep.argtypes, library.Sleep.restype = [C.c_uint32], None
    library.Sleep(milliseconds)


def released_sleep(milliseconds):
    library = C.WinDLL('kernel32')
    library.Sleep.argtypes, library.Sleep.restype = [C.c_uint32], None
    library.Sleep(milliseconds)


def main(output, mode):
    assert os.name == 'nt'
    output.mkdir(exist_ok=False)
    with (output / 'heartbeat.bin').open('xb') as backing:
        backing.write(b'\0' * 8)
    with (output / 'heartbeat.bin').open('r+b') as backing:
        shared = mmap.mmap(backing.fileno(), 8)
        counter = C.c_uint64.from_buffer(shared)
        gate, stop = threading.Event(), threading.Event()
        barrier = threading.Barrier(3)
        identities = {}

        def heartbeat():
            identities['heartbeat'] = threading.get_native_id()
            barrier.wait()
            while not stop.is_set():
                counter.value += 1
                time.sleep(.005)

        def worker():
            identities['sleeper'] = threading.get_native_id()
            barrier.wait()
            gate.wait()
            before = time.perf_counter_ns()
            write(output / 'phase_begin.json', dict(host_ns=before,
                tid=threading.get_native_id(), mode=mode, counter=counter.value))
            (held_sleep if mode == 'held' else released_sleep)(10000)
            after = time.perf_counter_ns()
            write(output / 'phase_end.json', dict(host_ns=after,
                tid=threading.get_native_id(), counter=counter.value))

        heart = threading.Thread(target=heartbeat, name='IndependentHeartbeat')
        sleeper = threading.Thread(target=worker, name='KnownSleepThread')
        heart.start()
        sleeper.start()
        barrier.wait()
        write(output / 'ready.json', dict(pid=os.getpid(), main_tid=threading.get_native_id(),
            tids=identities, mode=mode))
        deadline = time.monotonic() + 20
        while not (output / 'go').exists():
            if time.monotonic() > deadline:
                raise TimeoutError('No controller go marker')
            time.sleep(.01)
        gate.set()
        sleeper.join()
        stop.set()
        heart.join()
        del counter
        shared.close()
    write(output / 'complete.json', dict(pid=os.getpid(), mode=mode, completed=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('held', 'released'))
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    main(args.output, args.mode)
