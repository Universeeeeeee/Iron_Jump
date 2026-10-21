"""Explicit demonstration source: synthetic contacts, never a USB fallback."""

from __future__ import annotations

import time

from qtpy.QtCore import QObject, QThread, QTimer, QMetaObject, Qt, Signal, Slot


def gait_contact_frame(time_s: float) -> list[int]:
    """96 beams; alternating 600 ms stance / 400 ms swing after a clear lead-in.

    Fixed, separated footprints keep this fixture interpretable. It represents
    contact timing only, not measured foot motion or a subject's gait.
    """
    bits = [0] * 96
    elapsed_ms = round(time_s * 1000) - 200
    if elapsed_ms < 0:
        return bits
    for offset_ms, start in ((0, 12), (500, 50)):
        phase_ms = elapsed_ms - offset_ms
        if phase_ms >= 0 and phase_ms % 1000 < 600:
            bits[start:start + 16] = [1] * 16
    return bits


class SimulatedGaitWorker(QObject):
    raw_contact_signal = Signal(list, float)
    data_received = Signal(str)
    device_state_changed = Signal(str, str)

    def __init__(self, **_kwargs):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)
        self._origin = 0.0
        self._sample = 0

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit("connected", "演示模式：模拟接触信号，未连接真实设备")

    @Slot()
    def start_capture(self):
        self._origin = time.perf_counter()
        self._sample = 0
        self._timer.start()
        self.device_state_changed.emit("streaming", "演示模式：正在生成模拟步态数据")

    @Slot()
    def _tick(self):
        target = int((time.perf_counter() - self._origin) * 1000)
        # Keep timestamps at 1 kHz regardless of Qt timer jitter. Never invent
        # samples to cover a long event-loop stall: fail visibly instead.
        if target - self._sample > 1000:
            self._timer.stop()
            self.device_state_changed.emit("error", "模拟采集超时，请结束并重新开始演示")
            return
        while self._sample < target:
            seconds = self._sample / 1000
            self.raw_contact_signal.emit(gait_contact_frame(seconds), self._origin + seconds)
            self._sample += 1

    def stop(self):
        if QThread.currentThread() == self.thread():
            self._stop()
        elif self.thread().isRunning():
            QMetaObject.invokeMethod(self, "_stop", Qt.BlockingQueuedConnection)

    @Slot()
    def _stop(self):
        self._timer.stop()
        self.device_state_changed.emit("disconnected", "模拟采集已停止")
