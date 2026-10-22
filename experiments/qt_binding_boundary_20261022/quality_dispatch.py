"""A single experimental same-thread quality->engine boundary control."""
import json
import os
from pathlib import Path
import threading


class Dispatch:
    def __init__(self, owner, signal, mode):
        self.owner, self.signal, self.mode = owner, signal, mode
        self.callback = None
        self.tid = None
        self.count = 0

    def connect(self, callback):
        assert self.callback is None
        assert callback.__self__ is self.owner.parent()
        assert callback.__name__ == 'process_quality_frame'
        self.callback = callback
        if self.mode == 'qt':
            self.signal.connect(callback)

    def emit(self, *args):
        from qtpy.QtCore import QThread
        tid = threading.get_native_id()
        if self.tid is None:
            assert QThread.currentThread() == self.owner.thread() == self.owner.parent().thread()
            self.tid = tid
        assert tid == self.tid
        assert self.callback is not None
        self.count += 1
        if self.mode == 'qt':
            return self.signal.emit(*args)
        return self.callback(*args)


def install(r):
    from engine.device_quality_session import DeviceQualitySession
    mode = os.environ['IJ_QUALITY_DISPATCH']
    assert mode in ('qt', 'python')
    original_init = DeviceQualitySession.__init__
    original_flush = r.flush
    observed = []
    written = False

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.frame_ready = Dispatch(self, self.frame_ready, mode)
        observed.append(self.frame_ready)

    def flush():
        nonlocal written
        original_flush()
        if not written:
            path = Path(os.environ['IJ_REPLAY_OUTPUT']) / f'quality_dispatch_{os.getpid()}.json'
            with path.open('x') as stream:
                json.dump(dict(mode=mode, pid=os.getpid(), deliveries=[dict(count=d.count, tid=d.tid) for d in observed]), stream, indent=2)
            written = True

    DeviceQualitySession.__init__ = init
    r.flush = flush
