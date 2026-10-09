"""USB lifecycle contract: connect first, capture only after consent."""

from __future__ import annotations

import hardware.usb_worker as usb_worker
import pytest
from hardware.protocol import AckData, E_ACK, E_DATA_REPORT, UploadDataSubPack


class _FakeDll:
    def set_timeout(self, value):
        self.timeout = value


class _FakeDevice:
    def __init__(self, _dll_path):
        self.dll = _FakeDll()
        self.opened = False
        self.capture_started = False
        self.auto_read_started = False
        self.on_bytes = None
        self.on_frame = None

    def open(self, _vid, _pid):
        self.opened = True
        return True

    def start_capture(self):
        self.capture_started = True
        if self.on_frame and self.auto_read_started:
            self.on_frame(E_ACK, AckData(0), None, None)
        return 0

    def set_on_bytes(self, callback):
        self.on_bytes = callback

    def set_on_frame(self, callback):
        self.on_frame = callback

    def start_auto_read(self, _chunk, timeout_ms=None):
        self.read_timeout_ms = timeout_ms
        self.auto_read_started = True
        return 0

    def stop_auto_read(self):
        self.auto_read_started = False

    def stop_capture(self):
        self.capture_started = False
        return 0

    def write(self, data, timeout_ms=1000):
        raise AssertionError("DLL native capture must not send extra Python commands")

    def read(self, size, timeout_ms=1000):
        return b""

    def close(self):
        self.opened = False


def test_connect_does_not_start_capture(monkeypatch):
    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", _FakeDevice)
    worker = usb_worker.UsbWorker(dll_path="fake")
    states = []
    worker.device_state_changed.connect(
        lambda state, message: states.append((state, message))
    )

    worker.connect_device()

    assert worker.dev.opened
    assert not worker.dev.capture_started
    assert not worker.dev.auto_read_started
    assert states[-1][0] == "connected"

    worker.start_capture()

    assert worker.dev.capture_started
    assert worker.dev.auto_read_started
    assert worker.dev.read_timeout_ms == worker.timeout_ms
    assert states[-1][0] == "streaming"
    worker.stop()


def test_native_capture_must_be_stopped_before_draining(qapp, monkeypatch):
    class Device(_FakeDevice):
        def start_capture(self):
            self.capture_started = True
            if self.on_frame and self.auto_read_started:
                self.on_frame(E_ACK, AckData(0), None, None)
            return 0

        def stop_capture(self):
            self.capture_started = False
            return 0

        def read(self, size, timeout_ms=1000):
            return b"continuous DATA" if self.capture_started else b""

        def write(self, data, timeout_ms=1000):
            # Observed hardware: the hand-built command does not stop DATA.
            return len(data)

    monkeypatch.setattr(usb_worker, "CAPTURE_START_TIMEOUT_S", 0.04)
    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", Device)
    worker = usb_worker.UsbWorker()
    states = []
    worker.device_state_changed.connect(lambda state, message: states.append((state, message)))
    worker.connect_device()
    worker.start_capture()
    assert worker._capturing, states
    worker.stop()


@pytest.mark.parametrize("segments", [1, 3, 6, 8, 12])
def test_start_discards_previous_capture_before_ack(qapp, monkeypatch, segments):
    class BufferedDevice(_FakeDevice):
        def __init__(self, path):
            super().__init__(path)
            self.commands = []
            self.drained = False

        def read(self, size, timeout_ms=1000):
            self.drained = True
            return b""

        def start_auto_read(self, chunk, timeout_ms=None):
            result = super().start_auto_read(chunk, timeout_ms)
            # A stale stop ACK must not count as the new start ACK.
            self.on_frame(E_ACK, AckData(0), None, None)
            return result

        def stop_capture(self):
            self.commands.append("stop")
            return super().stop_capture()

        def start_capture(self):
            self.commands.append("start")
            for index in range(80062, 80078):
                self.on_frame(E_DATA_REPORT, None,
                              UploadDataSubPack(frameIdx=index, packNum=1, packIdx=0, buffer=b"\xff" * 96), None)
            result = super().start_capture()
            for index in range(3):
                self.on_frame(E_DATA_REPORT, None,
                              UploadDataSubPack(frameIdx=index, packNum=1, packIdx=0,
                                                buffer=b"\xff" * (12 * segments)), None)
            return result

    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", BufferedDevice)
    worker = usb_worker.UsbWorker()
    frames, issues = [], []
    worker.sensor_frame_received.connect(frames.append)
    worker.acquisition_issue.connect(issues.append)
    worker.connect_device()
    worker.start_capture()
    assert [f.frame_index for f in frames] == [0, 1, 2]
    assert worker.dev.drained and worker.dev.commands == ["stop", "start"]
    assert len(worker.layout.segments) == segments
    assert not issues
    # An unsolicited ACK during a test cannot authorize a device counter reset.
    worker._on_frame(E_ACK, AckData(0), None, None)
    worker._on_frame(E_DATA_REPORT, None,
                     UploadDataSubPack(frameIdx=0, packNum=1, packIdx=0,
                                       buffer=b"\xff" * (12 * segments)), None)
    assert issues[-1].code == "out_of_order_or_reset"
    first_stream = frames[0].stream_id
    worker.stop()
    worker.connect_device()
    worker.start_capture()
    assert [f.frame_index for f in frames] == [0, 1, 2, 0, 1, 2]
    assert frames[-1].stream_id != first_stream
    worker.stop()


@pytest.mark.parametrize("ack_code", [None, 1])
def test_start_ack_failure_cannot_be_revived_by_late_ack(qapp, monkeypatch, ack_code):
    class Device(_FakeDevice):
        def start_capture(self):
            self.capture_started = True
            if ack_code is not None:
                self.on_frame(E_ACK, AckData(ack_code), None, None)
            return 0

        def start_auto_read(self, chunk, timeout_ms=None):
            result = super().start_auto_read(chunk, timeout_ms)
            self.on_frame(E_ACK, AckData(0), None, None)  # old reply
            return result

    monkeypatch.setattr(usb_worker, "CAPTURE_START_TIMEOUT_S", 0.04)
    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", Device)
    worker = usb_worker.UsbWorker()
    states, frames = [], []
    worker.device_state_changed.connect(lambda state, message: states.append((state, message)))
    worker.sensor_frame_received.connect(frames.append)
    worker.connect_device()
    worker.start_capture()
    assert states[-1][0] == "error"
    assert ("应答超时" if ack_code is None else "ACK=1") in states[-1][1]
    assert not worker._capturing and not worker.dev.auto_read_started
    assert not worker.dev.capture_started
    worker._on_frame(E_ACK, AckData(0), None, None)
    worker._on_frame(E_DATA_REPORT, None,
                     UploadDataSubPack(frameIdx=0, packNum=1, buffer=b"\xff" * 12), None)
    assert not frames
    # Explicit retry is the only way to reopen the gate.
    ack_code = 0
    worker.start_capture()
    assert worker._capturing
    worker.stop()


def test_drain_consumes_old_bytes_and_fails_if_stream_does_not_stop(qapp, monkeypatch):
    class Device(_FakeDevice):
        def __init__(self, path):
            super().__init__(path)
            self.buffered = [b"old ACK", b"old DATA"]
            self.continuous = False

        def read(self, size, timeout_ms=1000):
            if self.continuous:
                return b"still streaming"
            return self.buffered.pop(0) if self.buffered else b""

    monkeypatch.setattr(usb_worker, "CAPTURE_START_TIMEOUT_S", 0.04)
    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", Device)
    worker = usb_worker.UsbWorker()
    states = []
    worker.device_state_changed.connect(lambda state, message: states.append((state, message)))
    worker.connect_device()
    worker.start_capture()
    assert not worker.dev.buffered and worker._capturing
    worker.stop()
    worker.connect_device()
    worker.dev.continuous = True
    worker.start_capture()
    assert states[-1][0] == "error" and "清理上一轮" in states[-1][1]
    assert not worker.dev.auto_read_started and not worker._capturing
    worker.stop()


def test_legacy_firmware_does_not_require_commands_or_ack(qapp, monkeypatch):
    class Device(_FakeDevice):
        def read(self, *args, **kwargs):
            raise AssertionError("Legacy stream must not be drained")

        def write(self, *args, **kwargs):
            raise AssertionError("Legacy firmware needs no capture commands")

    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", Device)
    worker = usb_worker.UsbWorker(capture_command_required=False)
    frames = []
    worker.sensor_frame_received.connect(frames.append)
    worker.connect_device()
    worker.start_capture()
    worker.dev.on_frame(E_DATA_REPORT, None,
                        UploadDataSubPack(frameIdx=456, packNum=1, buffer=b"\xff" * 36), None)
    assert len(frames) == 1 and frames[0].frame_index == 456
    worker.stop()


def test_connect_failure_emits_structured_error(monkeypatch):
    class _UnavailableDevice(_FakeDevice):
        def open(self, _vid, _pid):
            return False

    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", _UnavailableDevice)
    worker = usb_worker.UsbWorker(dll_path="fake")
    states = []
    worker.device_state_changed.connect(
        lambda state, message: states.append((state, message))
    )

    worker.connect_device()

    assert states[-1][0] == "error"
    assert "打开设备失败" in states[-1][1]


def test_led_health_summary_reports_exact_disconnected_and_flickering_leds():
    frames = [[0] * 96 for _ in range(64)]
    for frame in frames:
        frame[2] = 1
    for index, frame in enumerate(frames):
        frame[6] = index % 2

    result = usb_worker.summarize_led_health(frames)

    assert result == {
        "status": "warning",
        "sample_count": 64,
        "disconnected_leds": [3],
        "flickering_leds": [7],
    }


def test_led_health_summary_is_quiet_when_all_leds_are_stable():
    result = usb_worker.summarize_led_health([[0] * 96 for _ in range(64)])

    assert result["status"] == "normal"
    assert result["disconnected_leds"] == []
    assert result["flickering_leds"] == []


def test_led_health_summary_requires_a_minimum_sample():
    result = usb_worker.summarize_led_health([[0] * 96 for _ in range(19)])

    assert result["status"] == "insufficient"


def test_led_health_refresh_uses_short_capture_without_streaming_state(
    qtbot, monkeypatch
):
    monkeypatch.setattr(usb_worker, "CyUsbInterfaceDevice", _FakeDevice)
    worker = usb_worker.UsbWorker(dll_path="fake")
    states = []
    health_results = []
    worker.device_state_changed.connect(
        lambda state, message: states.append((state, message))
    )
    worker.led_health_changed.connect(health_results.append)
    worker.connect_device()

    worker.refresh_led_health()
    from hardware.sensor_frame import DeviceLayout, SensorFrame
    import time
    layout = DeviceLayout.linear(1)
    for index in range(usb_worker.LED_HEALTH_TARGET_FRAMES + 10):
        frame = SensorFrame('test', layout, index, index, time.perf_counter_ns(),
                            bytes(96), b'\x01' * 96, b'\xff' * 12)
        worker._record_led_health_frame(frame)
    worker._poll_led_health()

    assert [state for state, _message in states] == ["connecting", "connected"]
    assert [result["status"] for result in health_results] == [
        "checking",
        "normal",
    ]
    assert worker.dev.opened
    assert not worker.dev.capture_started
    assert not worker.dev.auto_read_started
    worker.stop()
