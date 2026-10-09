from dataclasses import replace
import time
import pytest
from hardware.beam_quality import BeamQualityPolicy, longest_run
from hardware.sensor_frame import DeviceLayout, SensorSegment, SensorFrame
from hardware.walking_preflight import WalkingPreflight
from engine.device_quality_session import DeviceQualitySession
from engine.gait_engine import GaitEngine
from config.test_config import config_from_dict
from agent.config.modes import MODE_TEST_TYPES


def test_preflight_uses_monitor_confirmation_and_preserves_raw_evidence(qapp):
    from hardware.beam_filter import BeamDisplayFilter
    def frame(index, payload):
        layout = DeviceLayout.linear(len(payload) // 12)
        return SensorFrame('test', layout, index, index, time.perf_counter_ns(),
                           layout.contact_bits(payload), b'\x01' * layout.bit_count, payload)
    gate = WalkingPreflight()
    display = BeamDisplayFilter(10)
    for index in range(3200):
        pulse = index % 100 == 50
        payload = b'\xff' * 12 + (bytes(12) if pulse else b'\xff' * 12)
        raw = frame(index, payload)
        gate.feed(raw)
        reference = raw.layout.contact_bits(display.feed(raw))
        state = gate.status(raw.received_monotonic_ns)
        visual = state['visual_frame']
        assert visual['contact_bits'] == list(reference)
        if pulse:
            assert visual['raw_contact_bits'] == list(raw.contact_bits)
        assert raw.wire_payload == payload
    assert state['ready']
    assert state['stability']['broad_change_events'] > 0
    assert not state['bad_indices']
    assert state['healthy_samples'] == 3000
    # A sustained change becomes visible after confirmation, still on the device clock.
    for index in range(3200, 3212):
        raw = frame(index, b'\xfe' + b'\xff' * 23)
        gate.feed(raw)
        expected = list(raw.layout.contact_bits(display.feed(raw)))
        assert gate.status(raw.received_monotonic_ns)['visual_frame']['contact_bits'] == expected
    assert expected[0] == 1
    assert not gate.status(raw.received_monotonic_ns)['ready']


def test_complete_dark_frame_uses_optical_confirmation_without_resetting_data_window():
    gate = WalkingPreflight()
    observe(gate, n=2)
    dark = sample(3000, range(192), n=2, quality_flags=('all_beams_blocked',))
    gate.feed(dark)
    state = gate.status(dark.received_monotonic_ns)
    assert state['healthy_samples'] == 3000
    assert gate.data_valid
    assert state['ready']  # An unconfirmed raw change does not override stable empty field.
    assert state['pending_indices'] == tuple(range(192))
    assert not any(state['visual_frame']['contact_bits'])
    assert all(state['visual_frame']['raw_contact_bits'])
    for index in range(3001, 3210):
        dark_now = index in (3100, 3200)
        gate.feed(sample(index, range(192) if dark_now else (), n=2,
                         quality_flags=('all_beams_blocked',) if dark_now else ()))
    state = gate.status(time.perf_counter_ns())
    assert state['healthy_samples'] == 3000
    assert state['stability']['broad_change_events'] == 3
    assert state['ready']
    assert not state['bad_indices']
    gate.feed(sample(3210, n=2, quality_flags=('crc_error',)))
    assert gate.healthy_samples == 0 and not gate.data_valid


def sample(index, blocked=(), n=1, **kwargs):
    layout = DeviceLayout.linear(n)
    bits = bytes(int(i in blocked) for i in range(layout.bit_count))
    return SensorFrame("quality", layout, index, index, time.perf_counter_ns(), bits,
                       bytes([1]) * len(bits), b"", **kwargs)


def observe(gate, blocked=(), n=1, count=3000):
    for i in range(count):
        gate.feed(sample(i, blocked(i) if callable(blocked) else blocked, n))
    return gate.status(time.perf_counter_ns())


@pytest.mark.parametrize("bad,ready", [((), True), ((40,), True), ((40,41), True), ((40,41,42), False)])
def test_actual_default_window_and_limits(bad, ready):
    gate = WalkingPreflight()
    observe(gate, bad, count=2999)
    assert gate.context is None
    gate.feed(sample(2999, bad))
    state = gate.status(time.perf_counter_ns())
    assert state["ready"] is ready
    assert state["requires_acknowledgement"] == (ready and bool(bad))


def test_per_segment_not_whole_array_and_cross_seam():
    assert not observe(WalkingPreflight(), (1, 20, 40), n=8)["ready"]
    assert not observe(WalkingPreflight(), (94, 95, 96), n=8)["ready"]
    assert observe(WalkingPreflight(), (95, 96), n=8)["ready"]
    separated = DeviceLayout((SensorSegment("a", 0, 0), SensorSegment("b", 1, 2)))
    assert longest_run((94, 95, 96), separated) == 2


def test_repeated_flicker_but_not_one_glitch():
    assert observe(WalkingPreflight(), lambda i: (10,) if (i // 200) % 2 else ())["requires_acknowledgement"]
    state = observe(WalkingPreflight(), lambda i: (10,) if i == 100 else ())
    assert state['ready'] and not state['bad_indices']
    assert state['stability']['transient_beam_pulses'] == 1


@pytest.mark.parametrize("mode", list(MODE_TEST_TYPES.values()))
def test_all_modes_gate_ack_raw_mask_and_no_optical_autostop(qtbot, mode):
    config = config_from_dict({"test_type": mode, "stop_type": "Software command"})
    engine = GaitEngine(config=config)
    gate = DeviceQualitySession(config, BeamQualityPolicy(), engine)
    engine.quality = gate
    engine.paused = True
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    for i in range(3000):
        gate.on_frame(sample(i, (40,)))
    key = gate.preflight.context.key
    gate.arm_checked((key, False))
    assert gate.context is None
    gate.arm_checked((key, True))
    assert gate.context.bad_indices == (40,)
    delivered, finished = [], []
    gate.frame_ready.connect(lambda raw, clean, uncertain: delivered.append((raw, clean, uncertain)))
    gate.finished.connect(finished.append)
    gate.on_frame(sample(3000, (40,)))
    assert delivered[-1][0].contact_bits[40] == 1
    assert delivered[-1][1].contact_bits[40] == 0
    gate.on_frame(sample(3001, (39,40,41)))
    if mode in {'Sprint and Gait Test', 'Overground Running Test'}:
        assert not delivered[-1][2]
        assert all(delivered[-1][1].valid_bits[:96])
    else:
        assert delivered[-1][2]
    # Arbitrarily serious optical faults are recorded, not a stop command.
    gate.on_frame(replace(sample(3002), valid_bits=bytes(96)))
    assert not finished
    assert gate.context.bad_indices == (40,)
    report = engine.build_report("manual")
    assert report.report_config_snapshot["beam_quality"]["empty_field_acknowledged"]
    assert len(report.report_config_snapshot["beam_quality"]["events"]) == (
        1 if mode in {"Sprint and Gait Test", "Overground Running Test"} else 2)
    gate.on_device_state("disconnected", "拔出设备")
    assert finished == ["disconnected"]
    gate.halt()
    if engine._stop_timer:
        engine._stop_timer.stop()


def test_ack_cannot_survive_confirmed_changed_faults(qtbot):
    config = config_from_dict({"test_type": "Jump Test"})
    gate = DeviceQualitySession(config, BeamQualityPolicy())
    for i in range(3000):
        gate.on_frame(sample(i, (40,)))
    key = gate.preflight.context.key
    for i in range(3000, 3011):
        gate.on_frame(sample(i, (40,60)))
    gate.arm_checked((key, True))
    assert gate.context is None


@pytest.mark.parametrize("kwargs", [{"max_bad_ratio": float("nan")}, {"max_bad_ratio": .11},
    {"max_consecutive": -1}, {"max_consecutive": 2.5}, {"observation_seconds": 0}])
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        BeamQualityPolicy(**kwargs)


def test_quality_settings_round_trip(tmp_path):
    from qtpy.QtCore import QSettings
    from ui.quality_settings import load_policy, save_policy
    settings = QSettings(str(tmp_path / 'quality.ini'), QSettings.IniFormat)
    policy = BeamQualityPolicy(.02, 1, 4)
    save_policy(policy, settings)
    assert load_policy(settings) == policy


def test_new_runtime_fault_does_not_change_mask_or_finish(qtbot):
    config = config_from_dict({"test_type": "Jump Test", "stop_type": "Software command"})
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1))
    for i in range(1000):
        gate.on_frame(sample(i))
    gate.arm_checked((gate.preflight.context.key, False))
    finished, frames = [], []
    gate.finished.connect(finished.append)
    gate.frame_ready.connect(lambda raw, clean, uncertain: frames.append((clean, uncertain)))
    for i in range(1000, 2100):
        gate.on_frame(sample(i, range(10, 50)))
    assert not finished
    assert not gate.context.bad_indices
    assert frames[-1][0].contact_bits[20] == 1  # Never dynamically mask.
    assert frames[-1][1]  # Yet uncertain contact must not contribute metrics.
    assert gate.snapshot()["events"][-1]["code"] == "runtime_obstruction"
    gate.last_frame = replace(gate.last_frame, received_monotonic_ns=time.perf_counter_ns() - 2_000_000_000)
    gate.poll()
    assert finished == ["data_timeout"]


@pytest.mark.parametrize("mode", list(MODE_TEST_TYPES.values()))
def test_controller_enforces_gate_for_every_mode(qtbot, mode):
    from qtpy.QtCore import Signal, Slot
    from tests.test_session_controller_lifecycle import _FakeUsbWorker
    from ui.session_controller import SessionController
    class Worker(_FakeUsbWorker):
        sensor_frame_received = Signal(object)
        acquisition_issue = Signal(object)
        @Slot()
        def prepare_walking_capture(self):
            pass
    controller = SessionController(worker_factory=Worker)
    controller.quality_policy = BeamQualityPolicy(observation_seconds=1)
    reports = []
    controller.session_finished.connect(reports.append)
    try:
        controller.prepare(config_from_dict({"test_type": mode, "stop_type": "Software command"}))
        qtbot.waitUntil(lambda: controller.device_state == "connected")
        controller.start()
        assert not controller.is_running
        for i in range(1000):
            controller._worker.sensor_frame_received.emit(sample(i, (40,)))
        qtbot.waitUntil(lambda: controller._walking_ready)
        controller.start()
        qtbot.waitUntil(lambda: not controller._start_pending)
        assert not controller.is_running
        controller.start(acknowledge_quality=True, quality_key=controller.quality_status["device_key"])
        qtbot.waitUntil(lambda: controller.is_running)
        assert controller._quality.thread() is controller._thread
        controller._worker.sensor_frame_received.emit(sample(1000, (40,)))
        qtbot.waitUntil(lambda: controller._quality.last_frame.sample_index == 1000)
        controller._worker.device_state_changed.emit("disconnected", "断开")
        qtbot.waitUntil(lambda: len(reports) == 1)
        assert reports[0].finish_reason == "disconnected"
        assert reports[0].report_config_snapshot["beam_quality"]["preflight"]["bad_indices"] == (40,)
    finally:
        if controller.is_running:
            controller.stop()
        else:
            controller.discard()


def test_quality_reaches_history_and_ai_package(qtbot):
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from data.subject_store import _report_detail, _report_from_detail
    engine = GaitEngine(config=config_from_dict({"test_type": "Jump Test"}))
    report = engine.build_report("manual")
    report.report_config_snapshot["beam_quality"] = {"degraded": True, "preflight": {"bad_indices": [40]},
                                                   "events": [], "limitation": "精度需复核"}
    # Existing serialization must retain quality, rather than reconstructing it from the current device.
    import json
    restored = _report_from_detail(json.loads(json.dumps(_report_detail(report))))
    assert restored.report_config_snapshot["beam_quality"] == report.report_config_snapshot["beam_quality"]
    package = ReportDataPackageBuilder().build(report, ReportContextInput(session_id=1, test_type="Jump Test"))
    assert any(flag.code == "beam_quality" and flag.details["degraded"] for flag in package.quality_flags)


def test_footprints_far_from_bad_beams_remain_visible(qtbot, monkeypatch):
    from ui.footprint_channel import FootprintChannelWidget
    view = FootprintChannelWidget()
    qtbot.addWidget(view)
    painted = []
    monkeypatch.setattr(view, '_paint_foot', lambda painter, foot, *args: painted.append(foot['contact_id']))
    view.render_state({'contact_bits': [0] * 96, 'valid_bits': [int(i != 40) for i in range(96)],
                       'feet': [{'contact_id': 'far', 'centroid_cm': 10, 'length_cm': 10, 'status': 'confirmed'},
                                {'contact_id': 'near', 'centroid_cm': 41, 'length_cm': 10, 'status': 'confirmed'}]})
    view.grab()
    assert 'far' in painted and 'near' not in painted


def test_mask_adjacent_motion_produces_no_fabricated_jump(qtbot):
    config = config_from_dict({'test_type': 'Jump Test', 'stop_type': 'Software command'})
    engine = GaitEngine(config=config)
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1), engine)
    engine.quality = gate
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    for i in range(1000):
        gate.on_frame(sample(i, (40,)))
    gate.arm_checked((gate.preflight.context.key, True))
    for i in range(1000, 2500):
        blocked = set(range(30, 50)) if (i // 200) % 2 else set()
        blocked.add(40)
        gate.on_frame(sample(i, blocked))
    report = engine.build_report('manual')
    assert not report.jump_results
    assert len(report.export_frames) == 1500
    assert all(bits[40] == 1 for bits in report.export_frames)
    assert report.report_config_snapshot['beam_quality']['events']
    if engine._stop_timer:
        engine._stop_timer.stop()
    gate.halt()


@pytest.mark.parametrize('mode', ['Sprint and Gait Test', 'Overground Running Test'])
def test_bad_beam_does_not_prevent_normal_empty_field_completion(qtbot, mode):
    config = config_from_dict({'test_type': mode})
    engine = GaitEngine(config=config)
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1), engine)
    engine.quality = gate
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    done = []
    engine.test_finished.connect(done.append)
    for i in range(1000):
        gate.on_frame(sample(i, (2,), n=1))
    gate.arm_checked((gate.preflight.context.key, True))
    CONTACTS = [(100, 250, .30), (400, 550, .65), (700, 850, .94)]
    positions = gate.context.layout.positions_m
    for i in range(1000, 4400):
        ranges = [(centre - .08, centre + .08) for start, end, centre in CONTACTS if start <= i - 1000 < end]
        blocked = {j for j, x in enumerate(positions) if any(low <= x <= high for low, high in ranges)}
        blocked.add(2)
        gate.on_frame(sample(i, blocked, n=1))
        if done:
            break
    assert done == ['passage_complete']
    report = engine.build_report(done[0])
    assert report.export_frames and all(bits[2] == 1 for bits in report.export_frames)
    assert all(item['valid_bits'][2] == 0 for item in report.visual_timeline)
    gate.halt()


def test_settings_change_invalidates_preparation_and_is_locked_in_run(qtbot, tmp_path, monkeypatch):
    from tests.test_main_window_navigation import _window
    window, controller = _window(qtbot, tmp_path)
    saved = []
    monkeypatch.setattr('ui.quality_settings.save_policy', saved.append)
    controller.engine = object()
    policy = BeamQualityPolicy(.02, 1, 4)
    window._on_quality_policy_changed(policy)
    assert saved == [policy] and controller.discards == 1
    assert controller.quality_policy == policy
    controller.is_running = True
    window._settings_view.set_test_running(True)
    assert not window._settings_view._quality_card.isEnabled()
    window._on_quality_policy_changed(BeamQualityPolicy())
    assert saved == [policy] and controller.discards == 1
    controller.is_running = False
    controller.engine = None


def test_runtime_issue_duration_is_recorded(qtbot):
    config = config_from_dict({'test_type': 'Jump Test'})
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1))
    for i in range(1000):
        gate.on_frame(sample(i))
    gate.arm_checked((gate.preflight.context.key, False))
    for i in range(1000, 2200):
        gate.on_frame(sample(i, (40,)))
    event = gate.snapshot()['events'][-1]
    assert event['code'] == 'runtime_obstruction'
    assert event['end_s'] > event['start_s']
    assert gate.snapshot()['event_count'] == 1
    gate.halt()


def test_transient_observations_are_not_reported_as_confirmed_faults():
    gate = WalkingPreflight()
    state = observe(gate, lambda i: (576, 577, 578) if i == 100 else (), n=8)
    assert state['ready']
    assert state['bad_indices'] == ()
    assert state['stability']['transient_indices'] == (576, 577, 578)
    assert state['message'] == '自检通过，可以开始'
    assert '超限' not in state['message']
    for i in range(3000, 3101):
        gate.feed(sample(i, n=8))
    assert gate.ready(time.perf_counter_ns())


def test_preflight_explains_whole_track_faults_when_selected_segment_is_clear():
    gate = WalkingPreflight()
    state = observe(gate, (576, 577, 578), n=8)
    assert not state['ready']
    assert '第7段' in state['details']
    assert '1–3' in state['details']
    assert '3.12%' in state['details']
    assert '2.50%' in state['details']
    assert '连续3束' in state['details']
    assert not any(state['visual_frame']['contact_bits'][:96])
    assert state['visual_frame']['preflight_bad_indices'] == (576, 577, 578)


def test_observation_retains_frame_gap_reason_until_window_recovers():
    gate = WalkingPreflight()
    observe(gate, count=400)
    gate.feed(sample(402, dropped_frames_before=2, quality_flags=('frame_gap',)))
    gate.feed(sample(403))
    state = gate.status(time.perf_counter_ns())
    assert not state['ready']
    assert '缺失2帧' in state['details']
    for i in range(404, 3403):
        gate.feed(sample(i))
    state = gate.status(time.perf_counter_ns())
    assert state['ready']
    assert '缺失2帧' not in state['details']


def test_preflight_display_work_is_throttled_but_readiness_changes_are_immediate(qtbot, monkeypatch):
    from unittest.mock import Mock
    import engine.device_quality_session as module
    clock = 10_000_000_000
    monkeypatch.setattr(module.time, 'perf_counter_ns', lambda: clock)
    gate = DeviceQualitySession(config_from_dict({'test_type': 'Jump Test'}), BeamQualityPolicy())
    status = Mock(wraps=gate.preflight.status)
    monkeypatch.setattr(gate.preflight, 'status', status)
    events = []
    gate.readiness.connect(events.append)
    for i in range(3000):
        gate.on_frame(sample(i))
    assert events[-1]['ready']
    assert status.call_count == 2  # Initial observation and the ready transition.
    for i in range(3000, 3010):
        gate.on_frame(sample(i, (10,)))
        assert events[-1]['ready']
    assert status.call_count == 2
    gate.on_frame(sample(3010, (10,)))
    assert not events[-1]['ready']  # Disable immediately when confirmation completes.
    assert status.call_count == 3
    clock += 100_000_000
    gate.on_frame(sample(3011, (10,)))
    assert status.call_count == 4
    gate.halt()


def test_beams_confirm_independently_on_device_clock():
    gate = WalkingPreflight()
    received = time.perf_counter_ns()
    # All frames arrive in one USB burst; a flickering beam cannot reset its neighbour.
    for i in range(11):
        gate.feed(replace(sample(i, (40, 41) if i % 2 else (40,)), received_monotonic_ns=received))
    assert gate._previous_bits == {40}
    assert gate.pending_indices == ()
    assert gate._counts[41] == 0


def test_short_pulse_does_not_confirm_after_a_long_host_pause():
    gate = WalkingPreflight()
    received = time.perf_counter_ns()
    for i in range(3):
        gate.feed(replace(sample(i, (40,)), received_monotonic_ns=received + i * 100_000_000))
    assert not gate._previous_bits
    assert gate.pending_indices == (40,)


def test_frequent_filtered_broad_transients_do_not_block_empty_field():
    gate = WalkingPreflight()
    state = observe(gate, lambda i: tuple(range(576, 672)) if i % 100 < 3 else (), n=8)
    assert state['ready']
    assert not state['bad_indices']
    assert '自检通过' in state['message']
    assert state['stability']['broad_change_events'] == 30
    assert state['stability']['transient_beam_pulses'] == 30 * 96
    assert state['message'] == '自检通过，可以开始'
    assert state['details'] == ''  # Raw diagnostics remain in stability, not the UI.
    for i in range(3000, 6100):
        gate.feed(sample(i, n=8))
    state = gate.status(time.perf_counter_ns())
    assert state['ready'] and not state['stability']['broad_change_events']


def test_single_beam_short_flicker_does_not_hide_other_beam_fault():
    state = observe(WalkingPreflight(), lambda i: (40, 41) if i % 2 else (40,), count=3001)
    assert state['ready'] and state['requires_acknowledgement']
    assert state['bad_indices'] == (40,)
    assert state['stability']['transient_indices'] == (41,)


def test_gap_cannot_complete_pending_confirmation():
    gate = WalkingPreflight()
    for i in range(10):
        gate.feed(sample(i, (40,)))
    gate.feed(sample(100, (40,), dropped_frames_before=90, quality_flags=('frame_gap',)))
    gate.feed(sample(101, (40,)))
    assert not gate._previous_bits and gate.pending_indices == (40,)


def test_stability_audit_is_frozen_and_short_runtime_pulses_are_preserved(qtbot):
    gate = DeviceQualitySession(config_from_dict({'test_type': 'Jump Test'}), BeamQualityPolicy())
    for i in range(3000):
        gate.on_frame(sample(i, (40,) if i == 100 else ()))
    gate.arm_checked((gate.preflight.context.key, False))
    snapshot = gate.snapshot()
    assert snapshot['preflight']['stability']['transient_beam_pulses'] == 1
    frames = []
    gate.frame_ready.connect(lambda raw, clean, uncertain: frames.append((raw, clean)))
    pulse = sample(3000, (10,))
    gate.on_frame(pulse)
    gate.on_frame(sample(3001))
    assert frames[0][0] is pulse
    assert frames[0][1].contact_bits[10] == 1
    assert frames[1][1].contact_bits[10] == 0
    assert gate.snapshot()['preflight'] == snapshot['preflight']
    gate.halt()


@pytest.mark.parametrize('segments', [1, 3, 8])
@pytest.mark.parametrize('episodes', [2, 3])
def test_raw_broad_change_diagnostics_do_not_override_confirmation(segments, episodes):
    offset = (segments - 1) * 96
    pulses = {100 + i * 100 for i in range(episodes)}
    state = observe(WalkingPreflight(), lambda i: (offset, offset + 10, offset + 20) if i in pulses else (), n=segments)
    assert state['ready']
    assert not state['bad_indices']
    assert state['stability']['broad_change_events'] == episodes


def test_confirmation_requires_full_device_interval():
    gate = WalkingPreflight()
    for i in range(10):
        gate.feed(sample(i, (40,)))
    assert not gate._previous_bits and gate.pending_indices == (40,)
    gate.feed(sample(10, (40,)))
    assert gate._previous_bits == {40} and not gate.pending_indices


def test_runtime_observation_keeps_counts_without_empty_field_classification(monkeypatch):
    import hardware.walking_preflight as module
    from collections import Counter, deque
    gate = WalkingPreflight(stabilize=False)
    window = deque(maxlen=gate.policy.samples)
    previous = set()
    def unexpected_classification(*args):
        pytest.fail('Runtime evidence must not classify all beams as empty-field faults')
    monkeypatch.setattr(module, 'longest_run', unexpected_classification)
    for index in range(3205):
        bits = set(range(576, 768)) if index % 13 < 3 else {40}
        assert gate.observe(sample(index, bits, n=8))
        window.append((bits, bits ^ previous if index else set()))
        previous = bits
        if index in (2999, 3204):
            counts = Counter(i for occupied, _ in window for i in occupied)
            transitions = Counter(i for _, changed in window for i in changed)
            assert +gate._counts == counts
            assert +gate._transitions == transitions
    assert not gate.observe(sample(3205, quality_flags=('crc_error',), n=8))
    assert gate.healthy_samples == 0 and not gate._counts


def test_runtime_faults_expire_with_window_and_reset_after_discontinuity(qtbot):
    gate = DeviceQualitySession(config_from_dict({'test_type': 'Jump Test'}),
                                BeamQualityPolicy(observation_seconds=1))
    for i in range(1000):
        gate.on_frame(sample(i))
    gate.arm_checked((gate.preflight.context.key, False))
    for i in range(1000, 2000):
        gate.on_frame(sample(i, (40,)))
    assert gate._runtime_suspicious_indices == (40,)
    for i in range(2000, 3000):
        gate.on_frame(sample(i))
    assert not gate._runtime_suspicious_indices
    for i in range(3000, 4000):
        gate.on_frame(sample(i, (60,)))
    assert gate._runtime_suspicious_indices == (60,)
    gate.on_frame(sample(4002, dropped_frames_before=2, quality_flags=('frame_gap',)))
    gate.on_frame(sample(4003))
    assert not gate._runtime_suspicious_indices
    assert gate._runtime.healthy_samples == 1
    gate.halt()


def test_short_transients_reach_history_ai_and_stay_out_of_visible_report(qtbot):
    import json
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from data.subject_store import _report_detail, _report_from_detail
    from ui.views.report_view import ReportView
    report = GaitEngine(config=config_from_dict({'test_type': 'Jump Test'})).build_report('manual')
    state = observe(WalkingPreflight(), lambda i: (40,) if i == 100 else ())
    quality = {'degraded': False, 'events': [], 'preflight': {'bad_indices': [], 'stability': state['stability']}}
    report.report_config_snapshot['beam_quality'] = quality
    restored = _report_from_detail(json.loads(json.dumps(_report_detail(report))))
    assert restored.report_config_snapshot['beam_quality']['preflight']['stability']['transient_beam_pulses'] == 1
    package = ReportDataPackageBuilder().build(restored, ReportContextInput(session_id=1, test_type='Jump Test'))
    assert any(flag.code == 'beam_quality' for flag in package.quality_flags)
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(restored)
    assert '自检短时变化' not in view._reason_label.text()
    assert '未计入坏灯' not in view._reason_label.text()


def test_native_runtime_counts_match_independent_rolling_counter_and_reset():
    from collections import Counter, deque
    from hardware.walking_preflight import RuntimeBeamEvidence
    policy = BeamQualityPolicy(observation_seconds=1)
    evidence = RuntimeBeamEvidence(policy)
    window, previous = deque(maxlen=policy.samples), set()
    for index in range(1400):
        bits = set(range(576, 768)) if index % 13 < 3 else {40}
        assert evidence.observe(sample(index, bits, n=8))
        window.append((bits, bits ^ previous if index else set()))
        previous = bits
        if index in (0, 998, 999, 1000, 1399):
            counts = Counter(i for occupied, _ in window for i in occupied)
            changes = Counter(i for _, changed in window for i in changed)
            assert evidence._counts.tolist() == [counts[i] for i in range(768)]
            assert evidence._transitions.tolist() == [changes[i] for i in range(768)]
    assert not evidence.observe(sample(1400, n=8, quality_flags=('crc_error',)))
    assert evidence.healthy_samples == 0 and not evidence._counts.size
    assert evidence.observe(sample(1401, (20,), n=8))
    assert evidence._counts[20] == 1 and evidence._transitions.sum() == 0
    assert evidence.observe(replace(sample(1404, (30,), n=8), stream_id='new'))
    assert evidence.healthy_samples == 1
    assert evidence._counts[30] == 1 and evidence._counts[20] == 0
    assert evidence._transitions.sum() == 0
    assert evidence.observe(sample(1405, (10,), n=2))
    assert evidence.healthy_samples == 1 and len(evidence._counts) == 192
