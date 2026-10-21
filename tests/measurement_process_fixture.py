"""Deterministic saved/synthetic workers; never load a USB DLL."""
import time
import numpy as np
from qtpy.QtCore import QObject, Signal, Slot, QTimer
from hardware.sensor_frame import DeviceLayout, SensorFrame


class SyntheticWorker(QObject):
    raw_contact_signal = Signal(list, float)
    data_received = Signal(str)
    device_state_changed = Signal(str, str)
    led_health_changed = Signal(dict)
    layout_detected = Signal(object)
    sensor_frame_received = Signal(object)
    acquisition_issue = Signal(object)

    def __init__(self, **kwargs):
        super().__init__()
        self.layout = DeviceLayout.linear(3)
        self.index = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1)
        self.timer.timeout.connect(self.feed)

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit('connected', 'Synthetic test source')

    @Slot()
    def prepare_walking_capture(self):
        self.layout_detected.emit(self.layout)
        self.device_state_changed.emit('streaming', 'Synthetic test source')
        self.timer.start()

    @Slot()
    def start_capture(self):
        self.prepare_walking_capture()

    @Slot()
    def refresh_led_health(self):
        self.led_health_changed.emit({'status': 'normal', 'sample_count': 1})

    @Slot()
    def feed(self):
        for _ in range(20):
            i = self.index
            if i >= 9000:
                self.timer.stop()
                return
            ranges = [(position - .1, position + .1) for start, end, position in
                      ((4500,5200,.35),(5000,5700,.95),(5500,6200,1.55),(6000,6700,2.15)) if start <= i < end]
            bits = np.array([int(any(a <= x <= b for a,b in ranges)) for x in self.layout.positions_m], np.uint8)
            self.sensor_frame_received.emit(SensorFrame('synthetic', self.layout, i, i, time.perf_counter_ns(),
                bits.tobytes(), bytes([1])*len(bits), np.packbits(1-bits,bitorder='little').tobytes()))
            self.index += 1

    @Slot()
    def stop(self):
        self.timer.stop()

class FailingWorker:
    def __init__(self, **kwargs):
        raise RuntimeError('injected worker preparation failure')
