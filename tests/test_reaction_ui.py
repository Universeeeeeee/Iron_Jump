"""Reaction UI keeps presentation timing explicit and bypasses camera startup."""
from types import SimpleNamespace

from qtpy.QtWidgets import QApplication, QAbstractItemView

from config.reaction_config import ReactionConfig
from config.reaction_report import ReactionTestReport, ReactionTrialRecord
from config.test_config import TestConfig as JumpConfig
from ui.param_panel import ParamPanel
from ui.reaction_panel import ReactionPanel
from ui.views.execution_view import ExecutionView
from ui.views.history_view import _config_detail_lines, _session_summary
from ui.views.report_view import ReportView


def test_reaction_parameters_defaults_and_round_trip(qtbot):
    panel = ParamPanel()
    qtbot.addWidget(panel)
    panel.set_test_type("Reaction Times")
    assert panel.get_config() == ReactionConfig()
    config = ReactionConfig(stimulus_type="Visual/Acoustic stimulus", start_position="Outside area",
                            sequence_type="Manual", number_of_repetitions=99,
                            minimum_pause="00:05", stimulus_delay_min_ms=1500,
                            stimulus_delay_max_ms=4500, response_timeout_ms=2500)
    panel.set_config(config)
    assert panel.get_config() == config
    assert panel._widgets["number_of_repetitions"].minimum() == 1
    assert panel._widgets["number_of_repetitions"].maximum() == 99
    assert panel._filter_section.isHidden()


def test_reaction_bypasses_pending_camera_and_keeps_controls_visible(qtbot, monkeypatch):
    view = ExecutionView()
    qtbot.addWidget(view)
    starts = []
    monkeypatch.setattr(view._camera_panel, "start_preview", lambda: starts.append(True))
    view.configure(JumpConfig())
    view.configure(ReactionConfig())
    view.resize(960, 640)
    view.show()
    view.set_compact_controls(True)
    QApplication.processEvents()
    view._select_camera("tinyse")
    view._start_camera_preview_if_visible()
    assert not starts
    assert not view._camera_start_timer.isActive()
    assert not view._camera_panel.isVisible()
    assert not view.btn_basic_camera.isVisible()
    view.on_session_started()
    assert view.btn_stop.isVisible()
    assert view._controls_container.isVisible()
    assert not view.btn_pause.isVisible()
    view.configure(JumpConfig())
    QApplication.processEvents()
    assert view.btn_basic_camera.isVisible()
    assert view._camera_panel.isVisible()
    assert starts


def test_main_reaction_prepare_start_never_previews_or_records(qtbot, tmp_path, monkeypatch):
    from tests.test_main_window_navigation import _window
    from ui.views.setup_view import SessionSetup
    window, controller = _window(qtbot, tmp_path)
    panel = window._exec_view._camera_panel
    calls = []
    monkeypatch.setattr(panel, "start_preview", lambda: calls.append("preview"))
    monkeypatch.setattr(panel, "_create_capture", lambda *args: calls.append("capture"))
    monkeypatch.setattr(panel, "_on_record", lambda *args: calls.append("record"))
    window.show()
    window._on_ready(SessionSetup(ReactionConfig()))
    window._on_start()
    controller.session_started.emit()
    window._on_camera("basic")
    QApplication.processEvents()
    assert controller.starts == 1
    assert controller.prepared[-1].test_type == "Reaction Times"
    assert not calls
    assert not panel.isVisible()


def test_timed_jump_to_reaction_clears_previous_countdown(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(JumpConfig(stop_type="End of Time", test_length="01:00"))
    view.reset()
    view.configure(ReactionConfig())
    view.on_session_started()
    assert view._countdown_remaining == 0
    assert view._countdown_timer is None


def test_reaction_readiness_keeps_specific_blocking_reason(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(ReactionConfig())
    for count, bad, pending, reason in [
        (5, [], [], "设备布局信息尚未完整，请等待识别"),
        (1, [7], [], "请清空测量区域并排除异常光束后开始反应时测试"),
        (1, [], [7], "第 1 段第 8 束尚未稳定，请检查遮挡"),
    ]:
        result = dict(ready=False, segment_count=count, bad_indices=bad,
                      pending_indices=pending, message=reason)
        view.on_walking_readiness(result)
        assert reason in view._device_label.text()
        assert not view.btn_start.isEnabled()


def test_reaction_five_segment_layout_waits_for_preflight_without_single_segment_block(qtbot):
    from hardware.sensor_frame import DeviceLayout
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(ReactionConfig())
    view.set_quality_preflight_required(True)
    view.on_device_layout(DeviceLayout.linear(5))
    view.on_device_state("connected", "设备已连接")
    assert view._detected_segments == 5
    assert "仅支持单段" not in view._device_label.text()
    assert not view.btn_start.isEnabled()
    view.on_walking_readiness(dict(ready=True, segment_count=5, message="设备就绪"))
    assert view.btn_start.isEnabled()
    view.on_device_message("5 段设备正在接收数据")
    assert view.btn_start.isEnabled()
    assert "仅支持单段" not in view._device_label.text()
    assert view._camera_panel.isHidden() or view._lower_split.isHidden()
    assert view._ground_track.isHidden()


def test_five_segment_layout_still_blocks_original_single_segment_modes(qtbot):
    from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
    from hardware.sensor_frame import DeviceLayout
    for config in (JumpConfig(),
                   TreadmillGaitConfig(stop_type="Software command", test_length=None),
                   TreadmillRunningConfig(stop_type="Software command", test_length=None)):
        view = ExecutionView()
        qtbot.addWidget(view)
        view.configure(config)
        view.on_device_layout(DeviceLayout.linear(5))
        view.on_device_state("connected", "设备已连接")
        view.on_device_message("5 段设备正在接收数据")
        assert "仅支持单段" in view._device_label.text()
        assert not view.btn_start.isEnabled()


def test_other_mode_readiness_keeps_existing_message(qtbot):
    from config.walking_config import WalkingConfig
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(WalkingConfig())
    view.on_walking_readiness(dict(ready=False, segment_count=8,
                                   message="backend specific message"))
    assert "正在检查设备，请保持测量区域无人" in view._device_label.text()


def test_reaction_instructions_distinguish_clear_field_from_trial_posture(qtbot):
    for position, instruction in (("Inside area", "站在测量区内"),
                                  ("Outside area", "站在测量区外")):
        view = ExecutionView()
        qtbot.addWidget(view)
        view.configure(ReactionConfig(start_position=position))
        assert "请先离开测量区" in view._reaction_panel.instruction.text()
        assert "自检通过后点击开始" in view._reaction_panel.instruction.text()
        view.on_session_started()
        assert instruction in view._reaction_panel.instruction.text()
        assert "请先离开测量区" not in view._reaction_panel.instruction.text()


def test_preparing_snapshot_can_advance_instruction_before_start_signal(qtbot):
    panel = ReactionPanel()
    qtbot.addWidget(panel)
    panel.configure(ReactionConfig())
    panel.update_snapshot(dict(state="preparing", trial_index=1, total_trials=5))
    assert "站在测量区内" in panel.instruction.text()


def test_visual_presentation_echoes_request_clock_and_clears_on_stop(qtbot, monkeypatch):
    panel = ReactionPanel()
    qtbot.addWidget(panel)
    panel.configure(ReactionConfig())
    calls = []
    panel.stimulus_presented.connect(calls.append)
    monkeypatch.setattr("ui.reaction_panel.time.perf_counter_ns", lambda: 12345)
    panel.present({"session_id": "current", "trial_index": 2, "stimulus_type": "visual"})
    assert calls[0]["requested_monotonic_ns"] == 12345
    assert calls[0]["session_id"] == "current"
    assert calls[0]["calibrated"] is False
    assert calls[0]["success"] is True
    assert "#16834f" in panel.stimulus.styleSheet()
    panel.update_snapshot(dict(state="stimulus_pending", trial_index=2, total_trials=5))
    panel.update_snapshot(dict(state="responding", trial_index=2, total_trials=5))
    assert "#16834f" in panel.stimulus.styleSheet()
    panel.clear()
    panel.present({"trial_index": 3, "stimulus_type": "visual"})
    assert len(calls) == 1
    assert "#8c293b" in panel.stimulus.styleSheet()


def test_acoustic_request_without_preloaded_sound_fails(qtbot):
    panel = ReactionPanel()
    qtbot.addWidget(panel)
    panel.configure(ReactionConfig())
    calls = []
    panel.stimulus_presented.connect(calls.append)
    panel.present({"trial_index": 1, "stimulus_type": "acoustic"})
    assert calls[0]["success"] is False
    assert calls[0]["error"]


def test_preloaded_acoustic_playback_keeps_screen_unchanged(qtbot, monkeypatch):
    panel = ReactionPanel()
    qtbot.addWidget(panel)
    panel.configure(ReactionConfig())
    events = []
    panel._sound = SimpleNamespace(isLoaded=lambda: True, play=lambda: events.append("play"), stop=lambda: None)
    monkeypatch.setattr("ui.reaction_panel.time.perf_counter_ns", lambda: events.append("clock") or 45678)
    panel.update_snapshot(dict(state="waiting", trial_index=1, total_trials=5))
    waiting_text = panel.stimulus.text()
    results = []
    panel.stimulus_presented.connect(results.append)
    panel.present({"trial_index": 1, "stimulus_type": "acoustic"})
    panel.update_snapshot(dict(state="responding", trial_index=1, total_trials=5))
    assert events == ["clock", "play"]
    assert results[0]["success"] is True
    assert results[0]["requested_monotonic_ns"] == 45678
    assert panel.stimulus.text() == waiting_text
    assert "#8c293b" in panel.stimulus.styleSheet()


def test_manual_next_readiness_and_latest_trial(qtbot):
    panel = ReactionPanel()
    qtbot.addWidget(panel)
    panel.configure(ReactionConfig(sequence_type="Manual"))
    panel.show()
    snapshot = dict(state="manual_wait", trial_index=2, total_trials=5,
                    next_allowed=False, latest_trial=ReactionTrialRecord(
                        1, "visual", "takeoff", "early"))
    panel.update_snapshot(snapshot)
    assert panel.next_button.isVisible()
    assert not panel.next_button.isEnabled()
    assert "抢先反应" in panel.result_label.text()
    panel.update_snapshot({**snapshot, "next_allowed": True})
    assert panel.next_button.isEnabled()


def test_reaction_report_is_read_only_and_uncalibrated(qtbot):
    view = ReportView(llm_client=object())
    qtbot.addWidget(view)
    report = ReactionTestReport((
        ReactionTrialRecord(1, "visual", "takeoff", "valid", reaction_time_ms=240),
        ReactionTrialRecord(2, "acoustic", "takeoff", "early"),
    ))
    view.set_analysis_availability(True)
    view.load_report(report, session_id=1)
    view.resize(960, 640)
    view.show()
    QApplication.processEvents()
    assert view._reaction_table.rowCount() == 2
    assert view._reaction_table.item(1, 4).text() == "—"
    assert view._reaction_table.editTriggers() == QAbstractItemView.NoEditTriggers
    assert view._analysis_entry.isHidden()
    assert view._replay_panel.isHidden()
    assert "未校准" in view._reason_label.text()
    assert "混合刺激" in view._stat_cards[1]._label.text()
    for card in view._stat_cards[:5]:
        assert card.height() >= card.minimumSizeHint().height()


def test_reaction_history_summary_and_configuration():
    session = SimpleNamespace(report_summary={"report_type": "reaction", "attempt_count": 3,
                                              "valid_count": 2, "mean_reaction_time_ms": 234.5})
    assert "有效 2 / 3 次" in _session_summary(session)
    assert "未校准" in _session_summary(session)
    assert "随机等待" in "\n".join(_config_detail_lines(ReactionConfig()))
