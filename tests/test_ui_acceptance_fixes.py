"""Acceptance regressions for the existing desktop layout, using the formal QSS."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from qtpy.QtCore import QCoreApplication, QEvent
from qtpy.QtWidgets import QScrollArea

from config.test_config import default_jump_config
from tests.test_main_window_navigation import _window
from tests.ui_review_samples import jump_report
from ui.styles import CONTROL_QSS

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def desktop(qtbot, tmp_path, monkeypatch, qapp):
    previous = qapp.styleSheet()
    qapp.setStyle("Fusion")
    qapp.setStyleSheet(CONTROL_QSS)
    window, _ = _window(qtbot, tmp_path)
    monkeypatch.setattr(window._exec_view._camera_panel, "start_preview", lambda: None)
    window.show()
    yield window
    window.close()
    qapp.setStyleSheet(previous)


def settle(qtbot):
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qtbot.wait(30)


def inside(window, widget):
    rect = widget.rect().adjusted(2, 2, -2, -2)
    for point in (rect.topLeft(), rect.bottomRight()):
        point = widget.mapTo(window, point)
        hit = window.childAt(point)
        assert hit is widget or (hit is not None and widget.isAncestorOf(hit))


@pytest.mark.parametrize("mode", [0, 1])
def test_desktop_configuration_summary_fits_without_horizontal_scroll(desktop, qtbot, mode):
    desktop.resize(1366, 768)
    view = desktop._setup_view
    view._set_config_mode(mode)
    settle(qtbot)
    scroll = view.findChild(QScrollArea, "SetupWorkspaceScroll")
    assert scroll.horizontalScrollBar().maximum() == 0
    inside(desktop, view._status_bar)
    assert view._summary_label.height() >= view._summary_label.heightForWidth(view._summary_label.width())


def test_dynamic_parameters_hide_retired_rows_immediately(desktop, qtbot):
    panel = desktop._setup_view.param_panel
    desktop._setup_view._set_config_mode(1)
    settle(qtbot)
    for test_type in ("Treadmill Gait Test", "Sprint and Gait Test", "Overground Running Test",
                      "Jump Test", "Treadmill Running Test", "Jump Test"):
        old = [panel._basic_grid.itemAt(i).widget() for i in range(panel._basic_grid.count())]
        combo = panel._widgets["test_type"]
        combo.setCurrentIndex(combo.findData(test_type))
        assert all(row.isHidden() for row in old)
        settle(qtbot)
        stops = panel._widgets.get("stop_type")
        for index in range(stops.count()):
            stops.setCurrentIndex(index)
            settle(qtbot)
            rows = [panel._basic_grid.itemAt(i).widget() for i in range(panel._basic_grid.count())]
            visible = [row for row in rows if row.isVisible()]
            for i, row in enumerate(visible):
                assert all(not row.geometry().intersects(other.geometry()) for other in visible[i + 1:])
        desktop._setup_view._set_config_mode(0)
        settle(qtbot)
        assert not panel.isVisible()
        desktop._setup_view._set_config_mode(1)
        settle(qtbot)
        assert panel.isVisible()


@pytest.mark.parametrize("size", [(1600, 900), (1920, 1080), (1366, 768)])
def test_jump_six_metrics_and_both_charts_fit_first_screen(desktop, qtbot, size):
    desktop.resize(*size)
    view = desktop._report_view
    view.load_report(jump_report())
    desktop._go_to_report()
    settle(qtbot)
    cards = [c for c in view._stat_cards if c.isVisible()]
    assert [c._label.text() for c in cards] == [
        "平均跳高", "最大跳高", "有效跳跃次数", "平均腾空时间", "平均触地时间", "平均跳跃节奏",
    ]
    for card in cards:
        inside(desktop, card)
        assert 85 <= card.height() <= 140
    for plot in (view._plot_1, view._plot_2):
        inside(desktop, plot)
        assert plot.getPlotItem().items
    scroll = view._overview_page.findChild(QScrollArea)
    assert scroll.verticalScrollBar().maximum() == 0
    assert scroll.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("size", [(1366, 768), (1600, 900)])
def test_session_buttons_have_actual_large_click_targets(desktop, qtbot, size):
    desktop.resize(*size)
    view = desktop._exec_view
    view.configure(default_jump_config())
    desktop._go_to_execution()
    for running, paused in ((False, False), (True, False), (True, True), (True, False)):
        if running and view.btn_start.isVisible():
            view.on_session_started()
        view.set_paused(paused)
        settle(qtbot)
        for button in (view.btn_return_config, view.btn_start, view.btn_pause, view.btn_stop):
            if button.isVisible():
                assert button.height() >= 48
                inside(desktop, button)


def test_capture_uses_formal_theme_event_loop_and_valid_jump_fixture(tmp_path):
    output = tmp_path / "capture"
    result = subprocess.run([
        sys.executable, "exports/ui_redesign_20261024/capture.py", str(output),
        "--sizes", "1366x768", "--pages", "setup_manual,setup_agent,report_jump,execution_jump",
    ], cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_API": "pyside6"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    environment = json.loads((output / "environment.json").read_text())
    assert environment["application_qss_sha256"] == hashlib.sha256(CONTROL_QSS.encode()).hexdigest()
    assert environment["event_loop_level"] >= 1
    assert environment["jump_valid_events"] == 3
    assert len(environment["jump_heights"]) == 3
    assert all(h > 0 for h in environment["jump_heights"])
    records = json.loads((output / "geometry.json").read_text())
    execution = next(r for r in records if r["name"].endswith("execution_jump"))
    assert execution["device_segments"] == 1
    assert all(b["height"] >= 48 for b in execution["buttons"])


def test_jump_quality_note_stays_visible_without_extra_metric_card(desktop, qtbot):
    from dataclasses import replace
    from config.test_report import JumpQualityNoticeRecord

    report = replace(jump_report(), quality_notices=(JumpQualityNoticeRecord(
        kind="large_occlusion", time_s=0.1, cluster_length=96, ratio=1.0,
    ),))
    view = desktop._report_view
    view.load_report(report)
    desktop._go_to_report()
    settle(qtbot)
    assert len([c for c in view._stat_cards if c.isVisible()]) == 6
    assert "质量提示：0 条排除 / 1 条标记" in view._capture_stats.text()
    inside(desktop, view._capture_stats)


def test_empty_jump_report_does_not_retain_previous_bars(desktop, qtbot):
    from dataclasses import replace

    report = jump_report()
    view = desktop._report_view
    view.load_report(report)
    assert view._plot_1.getPlotItem().items
    empty = replace(report, touch_count=0, lift_count=0, air_times=(), contact_times=(),
        cycle_times=(), jump_heights=(), cadences=(), jump_results=(), avg_jump_height=0.0,
        max_jump_height=0.0, avg_air_time=0.0, max_air_time=0.0, avg_contact_time=0.0,
        avg_cadence=None)
    view.load_report(empty)
    assert not view._plot_1.getPlotItem().items
    assert not view._plot_2.getPlotItem().items
    assert view._stat_cards[0]._value.text() == "--"
    assert view._stat_cards[2]._value.text() == "0"


@pytest.mark.parametrize("size", [(1280, 720), (1092, 614), (910, 512)])
@pytest.mark.parametrize("mode", [0, 1])
def test_narrow_setup_reflows_without_horizontal_scroll(desktop, qtbot, size, mode):
    desktop.resize(*size)
    view = desktop._setup_view
    view._set_config_mode(mode)
    settle(qtbot)
    scroll = view.findChild(QScrollArea, "SetupWorkspaceScroll")
    assert scroll.horizontalScrollBar().maximum() == 0
    for child in view.findChildren(QScrollArea):
        assert child.horizontalScrollBar().maximum() == 0
    widgets = [w for w in view._subject_bar_widgets if w.isVisible()]
    for index, widget in enumerate(widgets):
        inside(desktop, widget)
        assert all(not widget.geometry().intersects(other.geometry()) for other in widgets[index + 1:])
    # A tall summary may span multiple viewport heights; both ends must be reachable.
    for point in (view._status_bar.rect().adjusted(2, 2, -2, -2).topLeft(),
                  view._status_bar.rect().adjusted(2, 2, -2, -2).bottomRight()):
        target = view._status_bar.mapTo(scroll.widget(), point)
        scroll.ensureVisible(target.x(), target.y(), 2, 2)
        settle(qtbot)
        hit = desktop.childAt(view._status_bar.mapTo(desktop, point))
        assert hit is view._status_bar or (hit and view._status_bar.isAncestorOf(hit))
    inside(desktop, view.btn_ready)


@pytest.mark.parametrize("size", [(1280, 720), (1092, 614), (910, 512)])
def test_small_jump_charts_remain_readable_and_scrollable(desktop, qtbot, size):
    desktop.resize(*size)
    view = desktop._report_view
    view.load_report(jump_report())
    desktop._go_to_report()
    settle(qtbot)
    scroll = view._overview_page.findChild(QScrollArea)
    for plot in (view._plot_1, view._plot_2):
        assert plot.height() >= 200
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        settle(qtbot)
        inside(desktop, plot)
    assert scroll.horizontalScrollBar().maximum() == 0
    inside(desktop, view.btn_home)
    assert len([c for c in view._stat_cards if c.isVisible()]) == 6


def test_jump_capture_statistics_restore_counts_and_hide_for_other_reports(desktop, qtbot):
    from config.treadmill_report import TreadmillRunningReport

    view = desktop._report_view
    view.load_report(jump_report())
    desktop._go_to_report()
    settle(qtbot)
    assert "采集统计" in view._capture_stats.text()
    assert "触地次数：4" in view._capture_stats.text()
    assert "离地次数：3" in view._capture_stats.text()
    assert view._capture_stats.isVisible()
    view.load_report(TreadmillRunningReport(finish_reason="manual", touch_count=8, lift_count=8,
        resolved_starting_foot="left", starting_foot_source="auto_first_contact"))
    settle(qtbot)
    assert view._capture_stats.isHidden()
    assert view._plot_1.minimumHeight() == 0


@pytest.mark.parametrize("scale,size", [("1.25", "1092x614"), ("1.5", "910x512")])
def test_scaled_capture_preserves_readable_charts_and_setup_width(tmp_path, scale, size):
    output = tmp_path / "scaled"
    result = subprocess.run([
        sys.executable, "exports/ui_redesign_20261024/capture.py", str(output),
        "--sizes", size, "--pages", "setup_manual,setup_agent,report_jump",
    ], cwd=ROOT, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_API": "pyside6",
                     "QT_SCALE_FACTOR": scale}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    records = json.loads((output / "geometry.json").read_text())
    for record in records:
        assert record["actual_size"] == list(map(int, size.split("x")))
        assert all(button["inside_window"] for button in record["buttons"])
        if "setup" in record:
            assert record["setup"]["horizontal_scroll_maximum"] == 0
        else:
            assert record["report_scroll"]["horizontal_maximum"] == 0
            assert record["report_scroll"]["vertical_maximum"] > 0
            assert all(plot["height"] >= 200 and plot["inside_viewport"]
                       for plot in record["plots_after_scroll"])
            assert "触地次数：4" in record["capture_statistics"]
            assert "离地次数：3" in record["capture_statistics"]
