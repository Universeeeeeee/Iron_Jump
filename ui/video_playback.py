"""Background AVI decoding and a capture-time based playback clock."""

import threading
import time

import numpy as np
from qtpy.QtCore import QObject, QThread, QTimer, Signal

from camera.avi_video import AviVideo


class _Decoder(QThread):
    delivered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._condition = threading.Condition()
        self._pending = None
        self._stopping = False

    def submit(self, command):
        # One mailbox: scrubbing replaces queued requests instead of growing a queue.
        with self._condition:
            self._pending = command
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopping = True
            self._condition.notify()
        self.wait()

    def run(self):
        video = None
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stopping or self._pending is not None)
                    if self._stopping:
                        return
                    kind, generation, request, value = self._pending
                    self._pending = None
                try:
                    if kind in ("open", "close"):
                        if video is not None:
                            video.close()
                            video = None
                    if kind == "close":
                        continue
                    if kind == "open":
                        video = AviVideo(value)
                        payload = (video.info, video.read(0))
                    else:
                        payload = (value, video.read(value))
                    self.delivered.emit((kind, generation, request, payload))
                except Exception as exc:
                    self.delivered.emit(("error", generation, request, str(exc)))
        finally:
            if video is not None:
                video.close()


class VideoPlayback(QObject):
    opened = Signal(object)
    frame_ready = Signal(object, int, float)
    playing_changed = Signal(bool)
    error = Signal(str)
    pending_changed = Signal(bool)

    def __init__(self, parent=None, *, clock=time.monotonic):
        super().__init__(parent)
        self.info = None
        self.index = 0
        self.playing = False
        self.rate = 1.0
        self._clock = clock
        self._generation = 0
        self._request_id = 0
        self._requested_index = 0
        self._busy = False
        self._frame_valid = False
        self._worker = None
        self._timer = QTimer(self)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._tick)

    @property
    def is_frame_pending(self):
        return self._busy

    def _set_busy(self, busy):
        self._busy = busy
        self.pending_changed.emit(busy)

    def freeze_current_frame(self):
        """Keep the displayed frame, invalidating any outstanding decode result."""
        if self.info is None or not self._frame_valid:
            return False
        self.pause()
        self._request_id += 1
        self._requested_index = self.index
        self._set_busy(False)
        return True

    def open(self, path):
        self.close()
        if self._worker is None:
            self._worker = _Decoder(self)
            self._worker.delivered.connect(self._deliver)
            self._worker.start()
        self._set_busy(True)
        self._worker.submit(("open", self._generation, self._request_id, str(path)))

    def close(self):
        self.pause()
        self._generation += 1
        self.info = None
        self.index = self._requested_index = 0
        self.rate = 1.0
        self._frame_valid = False
        self._set_busy(False)
        if self._worker is not None:
            self._worker.submit(("close", self._generation, self._request_id, None))

    def shutdown(self):
        self.close()
        if self._worker is not None:
            self._worker.stop()
            self._worker.deleteLater()
            self._worker = None

    def _request(self, index):
        self._requested_index = index
        self._request_id += 1
        self._set_busy(True)
        self._worker.submit(("read", self._generation, self._request_id, index))

    def seek(self, index):
        if self.info is None:
            return
        self.pause()
        self._request(max(0, min(int(index), self.info.frame_count - 1)))

    def step(self, delta):
        self.seek(self._requested_index + delta)

    def play(self):
        if self.info is None or self.playing:
            return
        if self._requested_index == self.info.frame_count - 1:
            self._request(0)
        self._anchor_time = float(self.info.times[self._requested_index])
        self._anchor_clock = self._clock()
        self.playing = True
        self._timer.start()
        self.playing_changed.emit(True)

    def pause(self):
        self._timer.stop()
        if self.playing:
            self.playing = False
            self.playing_changed.emit(False)

    def set_rate(self, rate):
        if rate not in (0.25, 0.5, 1.0):
            raise ValueError(rate)
        if self.playing:
            self._anchor_time += (self._clock() - self._anchor_clock) * self.rate
            self._anchor_clock = self._clock()
        self.rate = rate

    def _tick(self):
        if not self.playing or self.info is None or self._busy:
            return
        target = self._anchor_time + (self._clock() - self._anchor_clock) * self.rate
        index = min(self.info.frame_count - 1, max(0, int(np.searchsorted(self.info.times, target, side="right")) - 1))
        if index != self.index:
            self._request(index)
        elif index == self.info.frame_count - 1:
            self.pause()

    def _deliver(self, result):
        kind, generation, request, payload = result
        if generation != self._generation or request != self._request_id:
            return
        if kind == "error":
            self._frame_valid = False
            self.pause()
            self._requested_index = self.index
            self.error.emit(payload)
            self._set_busy(False)
            return
        if kind == "open":
            self.info, frame = payload
            self.index = self._requested_index = 0
            self.opened.emit(self.info)
        else:
            self.index, frame = payload
        self._frame_valid = True
        self.frame_ready.emit(frame, self.index, float(self.info.times[self.index]))
        self._set_busy(False)
        if self.index == self.info.frame_count - 1:
            self.pause()
