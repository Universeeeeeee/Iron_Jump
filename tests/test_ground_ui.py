"""Device geometry, preflight and replay regressions without physical USB/video."""
from dataclasses import replace
import time

import pytest
from qtpy.QtCore import QPoint, Qt
from qtpy.QtWidgets import QApplication

from config.test_config import default_jump_config
from config.treadmill_report import TreadmillGaitReport
from config.walking_config import WalkingConfig
from hardware.sensor_frame import DeviceLayout, SensorSegment
from hardware.beam_quality import BeamQualityPolicy
from hardware.walking_preflight import WalkingPreflight
from engine.walking_session import WalkingSession
from ui.footprint_channel import FootprintReplayPanel
from ui.ground_track import GroundTrackPanel
from ui.views.execution_view import ExecutionView
from ui.views.setup_view import SessionSetup
from tests.test_overground_walking import frame, processor, walk, CONTACTS
from tests.test_main_window_navigation import _window


def visual(layout, *, timestamp=0, blocked=()):
    return {"positions_m": layout.positions_m, "timestamp_s": timestamp,
            "contact_bits": [int(i in blocked) for i in range(layout.bit_count)],
            "valid_bits": [1] * layout.bit_count, "feet": []}


@pytest.mark.parametrize("count", [1, 3, 8, 12])
def test_ground_selection_keeps_all_beams_and_physical_positions(qtbot, count):
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    panel.resize(300, 900)
    panel.show()
    layout = DeviceLayout.linear(count)
    panel.render_state(visual(layout, blocked=(layout.bit_count - 1,)))
    QApplication.processEvents()
    channel = panel.channel
    rect = channel.lane_rect()
    qtbot.mouseClick(channel, Qt.LeftButton, pos=QPoint(int(rect.center().x()), int(rect.bottom() - 1)))
    assert channel.selected_segment == count - 1
    assert len(channel._contact_bits) == count * 96
    assert panel.detail_channel._positions_m == layout.positions_m[-96:]
    assert "96" in panel.detail_status.text()
    qtbot.keyClick(channel, Qt.Key_Up)
    assert channel.selected_segment == max(0, count - 2)


def test_segment_detail_uses_calibrated_geometry_and_keeps_unknown_data(qtbot):
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    layout = DeviceLayout((SensorSegment("near", 1, 2.0), SensorSegment("far", 0, 3.1, reversed=True)))
    state = visual(layout, blocked=(97,))
    state["valid_bits"][98] = 0
    panel.render_state(state)
    panel.channel.select_segment(1)
    assert panel.detail_channel._positions_m[0] == 3.1
    assert "3" in panel.detail_status.text()
    assert "无效" in panel.detail_status.text()
    assert panel.detail_channel.valid_bits[2] == 0
    assert panel.detail_channel._contact_bits[1] == 1


def test_preflight_exposes_local_faults_and_stale_data_without_ready():
    gate = WalkingPreflight()
    layout = DeviceLayout.linear(8)
    sample = frame(layout, 0, [(4.2, 4.3)])
    gate.feed(sample)
    status = gate.status(sample.received_monotonic_ns)
    assert not status["ready"]
    assert any(status["visual_frame"]["contact_bits"][384:480])
    assert all(status["visual_frame"]["valid_bits"])
    valid = bytearray([1] * layout.bit_count)
    valid[401] = 0
    sample = replace(frame(layout, 1), valid_bits=bytes(valid))
    gate.feed(sample)
    status = gate.status(sample.received_monotonic_ns)
    assert status["visual_frame"]["valid_bits"].count(0) == 1
    assert not gate.status(sample.received_monotonic_ns + 500_000_001)["visual_frame"]["valid_bits"][0]


def test_start_rejects_changed_layout_even_after_new_self_check():
    session = WalkingSession(WalkingConfig())
    session.preflight.policy = BeamQualityPolicy(observation_seconds=1)
    for i in range(1000):
        session.on_frame(frame(DeviceLayout.linear(3), i))
    old_key = session.preflight.status(time.perf_counter_ns())["device_key"]
    for i in range(1000):
        session.on_frame(frame(DeviceLayout.linear(8), i, stream="replacement"))
    rejected = []
    session.readiness.connect(rejected.append)
    session.arm_checked(old_key)
    assert session.processor is None
    assert rejected[-1]["start_rejected"]
    session.arm_checked(session.preflight.status(time.perf_counter_ns())["device_key"])
    assert len(session.processor.device.layout.segments) == 8


def test_replay_history_rewinds_and_excludes_invalid_contacts(qtbot):
    panel = FootprintReplayPanel()
    qtbot.addWidget(panel)
    layout = DeviceLayout.linear(8)
    panel.set_ground_context({"positions_m": layout.positions_m}, {
        "contacts": [
            {"confirmed": True, "position_m": 1.2, "end": .5, "side": "unknown"},
            {"confirmed": True, "position_m": 2.1, "end": .8, "exclusion": "frame_gap"},
        ], "direction": 1,
    })
    invalid = visual(layout, timestamp=2)
    invalid["valid_bits"] = [0] * layout.bit_count
    panel.set_timeline([visual(layout), visual(layout, timestamp=1), invalid])
    panel._slider.setValue(1)
    assert len(panel.ground_track.channel.history) == 1
    assert panel.ground_track.channel.history[0]["side"] == "unknown"
    panel._slider.setValue(0)
    assert not panel.ground_track.channel.history
    panel._slider.setValue(2)
    assert not any(panel.ground_track.channel.valid_bits)
    panel._slider.setValue(0)
    panel._toggle_playback()
    assert panel._timer.interval() == 1000  # unknown/gap intervals keep device time
    panel._toggle_playback()


@pytest.mark.parametrize("size", [(1920, 1080), (1180, 720)])
def test_ground_rail_spans_voice_and_restores_other_modes(qtbot, tmp_path, monkeypatch, size):
    monkeypatch.setattr("ui.embedded_camera_panel.EmbeddedCameraPanel.start_preview", lambda self: None)
    window, controller = _window(qtbot, tmp_path)
    window.resize(*size)
    window.show()
    window._on_ready(SessionSetup(config=WalkingConfig(), subject_id=None, subject=None))
    view = window._exec_view
    view.on_walking_readiness({"ready": True, "segment_count": 8, "message": "空场自检通过",
                               "visual_frame": visual(DeviceLayout.linear(8))})
    QApplication.processEvents()
    rail = window._ground_rail
    voice = window._voice_panel
    assert rail.isVisible()
    assert rail.height() == window._stack.height() + voice.height()
    assert rail.mapTo(window, QPoint(0, rail.height())).y() == voice.mapTo(window, QPoint(0, voice.height())).y()
    assert window.width() == size[0]
    assert not view._footprint_channel.isVisible()
    assert view._ground_track.detail.isVisible()
    assert view.btn_start.text() == "确认共 8 段并开始"
    qtbot.mouseClick(view.btn_start, Qt.LeftButton)
    assert controller.starts == 1

    p = processor(8, stop_type="Software command")
    walk(p, CONTACTS, 2400)
    window._report_view.load_report(p.build_report("manual"))
    window._go_to_report()
    QApplication.processEvents()
    assert window._report_view._replay_panel.parentWidget() is rail
    assert not view._ground_track.isVisible()
    assert rail.isVisible()
    assert len(window._report_view._replay_panel.ground_track.channel._contact_bits) == 768

    window._report_view.load_report(TreadmillGaitReport(
        finish_reason="manual", touch_count=0, lift_count=0,
        resolved_starting_foot="unknown", starting_foot_source="unknown",
    ))
    window._go_to_report()
    assert not rail.isVisible()
    assert window._report_view._replay_panel.parentWidget() is not rail
    assert window._report_view._replay_panel._channel.isVisible()
    window._on_ready(SessionSetup(config=default_jump_config(), subject_id=None, subject=None))
    assert not rail.isVisible()
    assert not view._ground_track.detail.isVisible()


def test_single_segment_mode_blocks_multisegment_and_recovers(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(default_jump_config())
    view.on_device_layout(DeviceLayout.linear(8))
    view.on_device_state("connected", "已连接")
    view.on_device_message("ordinary device log")
    assert not view.btn_start.isEnabled()
    assert "仅支持单段" in view._device_label.text()
    view.on_device_layout(DeviceLayout.linear(1))
    assert view.btn_start.isEnabled()


def test_controller_rejects_known_multisegment_before_start(qtbot):
    from ui.session_controller import SessionController
    from tests.test_session_controller_lifecycle import _FakeUsbWorker
    controller = SessionController(worker_factory=_FakeUsbWorker)
    try:
        controller.prepare(default_jump_config())
        qtbot.waitUntil(lambda: controller.device_state == "connected")
        controller._on_device_layout(DeviceLayout.linear(8))
        controller.start()
        assert not controller._start_pending
        assert not controller.is_running
    finally:
        controller.discard()


def test_setup_health_locates_module_and_local_beam(qtbot):
    from ui.views.setup_view import SetupView
    view = SetupView(llm_client=None)
    qtbot.addWidget(view)
    view.on_device_state("connected")
    view.on_device_layout(DeviceLayout.linear(8))
    view.on_led_health({"status": "warning", "disconnected_leds": [210], "flickering_leds": []})
    assert "第 3 段：18" in view._device_meta_label.text()
    assert "768 路" in view._device_meta_label.text()
    view.on_device_state("disconnected")
    assert "768 路" not in view._device_meta_label.text()


def test_running_history_requires_valid_spatial_reference(qtbot):
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    valid = lambda value: {"valid": True, "value": value}
    panel.set_summary({"contacts": [
        {"toe_m": valid(1.2), "lift_s": valid(.5), "contact_s": valid(.3)},
        {"toe_m": {"valid": False}, "lift_s": valid(.7), "contact_s": valid(.3)},
    ]})
    panel.render_state(visual(DeviceLayout.linear(3), timestamp=1))
    assert len(panel.channel.history) == 1
    assert panel.channel.history[0]["centroid_cm"] == 120


def test_live_invalid_sample_does_not_reuse_last_valid_footprint():
    session = WalkingSession(WalkingConfig())
    session.preflight.policy = BeamQualityPolicy(observation_seconds=1)
    p = processor(3, stop_type="Software command")
    walk(p, [(0, 800, .35)], 500)
    session.processor = p
    session._last_frame = replace(frame(p.device.layout, 501), quality_flags=("invalid_sample",))
    emitted = []
    session.visual.connect(emitted.append)
    session.publish_snapshot()
    assert not any(emitted[-1]["valid_bits"])
    assert not emitted[-1]["feet"]
    assert emitted[-1]["timestamp_s"] == pytest.approx(.501)


def test_preflight_detail_distinguishes_current_frame_from_window(qtbot):
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    state = visual(DeviceLayout.linear(8))
    state['preflight_bad_indices'] = (576,)
    state['preflight_transient_indices'] = (577,)
    panel.render_state(state)
    assert '本段当前帧' in panel.detail_status.text()
    assert '全程自检' in panel.detail_status.text()
    panel.channel.select_segment(6)
    assert '观察窗异常束：1' in panel.detail_status.text()
    assert '短暂遮挡束：2' in panel.detail_status.text()
    assert '当前帧' in panel.detail_status.text()


def test_preflight_view_shows_fault_locations_without_hover(qtbot):
    from tests.test_beam_quality import observe
    gate = WalkingPreflight()
    result = observe(gate, (576, 577, 578), n=8)
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(WalkingConfig())
    view.on_walking_readiness(result)
    assert '第7段' in view._ground_status.text()
    assert '1–3' in view._ground_status.text()
    assert not view.btn_start.isEnabled()
