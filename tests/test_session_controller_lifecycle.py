"""Session controller two-stage lifecycle tests."""

from __future__ import annotations

from qtpy.QtCore import QObject, Signal, Slot
from qtpy.QtTest import QSignalSpy

import ui.session_controller as session_controller
from config.test_config import default_jump_config


class _FakeUsbWorker(QObject):
    raw_contact_signal = Signal(list, float)
    data_received = Signal(str)
    device_state_changed = Signal(str, str)
    led_health_changed = Signal(dict)

    def __init__(self, **_kwargs):
        super().__init__()
        self.stopped = False
        self.health_refreshes = 0

    @Slot()
    def connect_device(self):
        self.device_state_changed.emit("connected", "设备已连接")

    @Slot()
    def start_capture(self):
        self.device_state_changed.emit("streaming", "正在采集")

    @Slot()
    def refresh_led_health(self):
        self.health_refreshes += 1
        self.led_health_changed.emit(
            {
                "status": "normal",
                "sample_count": 64,
                "disconnected_leds": [],
                "flickering_leds": [],
            }
        )

    def stop(self):
        self.stopped = True
        self.device_state_changed.emit("disconnected", "设备已断开")


def test_ensure_device_connected_opens_device_without_config_or_capture(
    qtbot, monkeypatch
):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()
    started = QSignalSpy(controller.session_started)

    controller.ensure_device_connected()
    qtbot.waitUntil(lambda: controller.device_state == "connected")

    assert controller.config is None
    assert controller.engine is None
    assert not controller.is_running
    assert started.count() == 0
    controller.discard()


def test_connected_device_runs_one_automatic_led_health_sample(qtbot, monkeypatch):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()
    health = QSignalSpy(controller.led_health_changed)

    controller.ensure_device_connected()
    qtbot.waitUntil(lambda: health.count() == 1)

    assert health.at(0)[0]["status"] == "normal"
    assert controller._worker.health_refreshes == 1
    controller.discard()


def test_prepare_reuses_device_connected_from_setup(qtbot, monkeypatch):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()

    controller.ensure_device_connected()
    qtbot.waitUntil(lambda: controller.device_state == "connected")
    setup_worker = controller._worker
    setup_thread = controller._thread

    controller.prepare(default_jump_config())

    assert controller._worker is setup_worker
    assert controller._thread is setup_thread
    assert not setup_worker.stopped
    assert controller.device_state == "connected"
    assert controller.engine is not None

    controller.start()
    qtbot.waitUntil(lambda: controller.is_running)
    assert controller.device_state == "streaming"
    controller.stop()


def test_prepare_connects_but_does_not_start_session(qtbot, monkeypatch):
    monkeypatch.setattr(session_controller, "UsbWorker", _FakeUsbWorker)
    controller = session_controller.SessionController()
    started = QSignalSpy(controller.session_started)

    controller.prepare(default_jump_config())
    qtbot.waitUntil(lambda: controller.device_state == "connected")

    assert not controller.is_running
    assert started.count() == 0

    controller.start()
    qtbot.waitUntil(lambda: controller.is_running)

    assert controller.device_state == "streaming"
    assert started.count() == 1
    health_refreshes = controller._worker.health_refreshes
    controller.refresh_led_health()
    qtbot.wait(10)
    assert controller._worker.health_refreshes == health_refreshes
    controller.stop()


def test_treadmill_routes_device_samples_once_and_ignores_legacy_duplicate(qtbot, monkeypatch):
    from config.treadmill_config import TreadmillGaitConfig
    from hardware.sensor_frame import SensorFrame, DeviceLayout, AcquisitionIssue

    class SensorWorker(_FakeUsbWorker):
        sensor_frame_received = Signal(object)
        acquisition_issue = Signal(object)

    monkeypatch.setattr(session_controller, "UsbWorker", SensorWorker)
    controller = session_controller.SessionController()
    controller.prepare(TreadmillGaitConfig(stop_type="Software command", test_length=None,
                                          starting_foot_override="left"))
    try:
        qtbot.waitUntil(lambda: controller.device_state == "connected")
        controller.start()
        qtbot.waitUntil(lambda: controller.is_running)
        engine, worker = controller.engine, controller._worker
        frame = SensorFrame("test", DeviceLayout.linear(), 0, 0, 123,
                            bytes(96), bytes([1] * 96), bytes(12))
        worker.sensor_frame_received.emit(frame)
        worker.raw_contact_signal.emit([0] * 96, 1000.)
        qtbot.waitUntil(lambda: len(engine.export_timestamps) == 1)
        assert list(engine.export_timestamps) == [0.0]
        assert engine._processor._contact_tracker._side_known
        worker.acquisition_issue.emit(AcquisitionIssue("missing_packet", 1))
        qtbot.waitUntil(lambda: any(issue["reason"] == "missing_packet"
                                    for issue in engine._processor._evidence_issues))
        assert engine._processor._evidence_issues[-1]["reason"] == "missing_packet"
    finally:
        controller.stop()
