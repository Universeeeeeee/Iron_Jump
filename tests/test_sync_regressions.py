"""Regression contracts reproduced during the offline sync review."""
import json

import pytest

from tests.test_walking_vision_pipeline import landing_pose
from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import FootLabel, VisionConfig
from vision.live_walking import classify_walking_contact


def evidence(record_property, **values):
    record_property('evidence', json.dumps(values, ensure_ascii=False))


def scheduler(max_frames=40):
    return EventWindowScheduler(VisionConfig(
        pre_event_ms=150, post_event_ms=150, inference_interval_ms=50,
        decision_timeout_ms=450, frame_buffer_ms=1000, max_frames=max_frames))


def prime(s):
    for ms in range(500, 1151, 50):
        s.add_frame(None, ms / 1000)
        assert not s.process_ready(lambda _, t: landing_pose(t),
                                   classify_walking_contact, now_s=ms / 1000)
    cached = [p for t, p in s._pose_cache.items() if 850 <= t <= 1150]
    assert classify_walking_contact(1, 1., cached, s.config).label is FootLabel.LEFT


def test_complete_pose_cache_survives_raw_image_eviction(record_property):
    s = scheduler(20)
    prime(s)
    for ms in range(1160, 1301, 10):
        s.add_frame(None, ms / 1000)
    s.add_event(1, 1., submitted_at_s=1.3)
    result = s.process_ready(lambda _, t: landing_pose(t), classify_walking_contact, now_s=1.3)[0]
    evidence(record_property, oldest_image_s=s._frames[0].captured_at_s,
             cached_window_poses=result.diagnostics.pose_total, label=result.label.value,
             reason=result.reason, submitted_age_ms=300, deadline_age_ms=450)
    assert result.label is FootLabel.LEFT, result


def test_high_rate_frames_do_not_expire_an_ontime_event(record_property):
    s = scheduler(20)
    decisions = []
    for ms in range(500, 1151, 10):
        s.add_frame(None, ms / 1000)
        if ms == 1000:
            s.add_event(1, 1., submitted_at_s=1.)
        decisions.extend(s.process_ready(lambda _, t: landing_pose(t),
                                         classify_walking_contact, now_s=ms / 1000))
    evidence(record_property, label=decisions[0].label.value, reason=decisions[0].reason,
             decided_at_s=decisions[0].decided_at_s)
    assert decisions[0].label is FootLabel.LEFT, decisions[0]


def test_ready_event_is_decided_before_unrelated_inference(record_property):
    s = scheduler()
    prime(s)
    s.add_event(1, 1., submitted_at_s=1.43)
    s.add_frame(None, 1.43)
    now = [1.43]
    def infer(_, ms):
        now[0] += .03
        return landing_pose(ms)
    result = s.process_ready(infer, classify_walking_contact, now_s=now[0],
                             decision_clock=lambda: now[0])[0]
    evidence(record_property, label=result.label.value, reason=result.reason,
             decided_at_s=result.decided_at_s, actual_finish_s=now[0])
    assert result.label is FootLabel.LEFT, result
    assert result.decided_at_s <= 1.45


def test_classifier_completion_must_meet_deadline(record_property):
    s = scheduler()
    prime(s)
    s.add_event(1, 1., submitted_at_s=1.44)
    now = [1.44]
    def classify(*args):
        result = classify_walking_contact(*args)
        now[0] += .02
        return result
    result = s.process_ready(lambda _, t: landing_pose(t), classify,
                             now_s=now[0], decision_clock=lambda: now[0])[0]
    evidence(record_property, label=result.label.value, reason=result.reason,
             recorded_decision_s=result.decided_at_s, actual_finish_s=now[0])
    assert result.label is FootLabel.UNKNOWN, result
    assert result.reason == 'decision_timeout'
    assert result.decided_at_s >= 1.46


@pytest.mark.parametrize('fault', ['late', 'missing'])
def test_unusable_evidence_remains_unknown(fault):
    s = scheduler()
    for ms in range(500, 1151, 50):
        s.add_frame(None, ms / 1000)
    now = 1.6 if fault == 'late' else 1.3
    s.add_event(1, 1., submitted_at_s=now)
    result = s.process_ready(lambda _, t: None if fault == 'missing' else landing_pose(t),
                             classify_walking_contact, now_s=now)[0]
    assert result.label is FootLabel.UNKNOWN
    assert result.reason == ('decision_timeout' if fault == 'late' else 'pose_window_unavailable')


@pytest.fixture
def ground(qapp, monkeypatch, request):
    from config.walking_config import WalkingConfig
    from config.overground_running_config import OvergroundRunningConfig
    from engine.device_quality_session import DeviceQualitySession
    from engine.gait_engine import GaitEngine
    from hardware.beam_quality import BeamQualityPolicy
    from hardware.sensor_frame import DeviceLayout, SensorFrame
    from ui.session_controller import _GroundFrameInbox
    config_type = OvergroundRunningConfig if getattr(request, 'param', 'walk') == 'run' else WalkingConfig
    config = config_type(stop_type='Software command', starting_foot='Left')
    engine = GaitEngine(config=config)
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1), engine)
    engine.quality = gate
    inbox = _GroundFrameInbox(gate)
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    layout = DeviceLayout.linear(8)
    clock = [10_000_000_000]
    monkeypatch.setattr('time.perf_counter_ns', lambda: clock[0])
    def frame(index, occupied=()):
        clock[0] = 10_000_000_000 + index * 1_000_000
        bits = bytes(int(i == 576 or i in occupied) for i in range(768))
        return SensorFrame('offline', layout, index, index, clock[0], bits, b'\x01' * 768, b'')
    for i in range(1000):
        gate.on_frame(frame(i))
    assert gate.preflight.context.bad_indices == (576,)
    gate.arm_checked((gate.preflight.context.key, True))
    assert gate.context is not None
    try:
        yield engine, gate, inbox, frame, clock
    finally:
        inbox._timer.stop()
        gate.halt()
        engine.overground.halt()
        engine.deleteLater()


@pytest.mark.parametrize('second_start', [571, 620], ids=['crosses_bad_beam', 'far_from_bad_beam'])
@pytest.mark.parametrize('ground', ['walk', 'run'], indirect=True)
def test_masked_beam_cannot_contribute_valid_step(ground, second_start, record_property):
    engine, gate, inbox, frame, clock = ground
    for i in range(1000, 2300):
        occupied = set(range(520, 539)) if 1100 <= i < 1700 else set()
        if 1600 <= i < 2200:
            occupied.update(range(second_start, second_start + 19))
        gate.on_frame(frame(i, occupied))
    report = engine.build_report('manual')
    assert all(bits[576] for bits in report.export_frames)
    summary = engine.overground.processor.summary()
    rows = [{k: c.get(k) for k in ('id', 'confirmed', 'exclusion', 'side')} for c in summary['contacts']]
    evidence(record_property, valid_steps=summary['valid_steps'], contacts=rows,
             fixed_bad_beam=576, second_foot_start=second_start)
    assert summary['valid_steps'] == (0 if second_start == 571 else 1), rows
    assert not any(issue['code'] == 'frame_gap' for issue in summary['issues'])
    if second_start == 571:
        assert any(issue['code'] == 'masked_contact_boundary' for issue in summary['issues'])


@pytest.mark.parametrize('pending', [0, 100, 1200])
@pytest.mark.parametrize('reason', ['data_timeout', 'disconnected'])
def test_source_timeout_preserves_every_received_tail_frame(ground, pending, reason, record_property):
    engine, gate, inbox, frame, clock = ground
    gate.on_frame(frame(1000))
    for i in range(1001, 1001 + pending):
        inbox.on_frame(frame(i))
    clock[0] += 1_100_000_000
    if reason == 'data_timeout':
        gate.poll()
    else:
        gate.on_device_state('disconnected', 'offline injection')
    assert gate.done
    assert not inbox._accepting
    inbox.on_frame(frame(1001 + pending))  # Beyond the frozen boundary: not accepted.
    inbox.finish()
    report = engine.build_report(reason)
    evidence(record_property, received_formal_frames=1 + pending,
             archived_frames=len(report.export_frames), pending_after_finish=len(inbox._pending))
    assert len(report.export_frames) == 1 + pending
    assert report.report_config_snapshot['raw_buffer']['raw_only_tail_frames'] == pending
    assert list(report.export_timestamps) == pytest.approx([i / 1000 for i in range(1 + pending)])
    assert not inbox._pending
    inbox.finish()
    assert len(engine.build_report(reason).export_frames) == 1 + pending


def test_fresh_arrivals_prevent_false_timeout_while_processing_lags(ground):
    engine, gate, inbox, frame, clock = ground
    gate.on_frame(frame(1000))
    for i in range(1001, 2201):
        inbox.on_frame(frame(i))
    gate.poll()
    assert not gate.done
    inbox.finish()
    assert len(engine.build_report('manual').export_frames) == 1201


def test_halt_publishes_contact_confirmed_in_filter_tail(ground, record_property):
    engine, gate, inbox, frame, clock = ground
    snapshots = []
    engine.overground.snapshot.connect(snapshots.append)
    for i in range(1000, 1166):
        gate.on_frame(frame(i, range(520, 539) if i >= 1100 else ()))
    assert not any(c.confirmed for c in engine.overground.processor.contacts)
    before = len(snapshots)
    engine.overground.halt()
    assert any(c.confirmed for c in engine.overground.processor.contacts)
    evidence(record_property, snapshots_before_halt=before, snapshots_after_halt=len(snapshots),
             processor_confirmed=True, last_published_touch_count=snapshots[-1]['touch_count'])
    assert snapshots[-1]['touch_count'] == 1
    engine.overground.halt()
    assert len(snapshots) == before + 1


def test_ready_decision_returns_before_unrelated_inference_can_block():
    s = scheduler()
    prime(s)
    s.add_event(1, 1., submitted_at_s=1.43)
    s.add_frame(None, 1.43)
    inferred = []
    result = s.process_ready(lambda _, ms: inferred.append(ms), classify_walking_contact, now_s=1.43)
    assert result[0].label is FootLabel.LEFT
    assert not inferred
    assert not s.process_ready(lambda _, ms: inferred.append(ms), classify_walking_contact, now_s=1.44)
    assert inferred == [1430]


def test_raw_frames_without_pose_history_cannot_synthesize_missing_evidence():
    s = scheduler(20)
    # A whole camera batch arrives late; the evicted input frames were never inferred.
    for ms in range(500, 1301, 10):
        s.add_frame(None, ms / 1000)
    s.add_event(1, 1., submitted_at_s=1.3)
    result = s.process_ready(lambda _, ms: landing_pose(ms), classify_walking_contact, now_s=1.3)[0]
    assert result.label is FootLabel.UNKNOWN


def test_arrival_during_watchdog_freeze_cancels_timeout(ground):
    engine, gate, inbox, frame, clock = ground
    gate.on_frame(frame(1000))
    clock[0] += 1_100_000_000
    finished = []
    gate.finished.connect(finished.append)
    original_freeze = gate.freeze_input
    from dataclasses import replace
    fresh = replace(frame(1001), received_monotonic_ns=12_100_000_000)
    clock[0] = 12_100_000_000
    def arrive_then_freeze(cutoff):
        inbox.on_frame(fresh)
        return original_freeze(cutoff)
    gate.freeze_input = arrive_then_freeze
    gate.poll()
    assert not gate.done and not finished and inbox._accepting
    assert not any(event['code'] == 'data_timeout' for event in gate.snapshot()['events'])
    inbox.finish()
    assert len(engine.build_report('manual').export_frames) == 2


def test_archived_tail_does_not_generate_contacts_after_timeout(ground):
    engine, gate, inbox, frame, clock = ground
    gate.on_frame(frame(1000))
    for i in range(1001, 1401):
        inbox.on_frame(frame(i, range(520, 539)))
    clock[0] += 1_100_000_000
    gate.poll()
    inbox.finish()
    report = engine.build_report('data_timeout')
    assert len(report.export_frames) == 401
    assert not engine.overground.processor.contacts
    assert any(report.export_frames[-1][520:539])


def test_short_mask_neighbor_flicker_does_not_break_distant_walk(ground):
    engine, gate, inbox, frame, clock = ground
    for i in range(1000, 2300):
        occupied = set(range(200, 219)) if 1100 <= i < 1700 else set()
        if 1600 <= i < 2200:
            occupied.update(range(260, 279))
        if i % 5 == 0:
            occupied.add(577)  # One raw sample, not a confirmed optical change.
        gate.on_frame(frame(i, occupied))
    engine.build_report('manual')
    assert engine.overground.processor.summary()['valid_steps'] == 1


def test_controller_timeout_archives_pending_frames_before_publishing_report(qtbot):
    import time
    from qtpy.QtCore import Signal, Slot, QMetaObject, Qt
    from config.walking_config import WalkingConfig
    from hardware.sensor_frame import SensorFrame, DeviceLayout
    from hardware.beam_quality import BeamQualityPolicy
    from tests.test_session_controller_lifecycle import _FakeUsbWorker
    from ui.session_controller import SessionController
    layout = DeviceLayout.linear(8)
    def frame(n):
        return SensorFrame('controller-tail', layout, n, n, time.perf_counter_ns(),
                           bytes(768), b'\x01' * 768, b'')
    class Worker(_FakeUsbWorker):
        sensor_frame_received = Signal(object)
        acquisition_issue = Signal(object)
        @Slot()
        def prepare_walking_capture(self):
            self.start_capture()
        @Slot()
        def inject_timeout(self):
            controller._quality.on_frame(frame(1000))
            for n in range(1001, 1101):
                self.sensor_frame_received.emit(frame(n))
            # Source goes quiet while this worker cannot dispatch its drain timer.
            time.sleep(1.1)
            controller._quality.poll()
    controller = SessionController(worker_factory=Worker)
    controller.quality_policy = BeamQualityPolicy(observation_seconds=1)
    controller.prepare(WalkingConfig(stop_type='Software command'))
    reports = []
    controller.session_finished.connect(reports.append)
    try:
        qtbot.waitUntil(lambda: controller.device_state == 'streaming')
        for start in range(0, 1000, 40):
            for n in range(start, start + 40):
                controller._worker.sensor_frame_received.emit(frame(n))
            qtbot.wait(10)
        qtbot.waitUntil(lambda: controller._walking_ready)
        controller.start()
        qtbot.waitUntil(lambda: controller.is_running)
        QMetaObject.invokeMethod(controller._worker, 'inject_timeout', Qt.QueuedConnection)
        qtbot.waitUntil(lambda: bool(reports), timeout=4000)
        assert len(reports) == 1
        report = reports[0]
        assert report.finish_reason == 'data_timeout'
        assert len(report.export_frames) == 101
        assert report.report_config_snapshot['raw_buffer']['raw_only_tail_frames'] == 100
        assert controller._frame_inbox is None
    finally:
        if controller.is_running:
            controller.stop('manual')
        elif controller._thread is not None:
            controller.discard()
