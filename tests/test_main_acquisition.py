"""The main program consumes complete frames without legacy display work."""
import pytest

from hardware.protocol import E_DATA_REPORT
from hardware.usb_worker import UsbWorker, summarize_led_health
from tests.test_sensor_interface import packet
from tests.test_session_controller_lifecycle import _FakeUsbWorker
from config.test_config import default_jump_config
from ui.session_controller import SessionController


@pytest.mark.parametrize("segments", [1, 3, 8, 12])
def test_complete_frames_keep_short_pulses_and_gaps_without_legacy_signals(qapp, segments):
    worker = UsbWorker(legacy_frame_signals=False)
    frames, issues, legacy = [], [], []
    worker.sensor_frame_received.connect(frames.append)
    worker.acquisition_issue.connect(issues.append)
    worker.raw_contact_signal.connect(lambda *args: legacy.append(args))
    worker.led_bits_signal.connect(legacy.append)
    worker.led_contact_signal.connect(legacy.append)
    worker.data_received.connect(legacy.append)
    payloads = [b"\xff" * (segments * 12), bytes(segments * 12),
                b"\xff" * (segments * 12), b"\xfe" + b"\xff" * (segments * 12 - 1)]
    for index, payload in zip((0, 1, 2, 5), payloads):
        worker._on_frame(E_DATA_REPORT, None, packet(index, payload), None)
    worker._maybe_flush(force=True)
    assert [f.wire_payload for f in frames] == payloads
    assert [f.sample_time_ns for f in frames] == [0, 1_000_000, 2_000_000, 5_000_000]
    assert frames[-1].dropped_frames_before == 2
    assert frames[-1].quality_flags == ("frame_gap",)
    worker._on_protocol_issue("crc_error")
    assert len(frames) == 4
    assert issues
    assert legacy == []
    assert worker._pending_bits is None and worker._pending_hex is None
    # State/error notices still reach the controller's logging path.
    worker._emit_state("error", "device failure")
    assert legacy == ["device failure"]


def test_setup_health_filters_short_flicker_without_changing_raw_frames(qapp):
    worker = UsbWorker(legacy_frame_signals=False)
    worker._health_check_active = True
    payloads = [b"\xff" * 12, b"\xfe" + b"\xff" * 11] * 37
    for index, payload in enumerate(payloads):
        worker._on_frame(E_DATA_REPORT, None, packet(index, payload), None)
    assert len(worker._health_frames) == 64
    result = summarize_led_health(worker._health_frames)
    assert result["flickering_leds"] == []
    assert result["disconnected_leds"] == []


def test_setup_health_keeps_sustained_obstruction_and_restarts_after_gap(qapp):
    from tests.test_led_monitor import frame
    worker = UsbWorker(legacy_frame_signals=False)
    worker._health_check_active = True
    for index in range(74):
        worker._record_led_health_frame(frame(index, b'\xfe' + b'\xff' * 95))
    result = summarize_led_health(worker._health_frames, 768)
    assert result['disconnected_leds'] == [1]
    worker._record_led_health_frame(frame(100, b'\xff' * 96))
    assert worker._health_frames == []
    for index in range(101, 174):
        worker._record_led_health_frame(frame(index, b'\xff' * 96))
    assert summarize_led_health(worker._health_frames, 768)['status'] == 'normal'


def test_default_worker_still_serves_single_meter_viewer(qapp):
    worker = UsbWorker()
    leds, contacts = [], []
    worker.led_bits_signal.connect(leds.append)
    worker.raw_contact_signal.connect(lambda bits, _time: contacts.append(bits))
    worker._on_frame(E_DATA_REPORT, None, packet(0, b"\xfe" + b"\xff" * 11), None)
    worker._maybe_flush(force=True)
    assert leds == [[0] + [1] * 95]
    assert contacts == [[1] + [0] * 95]


@pytest.mark.parametrize("connect_first", [False, True])
def test_controller_selects_lightweight_source_for_both_entry_paths(qtbot, connect_first):
    options = []
    def factory(**kwargs):
        options.append(kwargs)
        return _FakeUsbWorker(**kwargs)
    controller = SessionController(worker_factory=factory)
    try:
        if connect_first:
            controller.ensure_device_connected()
            qtbot.waitUntil(lambda: controller.device_state == "connected")
        controller.prepare(default_jump_config())
        qtbot.waitUntil(lambda: controller.device_state == "connected")
        assert len(options) == 1
        assert options[0]["legacy_frame_signals"] is False
    finally:
        controller.discard()


def test_ground_inbox_preserves_order_boundaries_and_drains_stop_tail(qapp, monkeypatch):
    from itertools import count
    from qtpy.QtCore import QObject
    from ui.session_controller import _GroundFrameInbox
    class Quality(QObject):
        def __init__(self):
            super().__init__()
            self.items = []
        def on_frame(self, value):
            self.items.append(('frame', value))
        def on_issue(self, value):
            self.items.append(('issue', value))
        def arm_checked(self, value):
            self.items.append(('arm', value))
    q = Quality()
    inbox = _GroundFrameInbox(q)
    clock = count()
    monkeypatch.setattr('ui.session_controller.time.perf_counter', lambda: next(clock) / 100)
    expected = []
    for i in range(53):
        value = object()
        if i in (7, 20, 44):
            inbox.on_issue(value)
            expected.append(('issue', value))
        else:
            inbox.on_frame(value)
            expected.append(('frame', value))
    inbox.drain()
    assert q.items == expected[:20] and len(inbox._pending) == 33
    assert inbox._timer.interval() == 0
    inbox.drain()
    assert q.items == expected[:40]
    inbox.arm_checked('begin')
    expected.append(('arm', 'begin'))
    assert q.items == expected and not inbox._pending
    tail = object()
    inbox.on_frame(tail)
    expected.append(('frame', tail))
    inbox.finish()
    assert q.items == expected and not inbox._pending
    inbox.on_frame(object())
    inbox.on_issue(object())
    inbox.drain()
    assert q.items == expected


def test_ground_inbox_consumes_on_owner_thread_and_retains_sample_clock(qtbot):
    import threading
    from qtpy.QtCore import QObject, QThread, QMetaObject, Qt, Slot
    from hardware.sensor_frame import SensorFrame, DeviceLayout
    from ui.session_controller import _GroundFrameInbox
    class Quality(QObject):
        def __init__(self):
            super().__init__()
            self.frames = []
        def on_frame(self, frame):
            self.frames.append((frame, QThread.currentThread() == self.thread()))
        def on_issue(self, issue):
            pytest.fail('No acquisition issue expected')
    q = Quality()
    inbox = _GroundFrameInbox(q)
    thread = QThread()
    q.moveToThread(thread)
    thread.finished.connect(q.deleteLater)
    thread.start()
    layout = DeviceLayout.linear(8)
    frames = [SensorFrame('batch', layout, n, n, 1234 + n, bytes(768), b'\x01' * 768, b'\xff' * 96)
              for n in range(61)]
    try:
        reader = threading.Thread(target=lambda: [inbox.on_frame(f) for f in frames])
        reader.start()
        reader.join()
        QMetaObject.invokeMethod(inbox, 'monitor', Qt.BlockingQueuedConnection)
        qtbot.waitUntil(lambda: len(q.frames) == len(frames))
        assert [f for f, _ in q.frames] == frames
        assert all(owner for _, owner in q.frames)
        assert [f.sample_time_ns for f, _ in q.frames] == [n * 1_000_000 for n in range(61)]
        QMetaObject.invokeMethod(inbox, 'finish', Qt.BlockingQueuedConnection)
    finally:
        thread.quit()
        thread.wait(2000)


def test_ground_controller_manual_stop_keeps_every_received_pending_frame(qtbot):
    import time
    from qtpy.QtCore import Signal, Slot
    from hardware.sensor_frame import SensorFrame, DeviceLayout
    from hardware.beam_quality import BeamQualityPolicy
    from config.walking_config import WalkingConfig
    class Worker(_FakeUsbWorker):
        sensor_frame_received = Signal(object)
        acquisition_issue = Signal(object)
        @Slot()
        def prepare_walking_capture(self):
            self.start_capture()
    controller = SessionController(worker_factory=Worker)
    controller.quality_policy = BeamQualityPolicy(observation_seconds=1)
    controller.prepare(WalkingConfig(stop_type='Software command'))
    layout = DeviceLayout.linear(2)
    reports = []
    controller.session_finished.connect(reports.append)
    def make(n, bits):
        return SensorFrame('inbox', layout, n, n, time.perf_counter_ns(), bits, b'\x01' * 192, b'\xff' * 24)
    try:
        qtbot.waitUntil(lambda: controller.device_state == 'streaming')
        for start in range(0, 1000, 40):
            for n in range(start, start + 40):
                controller._worker.sensor_frame_received.emit(make(n, bytes(192)))
            qtbot.wait(10)
        qtbot.waitUntil(lambda: controller._walking_ready)
        controller.start()
        qtbot.waitUntil(lambda: controller.is_running)
        bits = bytes(int(.2 <= x <= .38) for x in layout.positions_m)
        frames = [make(n, bits) for n in range(1000, 1100)]
        for frame in frames:
            controller._worker.sensor_frame_received.emit(frame)
        controller.stop('manual')
        assert len(reports) == 1 and reports[0].finish_reason == 'manual'
        assert list(reports[0].export_frames) == [f.contact_bits for f in frames]
        assert len(reports[0].export_timestamps) == 100
        assert controller._frame_inbox is None
    finally:
        if controller.is_running:
            controller.stop('manual')
        elif controller._thread is not None:
            controller.discard()


def test_ground_inbox_catches_up_after_delayed_timer_wakeups(qapp):
    from qtpy.QtCore import QObject
    from ui.session_controller import _GroundFrameInbox
    class Quality(QObject):
        def __init__(self):
            super().__init__()
            self.frames = []
        def on_frame(self, frame):
            self.frames.append(frame)
    q = Quality()
    inbox = _GroundFrameInbox(q)
    # A delayed Windows timer can receive 32 samples before its next callback.
    for tick in range(100):
        for sample in range(tick * 32, (tick + 1) * 32):
            inbox.on_frame(sample)
        inbox.drain()
    assert q.frames == list(range(3200))
    assert not inbox._pending


def test_ground_watchdog_uses_arrival_time_while_startup_frames_wait_in_inbox(qapp, monkeypatch):
    from config.walking_config import WalkingConfig
    from engine.device_quality_session import DeviceQualitySession
    from hardware.beam_quality import BeamQualityPolicy
    from tests.test_beam_quality import sample
    from ui.session_controller import _GroundFrameInbox

    now = [10_000_000_000]
    monkeypatch.setattr('engine.device_quality_session.time.perf_counter_ns', lambda: now[0])
    gate = DeviceQualitySession(WalkingConfig(), BeamQualityPolicy(observation_seconds=1))
    inbox = _GroundFrameInbox(gate)
    for i in range(1000):
        gate.on_frame(sample(i, n=8))
    gate.arm_checked((gate.preflight.context.key, False))
    assert gate.context is not None
    finished, delivered = [], []
    gate.finished.connect(finished.append)
    gate.frame_ready.connect(lambda raw, clean, uncertain: delivered.append(raw))

    # The measurement thread resumes with a watchdog event before its drain event.
    now[0] += 1_200_000_000
    incoming = sample(1000, n=8)
    inbox.on_frame(incoming)
    gate.poll()
    assert not finished  # USB has delivered a fresh frame; this is not data loss.
    assert not delivered
    inbox.drain()
    assert delivered == [incoming]
    assert delivered[0].received_monotonic_ns == incoming.received_monotonic_ns

    # A real one-second interruption must still terminate the session.
    now[0] += 1_000_000_001
    gate.poll()
    assert finished == ['data_timeout']
    inbox.finish()
