"""Two alternating native GIL holders with an independent shared-memory oracle."""
import ctypes as C
import json
import mmap
import os
from pathlib import Path
import sys
import threading
import time


def write(path, value):
    with path.open('x') as out:
        json.dump(value, out)


def main(folder):
    assert os.name == 'nt'
    folder.mkdir(exist_ok=False)
    with (folder / 'oracle.bin').open('xb') as out:
        out.write(b'\0' * 32)
    backing = (folder / 'oracle.bin').open('r+b')
    shared = mmap.mmap(backing.fileno(), 32)
    epoch, phase, owner, heart = [C.c_uint64.from_buffer(shared, i * 8) for i in range(4)]
    library = C.PyDLL('kernel32')
    library.Sleep.argtypes, library.Sleep.restype = [C.c_uint32], None
    turns = [threading.Event(), threading.Event()]
    stop = threading.Event()
    barrier = threading.Barrier(4)
    tids = {}

    def publish(value):
        epoch.value += 1  # Odd while updating, even when the whole marker is coherent.
        phase.value = value
        owner.value = threading.get_native_id() if value else 0
        epoch.value += 1

    def hold_a():
        publish(1)
        library.Sleep(37)  # PyDLL keeps the GIL, including during the native wait.
        publish(0)

    def hold_b():
        publish(2)
        library.Sleep(53)
        publish(0)

    def worker(i):
        tids[str(i + 1)] = threading.get_native_id()
        barrier.wait()
        while True:
            turns[i].wait()
            turns[i].clear()
            if stop.is_set():
                return
            (hold_a if i == 0 else hold_b)()
            turns[1 - i].set()

    def heartbeat():
        tids['heartbeat'] = threading.get_native_id()
        barrier.wait()
        while not stop.is_set():
            heart.value += 1
            time.sleep(.005)

    threads = [threading.Thread(target=worker, args=(i,), name='Holder' + str(i + 1)) for i in range(2)]
    threads.append(threading.Thread(target=heartbeat, name='IndependentHeartbeat'))
    for thread in threads:
        thread.start()
    barrier.wait()
    write(folder / 'ready.json', dict(pid=os.getpid(), tids=tids))
    deadline = time.monotonic() + 20
    while not (folder / 'go').exists():
        if time.monotonic() > deadline:
            raise TimeoutError('No controller go')
        time.sleep(.01)
    begin = time.perf_counter_ns()
    write(folder / 'phase_begin.json', dict(host_ns=begin))
    turns[0].set()
    while time.perf_counter_ns() - begin < 6 * 10**9:
        time.sleep(.005)
    stop.set()
    for turn in turns:
        turn.set()
    for thread in threads:
        thread.join()
    write(folder / 'complete.json', dict(completed=True, pid=os.getpid(), host_ns=time.perf_counter_ns()))
    del epoch, phase, owner, heart
    shared.close()
    backing.close()


if __name__ == '__main__':
    main(Path(sys.argv[1]))
