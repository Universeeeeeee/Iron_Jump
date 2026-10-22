"""Control only the reader-to-inbox DirectConnection, with quality Qt restored."""
import json
import os
from pathlib import Path
import threading


class SourceDispatch:
    def __init__(self, signal, mode):
        self.signal, self.mode = signal, mode
        self.callback = None
        self.tid = None
        self.count = 0

    def connect(self, callback, connection_type):
        from qtpy.QtCore import Qt
        from ui.session_controller import _GroundFrameInbox
        assert connection_type == Qt.DirectConnection
        assert isinstance(callback.__self__, _GroundFrameInbox)
        assert callback.__name__ == 'on_frame' and self.callback is None
        self.callback = callback
        if self.mode == 'qt':
            self.signal.connect(callback, connection_type)

    def emit(self, frame):
        tid = threading.get_native_id()
        if self.tid is None:
            self.tid = tid
        assert tid == self.tid and self.callback is not None
        self.count += 1
        if self.mode == 'qt':
            return self.signal.emit(frame)
        return self.callback(frame)


def install(r):
    mode = os.environ['IJ_SOURCE_DISPATCH']
    assert mode in ('qt', 'python')
    original_init, original_flush = r.ReplayWorker.__init__, r.flush
    observed = []
    written = False

    def init(self, **kwargs):
        original_init(self, **kwargs)
        self.sensor_frame_received = SourceDispatch(self.sensor_frame_received, mode)
        observed.append(self.sensor_frame_received)

    def flush():
        nonlocal written
        original_flush()
        if not written:
            path = Path(os.environ['IJ_REPLAY_OUTPUT']) / f'source_dispatch_{os.getpid()}.json'
            with path.open('x') as stream:
                json.dump(dict(mode=mode, pid=os.getpid(), deliveries=[dict(count=d.count, tid=d.tid) for d in observed]), stream, indent=2)
            written = True

    r.ReplayWorker.__init__, r.flush = init, flush
