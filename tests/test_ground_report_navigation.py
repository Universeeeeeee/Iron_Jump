"""Ground report navigation keeps record identity and metric eligibility intact."""
import pytest
from copy import deepcopy
from dataclasses import replace
from qtpy.QtCore import QPoint, Qt
from qtpy.QtWidgets import QTextBrowser

from tests.test_ground_bilateral import measured
from ui.views.report_view import ReportView


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_ground_details_have_analysis_and_evidence_tabs(qtbot, mode):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(measured(mode).build_report('manual'))
    assert [view._detail_tabs.tabText(i) for i in range(3)] == [
        '逐步分析', '周期分析', '原始记录']
    assert all(view._detail_tabs.isTabVisible(i) for i in range(3))
    assert view._more_stats_button.isHidden()
    assert view._ground_steps.table.rowCount() == 8
    assert view._ground_cycles.table.rowCount() == 6
    assert view._step_page.findChild(QTextBrowser) is not None


def test_record_selection_survives_filter_and_links_to_replay(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(measured('walk', 'Right').build_report('manual'))
    steps = view._ground_steps
    steps.select_contact(3)
    assert steps.selected_contact_id == 3
    assert view._replay_panel.ground_track.channel.selected_contact_id == 3
    steps.record_filter.setCurrentIndex(2)  # left foot
    assert steps.table.item(3, 0).text() == '#04'
    assert not steps.table.isRowHidden(3)
    assert steps.selected_contact_id == 3
    steps.locate_button.click()
    assert view._replay_panel._timeline[view._replay_panel._index]['timestamp_s'] >= 1.5
    view._replay_panel.ground_track.channel.contact_selected.emit(6)
    assert steps.selected_contact_id == 6
    assert steps.record_filter.currentIndex() == 0
    assert steps.table.currentRow() == 6


def test_missing_metrics_do_not_remove_landings_or_invent_values(qtbot):
    from ui.ground_report import GroundStepAnalysis
    from reporting.recognized_gait import recognized_gait
    summary = measured('walk').summary()
    summary['recognized_measurements'] = recognized_gait(summary)
    rows = summary['recognized_measurements']['rows']
    rows[2].update(step_length_m=None, contact_s=None, contact_included=False,
                   contact_basis='未完整观测离地')
    before = deepcopy(summary)
    widget = GroundStepAnalysis(summary)
    qtbot.addWidget(widget)
    widget.select_contact(rows[2]['contact_id'])
    assert widget.table.rowCount() == 8
    assert widget.values['step_length_m'].text() == '—'
    assert widget.values['contact_s'].text() == '—'
    assert widget.values['step_time_s'].text() == '0.500 s'
    assert '未完整观测离地' in widget.selection_note.text()
    assert summary == before


def test_no_replay_and_empty_report_have_no_active_locate_action(qtbot):
    from tests.test_overground_walking import processor
    view = ReportView()
    qtbot.addWidget(view)
    report = measured('walk').build_report('manual')
    view.load_report(replace(report, visual_timeline=()))
    assert not view._ground_steps.locate_button.isEnabled()
    view.load_report(processor(8, stop_type='Software command').build_report('manual'))
    assert view._ground_steps.table.rowCount() == 0
    assert not view._ground_steps.locate_button.isEnabled()
    assert view._replay_panel.ground_track.channel.selected_marker is None


def test_switching_reports_clears_selection_and_restores_treadmill_controls(qtbot):
    from config.treadmill_report import TreadmillGaitReport
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(measured('run').build_report('manual'))
    view._ground_steps.select_contact(3)
    view.load_report(TreadmillGaitReport(touch_count=0, lift_count=0,
        resolved_starting_foot='unknown', starting_foot_source='unknown', finish_reason='manual'))
    assert view._ground_steps is None
    assert not view._more_stats_button.isHidden()
    assert not view._cycle_filter.isHidden()
    assert view._detail_tabs.tabText(0) == '统计汇总'
    assert view._replay_panel.ground_track.channel.selected_marker is None


def test_clicking_painted_footprint_selects_its_original_record(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(measured('walk', 'Right').build_report('manual'))
    channel = view._replay_panel.ground_track.channel
    channel.resize(280, 650)
    foot = next(f for f in channel.history if f['contact_id'] == 2)
    lane = channel.lane_rect()
    x = lane.left() + lane.width() * .64  # Right-start third landing is right.
    y = lane.top() + lane.height() * (foot['centroid_cm'] / 100 - channel._positions_m[0]) / (
        channel._positions_m[-1] - channel._positions_m[0])
    qtbot.mouseClick(channel, Qt.LeftButton, pos=QPoint(round(x), round(y)))
    assert view._ground_steps.selected_contact_id == 2
    assert view._ground_steps.rows[2]['side'] == 'right'


def test_plot_point_and_cycle_selection_link_to_record(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(measured('walk').build_report('manual'))
    steps = view._ground_steps
    if steps.plot is not None:
        import pyqtgraph as pg
        points = next(item for item in steps.plot.items() if isinstance(item, pg.ScatterPlotItem)
                      and not isinstance(item, pg.PlotDataItem) and len(item.points()) == 7)
        points.sigClicked.emit(points, [points.points()[1]], None)
        assert steps.selected_contact_id == 2
        assert steps.plot.getAxis('left').labelUnits == 'm'
        assert steps.plot.getAxis('left').autoSIPrefixScale == 1
    view._ground_cycles.table.selectRow(1)
    assert steps.selected_contact_id == 1


@pytest.mark.parametrize('size', [(1672, 941), (1180, 720)])
def test_main_window_can_paint_and_switch_ground_analysis(qtbot, qapp, tmp_path, size):
    from tests.test_main_window_navigation import _window
    window, _ = _window(qtbot, tmp_path)
    view = window._report_view
    view.load_report(measured('walk').build_report('manual'))
    window._go_to_report()
    view._tabs.setCurrentIndex(1)
    window.resize(*size)
    window.show()
    qtbot.wait(20)
    assert window.size().toTuple() == size
    assert not window.grab().isNull()
    steps = view._ground_steps
    from ui.theme import PALETTE
    first_card = steps.layout().itemAt(0).layout().itemAt(0).widget()
    image = steps.grab().toImage()
    assert image.pixelColor(first_card.geometry().right() + 3, 10).name() == PALETTE['sidebar']
    steps.select_contact(3)
    steps.metric_selector.setCurrentIndex(1)
    assert steps.selected_contact_id == 3
    if steps.plot is not None:
        assert steps.plot.getAxis('left').labelUnits == 's'
        assert steps.plot.getAxis('left').autoSIPrefixScale == 1
    for index in (1, 2, 0):
        view._detail_tabs.setCurrentIndex(index)
        qapp.processEvents()
        assert not window.grab().isNull()
