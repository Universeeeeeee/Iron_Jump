"""Synthetic raw contacts must pass the real engine, UI and persistence path."""

import pytest

from config.treadmill_config import TreadmillGaitConfig
from engine.gait_engine import GaitEngine
from engine.modes.treadmill_processor import TreadmillProcessor
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from hardware.simulated_worker import gait_contact_frame
from ui.demo import DemoWindow
from ui.views.setup_view import SessionSetup


def config():
    return TreadmillGaitConfig(
        stop_type="Software command", test_length=None,
        treadmill_speed=3.6, direction="Interface side", starting_foot_override="left",
    )


def test_raw_contact_fixture_produces_complete_cycles(qapp):
    engine = GaitEngine(config=config())
    engine.begin_session(100.0)
    for sample in range(12200):
        seconds = sample / 1000
        engine.process_raw_frame(gait_contact_frame(seconds), 100 + seconds)
    report = engine.build_report()
    assert len(report.gait_cycles) == 22
    for cycle in report.gait_cycles:
        assert cycle.is_included_in_statistics
        assert cycle.gait_cycle_s == pytest.approx(1, abs=0.002)
        # The real contact filter adds a few milliseconds to the raw fixture.
        assert cycle.stance_phase_s == pytest.approx(0.6, abs=0.015)
        assert cycle.swing_phase_s == pytest.approx(0.4, abs=0.015)
    assert report.cycle_asymmetry_percent["gait_cycle_s"] == pytest.approx(0)
    assert len(report.export_frames) == 12200


def test_demo_start_pause_resume_save_and_reopen(qtbot, tmp_path):
    window = DemoWindow(db_path=tmp_path / "demo.sqlite3")
    qtbot.addWidget(window)
    controller = window._controller
    try:
        window._on_ready(SessionSetup(config=config(), subject_id=None, subject=None))
        qtbot.waitUntil(lambda: controller.device_state == "connected")
        controller.start()
        qtbot.waitUntil(lambda: controller.is_running)
        qtbot.waitUntil(lambda: len(controller.engine._export_frames) > 2400, timeout=6000)
        controller.pause()
        qtbot.waitUntil(lambda: controller.is_paused)
        frame_count = len(controller.engine._export_frames)
        qtbot.wait(150)
        assert len(controller.engine._export_frames) == frame_count
        controller.resume()
        qtbot.waitUntil(lambda: not controller.is_paused)
        qtbot.waitUntil(lambda: len(controller.engine._export_frames) > frame_count + 1300, timeout=4000)
        controller.stop("manual")
        assert window._stack.currentWidget() is window._report_view
        sessions = window._subject_store.get_all_sessions()
        assert len(sessions) == 1
        saved = window._subject_store.get_session(sessions[0].id).report
        assert saved.gait_cycles
        assert saved.report_config_snapshot["data_source"] == "simulation"
        window._report_view.load_report(saved, sessions[0].id)
        assert "模拟数据" in window._report_view._title.text()
        assert not window._llm_client.is_running
        assert controller._thread is None
    finally:
        window.close()


def test_pause_does_not_create_a_cycle_across_the_boundary():
    processor = TreadmillProcessor(config(), "treadmill_gait")
    for sample in range(2400):
        t = sample / 1000
        processor.process_raw_frame(gait_contact_frame(t), t, 100 + t)
    processor.pause_boundary()
    for sample in range(2400, 7200):
        t = sample / 1000
        processor.process_raw_frame(gait_contact_frame(t + 0.3), t, 100.3 + t)
    report = processor.build_report("manual", (), ())
    boundary = report.report_config_snapshot["pause_boundaries_s"][0]
    assert report.gait_cycles
    assert all(not (c.start_time_s < boundary < c.end_time_s) for c in report.gait_cycles)
    suspended = [r for r in report.per_step_results if r.row_status == "suspended"]
    assert suspended and all(not r.is_included_in_statistics for r in suspended)
    assert all(r.statistics_exclusion_reason for r in suspended)


def test_lift_of_pre_pause_foot_cannot_close_other_foot_after_resume():
    accumulator = TreadmillGaitAccumulator(config())
    accumulator.record_touch(0.0, "left", 10, 30)
    accumulator.pause_boundary(0.2)
    accumulator.record_touch(0.3, "right", 50, 70)
    accumulator.record_lift(0.4, "left")
    assert len(accumulator.rows) == 1
    accumulator.record_lift(0.9, "right")
    assert len(accumulator.rows) == 2
    assert accumulator.rows[-1].contact_time_s == pytest.approx(0.6)
