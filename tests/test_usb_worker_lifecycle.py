"""USB lifecycle contract: connect first, capture only after consent."""

from __future__ import annotations

import hardware.usb_worker as usb_worker


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

    def write(self, data, timeout_ms=1000):
        self.dll.set_timeout(timeout_ms)
        return len(data)

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
    for _ in range(usb_worker.LED_HEALTH_TARGET_FRAMES):
        worker._record_led_health_frame([0] * 96)
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
