from dataclasses import replace

import pytest

pytest.importorskip("dayu_widgets")

from qtpy.QtWidgets import QApplication, QScrollArea, QTableWidget

from config.test_report import JumpTestReport
from config.treadmill_report import (
    GaitCycleRecord,
    TreadmillGaitReport,
    TreadmillRunningReport,
    summarize,
)
from engine.footprint_visualization import FootprintVisualFrame
from ui.footprint_channel import FootprintReplayPanel
from ui.views.report_view import CyclePhaseBar, ReportView, StatCard


def _app():
    return QApplication.instance() or QApplication([])


def _visible_card_data(view):
    return [
        (card._label.text(), card._value.text(), card.toolTip())
        for card in view._stat_cards
        if not card.isHidden()
    ]


def test_report_overview_uses_three_columns_without_scroll(qtbot):
    view = ReportView()
    qtbot.addWidget(view)

    assert not hasattr(view, "_stats_scroll")
    assert view._stats_layout.columnCount() == 3
    assert len(view._stat_cards) == 12


def test_gait_overview_prioritizes_available_biomechanics(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=10,
        lift_count=10,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=tuple(
            _step(i, "left" if i % 2 == 0 else "right")
            for i in range(10)
        ),
        metric_summaries={
            "step_length_cm": summarize((60.0, 62.0)),
            "contact_time_s": summarize((0.25, 0.27)),
            "cadence_steps_per_min": summarize((110.0, 114.0)),
            "flight_time_s": summarize((0.04, 0.05)),
        },
        cycle_metric_summaries={
            "stride_length_cm": summarize((122.0, 124.0)),
            "gait_cycle_s": summarize((1.0, 1.1)),
            "stance_phase_percent": summarize((61.0, 62.0)),
            "swing_phase_percent": summarize((39.0, 38.0)),
            "total_double_support_s": summarize((0.12, 0.13)),
        },
        report_config_snapshot={
            "treadmill_speed": 5.0,
            "direction": "Interface side",
        },
        export_timestamps=(2.0, 12.0),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)
    cards = _visible_card_data(view)
    labels = [label for label, _, _ in cards]

    assert labels[:8] == [
        "平均步长",
        "平均步幅",
        "平均步频",
        "平均步态周期",
        "平均触地时间",
        "平均支撑相",
        "平均摆动相",
        "平均双支撑时间",
    ]
    assert "平均腾空时间" not in labels
    assert "有效步数" in labels
    assert len(cards) <= 12
    assert dict((label, value) for label, value, _ in cards)[
        "实际测试时长"
    ] == "10.0 s"
    tooltips = dict((label, tooltip) for label, _, tooltip in cards)
    assert tooltips["平均步长"]
    assert tooltips["平均步幅"]


def test_running_overview_includes_flight_time(qtbot):
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=2,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        metric_summaries={"flight_time_s": summarize((0.08, 0.09))},
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert "平均腾空时间" in [
        label for label, _, _ in _visible_card_data(view)
    ]


def test_treadmill_overview_omits_unknown_starting_foot(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        report_config_snapshot={"direction": "Interface side"},
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    labels = [
        label for label, _, _ in _visible_card_data(view)
    ]
    assert "起始脚" not in labels
    assert "行进方向" in labels


def test_treadmill_details_use_three_internal_tabs(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(
        TreadmillGaitReport(
            finish_reason="manual",
            touch_count=0,
            lift_count=0,
            resolved_starting_foot="unknown",
            starting_foot_source="unknown",
        )
    )

    assert [view._detail_tabs.tabText(i) for i in range(3)] == [
        "统计汇总",
        "周期明细",
        "逐步数据",
    ]
    assert not isinstance(view._details_page, QScrollArea)


def test_non_treadmill_report_hides_empty_details_tab(qtbot):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(
        JumpTestReport(
            touch_count=1,
            lift_count=1,
            air_times=(0.4,),
            contact_times=(0.2,),
            cycle_times=(0.6,),
            avg_jump_height=0.1962,
            max_jump_height=0.1962,
            avg_air_time=0.4,
            max_air_time=0.4,
            avg_contact_time=0.2,
            avg_cadence=100.0,
            finish_reason="manual",
            jump_heights=(0.1962,),
        )
    )

    assert not view._tabs.isTabVisible(1)


def test_detail_filters_default_to_included_and_preserve_report(qtbot):
    included = _cycle(index=0, is_included_in_statistics=True)
    excluded = _cycle(
        index=1,
        side="right",
        is_included_in_statistics=False,
        statistics_exclusion_reason="Contact time below minimum threshold",
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=2,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        gait_cycles=(included, excluded),
        per_step_results=(
            _step(0, "left"),
            replace(
                _step(1, "right"),
                is_included_in_statistics=False,
                statistics_exclusion_reason=(
                    "Contact time below minimum threshold"
                ),
            ),
        ),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert view._cycle_filter.currentData() == "included"
    assert view._cycle_detail_table.rowCount() == 1
    assert view._step_filter.currentData() == "included"
    assert view._treadmill_step_table.rowCount() == 1
    view._cycle_filter.setCurrentIndex(
        view._cycle_filter.findData("excluded")
    )
    view._step_filter.setCurrentIndex(
        view._step_filter.findData("excluded")
    )
    assert view._cycle_detail_table.rowCount() == 1
    assert view._treadmill_step_table.rowCount() == 1
    assert report.gait_cycles == (included, excluded)


def test_treadmill_details_use_compact_mode_specific_columns(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        gait_cycles=(_cycle(stride_length_cm=120.0),),
        per_step_results=(_step(0, "left"),),
        metric_summaries={
            "step_length_cm": summarize((60.0,)),
            "contact_time_s": summarize((0.25,)),
        },
        cycle_metric_summaries={
            "stride_length_cm": summarize((120.0,)),
            "gait_cycle_s": summarize((1.0,)),
        },
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert [
        view._summary_table.horizontalHeaderItem(index).text()
        for index in range(6)
    ] == [
        "指标",
        "有效样本数",
        "总体均值",
        "左脚均值",
        "右脚均值",
        "不对称性",
    ]
    assert all(
        view._summary_table.isColumnHidden(index)
        for index in range(6, 10)
    )
    view._more_stats_button.setChecked(True)
    assert not any(
        view._summary_table.isColumnHidden(index)
        for index in range(6, 10)
    )
    assert [
        view._cycle_detail_table.horizontalHeaderItem(index).text()
        for index in range(view._cycle_detail_table.columnCount())
    ] == [
        "序号",
        "脚",
        "周期阶段图",
        "步态周期(s)",
        "支撑相(%)",
        "摆动相(%)",
        "步幅(cm)",
        "纳入统计",
        "统计说明",
    ]
    assert [
        view._treadmill_step_table.horizontalHeaderItem(index).text()
        for index in range(view._treadmill_step_table.columnCount())
    ] == [
        "序号",
        "脚",
        "步长(cm)",
        "触地时间(ms)",
        "纳入统计",
        "统计说明",
    ]


def test_running_step_details_include_flight_time(qtbot):
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(_step(0, "left"),),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    assert "腾空时间(ms)" in [
        view._treadmill_step_table.horizontalHeaderItem(index).text()
        for index in range(view._treadmill_step_table.columnCount())
    ]


def test_report_view_passes_treadmill_direction_to_replay_panel():
    _app()
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        report_config_snapshot={"direction": "Opposite side"},
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()

    view.load_report(report)

    assert view._replay_panel._channel._direction == "Opposite side"


def test_report_view_shows_replay_panel_for_treadmill_report(qtbot):
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()
    qtbot.addWidget(view)
    view.show()

    view.load_report(report)

    assert isinstance(view._replay_panel, FootprintReplayPanel)
    assert view._replay_panel.isVisible()
    assert view._replay_panel._timeline[0]["timestamp_s"] == 0.0
    assert len(
        view._replay_panel._channel._rail_marker_rects(
            rail_x=30.0, top=34.0, height=486.0
        )
    ) == 96


def test_report_view_clears_treadmill_dynamic_widgets_when_loading_jump_report(qtbot):
    treadmill_report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        metric_summaries={"contact_time_s": _summary()},
    )
    jump_report = JumpTestReport(
        touch_count=0,
        lift_count=0,
        air_times=(),
        contact_times=(),
        cycle_times=(),
        avg_jump_height=0.0,
        max_jump_height=0.0,
        avg_air_time=0.0,
        max_air_time=0.0,
        avg_contact_time=0.0,
        avg_cadence=None,
        finish_reason="manual",
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(treadmill_report)
    assert view._dynamic_widgets

    view.load_report(jump_report)

    assert view._dynamic_widgets == []


def test_treadmill_report_uses_overview_and_details_pages():
    _app()
    report = TreadmillGaitReport(
        finish_reason="time_up",
        touch_count=57,
        lift_count=56,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        metric_summaries={"contact_time_s": _summary()},
        left_right_results={"left": _summary(), "right": _summary()},
        report_config_snapshot={
            "treadmill_speed": 3.0,
            "direction": "Opposite side",
        },
        per_step_results=(
            _step(0, "left"),
            _step(1, "right"),
            _step(2, "left"),
        ),
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()

    view.load_report(report)

    assert view._tabs.count() == 3
    assert view._tabs.tabText(2) == "步态专项问答"
    assert view._tabs.tabText(0) == "概览"
    assert view._tabs.tabText(1) == "明细"
    assert view._overview_page.isAncestorOf(view._replay_panel)
    assert view._dynamic_widgets
    assert all(isinstance(widget, QTableWidget) for widget in view._dynamic_widgets)
    assert len(view._dynamic_widgets) == 3
    assert {
        widget.parent() for widget in view._dynamic_widgets
    } == {
        view._summary_page,
        view._cycle_page,
        view._step_page,
    }


def test_report_details_and_tables_use_dark_layered_theme(qtbot):
    cycle = _cycle()
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=3,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="manual_override",
        per_step_results=(_step(0, "left"),),
        gait_cycles=(cycle,),
        cycle_metric_summaries={"gait_cycle_s": _summary()},
        cycle_side_summaries={
            "left": {"gait_cycle_s": _summary()},
            "right": {"gait_cycle_s": _summary()},
        },
        metric_summaries={"contact_time_s": _summary()},
        left_right_results={"left_contact_time_s": _summary()},
    )
    view = ReportView()
    qtbot.addWidget(view)
    view.resize(1200, 720)
    view.load_report(report)
    view.show()
    view._tabs.setCurrentIndex(1)
    QApplication.processEvents()

    assert view._tabs.tabBar().objectName() == "ReportTabBar"
    assert view._details_page.objectName() == "ReportDetailsPage"
    assert view._detail_tabs.objectName() == "ReportDetailTabs"
    detail_tab_bar = view._detail_tabs.tabBar().grab().toImage()
    detail_tab_bar_background = detail_tab_bar.pixelColor(
        max(detail_tab_bar.width() - 10, 0),
        detail_tab_bar.height() // 2,
    )
    assert detail_tab_bar_background.lightness() < 80
    assert view._dynamic_widgets
    assert all(
        table.objectName() == "ReportDetailTable"
        for table in view._dynamic_widgets
        if isinstance(table, QTableWidget)
    )

    viewport = view._cycle_timeline_table.viewport()
    background = viewport.grab().toImage().pixelColor(
        max(viewport.width() - 5, 0),
        max(viewport.height() - 5, 0),
    )
    assert background.lightness() < 80


def test_report_replay_controls_do_not_fall_back_to_light_theme(qtbot):
    panel = FootprintReplayPanel()
    qtbot.addWidget(panel)
    panel.resize(620, 520)
    panel.show()
    QApplication.processEvents()

    assert panel._btn_play.objectName() == "ReplayButton"
    assert panel._slider.objectName() == "ReplaySlider"
    button_image = panel._btn_play.grab().toImage()
    button_background = button_image.pixelColor(
        10, button_image.height() // 2
    )
    assert button_background.lightness() < 80


def test_treadmill_report_overview_keeps_tables_off_the_replay_page():
    _app()
    report = TreadmillGaitReport(
        finish_reason="time_up",
        touch_count=57,
        lift_count=56,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        metric_summaries={"contact_time_s": _summary()},
        report_config_snapshot={
            "treadmill_speed": 3.0,
            "direction": "Opposite side",
        },
        per_step_results=tuple(_step(i, "left" if i % 2 == 0 else "right") for i in range(57)),
        visual_timeline=(FootprintVisualFrame(0.0, (0,) * 96),),
    )
    view = ReportView()
    view.resize(1600, 900)
    view.load_report(report)
    view.show()
    QApplication.processEvents()

    assert view._tabs.currentWidget() is view._overview_page
    assert view._overview_page.isAncestorOf(view._replay_panel)
    assert not any(view._overview_page.isAncestorOf(widget) for widget in view._dynamic_widgets)
    assert view._replay_panel.width() <= 780
    assert view._replay_panel.height() >= 520


def test_treadmill_report_shows_cycle_overview_timeline_and_details(qtbot):
    cycle = GaitCycleRecord(
        index=0,
        side="left",
        start_time_s=0.0,
        end_time_s=1.0,
        gait_cycle_s=1.0,
        stance_phase_s=0.6,
        stance_phase_percent=60.0,
        swing_phase_s=0.4,
        swing_phase_percent=40.0,
        step_time_s=0.5,
        single_support_s=0.4,
        single_support_percent=40.0,
        total_double_support_s=0.2,
        total_double_support_percent=20.0,
        load_response_s=0.1,
        load_response_percent=10.0,
        pre_swing_s=0.1,
        pre_swing_percent=10.0,
        total_flight_time_s=0.0,
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=3,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="manual_override",
        gait_cycles=(cycle,),
        cycle_metric_summaries={"gait_cycle_s": summarize((1.0,))},
        cycle_side_summaries={
            "left": {"gait_cycle_s": summarize((1.0,))},
            "right": {"gait_cycle_s": summarize(())},
        },
        report_config_snapshot={"treadmill_speed": 5.0, "direction": "Interface side"},
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)

    labels = [label for label, _, _ in _visible_card_data(view)]
    assert "平均步态周期" in labels
    assert "跑带速度" in labels
    assert view._cycle_timeline_table.rowCount() == 1
    assert view._cycle_detail_table.rowCount() == 1
    assert view._cycle_detail_table.horizontalHeaderItem(1).text() == "脚"


def test_treadmill_report_shows_chinese_statistics_notes(qtbot):
    cycle = _cycle(
        is_included_in_statistics=False,
        statistics_exclusion_reason="Contact time below minimum threshold",
        quality_flags=("running_overlap_above_tolerance",),
    )
    step = _step(0, "left")
    step = type(step)(
        **{
            **step.__dict__,
            "gap_between_feet_cm": 8.5,
            "quality_flags": ("gap_below_minimum",),
        }
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=3,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="manual_override",
        per_step_results=(step,),
        gait_cycles=(cycle,),
    )
    view = ReportView()
    qtbot.addWidget(view)

    view.load_report(report)
    view._cycle_filter.setCurrentIndex(
        view._cycle_filter.findData("excluded")
    )

    detail_note = _column_index(view._cycle_detail_table, "统计说明")
    step_note = _column_index(view._treadmill_step_table, "统计说明")
    assert (
        view._cycle_detail_table.item(0, detail_note).text()
        == "未纳入：触地时间低于最小阈值；质量提示：跑步时双脚重叠超过容差"
    )
    assert "两脚间距(cm)" not in [
        view._treadmill_step_table.horizontalHeaderItem(index).text()
        for index in range(view._treadmill_step_table.columnCount())
    ]
    assert (
        view._treadmill_step_table.item(0, step_note).text()
        == "质量提示：两脚间距低于最小阈值"
    )


def test_cycle_phase_bar_falls_back_when_detailed_stance_does_not_close():
    _app()
    cycle = _cycle(
        stance_phase_s=0.6,
        swing_phase_s=0.4,
        load_response_s=0.1,
        single_support_s=0.3,
        pre_swing_s=0.1,
    )

    bar = CyclePhaseBar(cycle)

    assert bar._segments() == [
        ("支撑相", 0.6),
        ("摆动相", 0.4),
    ]
    assert bar.toolTip() == "子阶段无法可靠拆分，按支撑相和摆动相绘制"


def test_stat_card_reduces_font_for_long_values():
    _app()
    card = StatCard("方向")

    card.set_value("Opposite side")

    assert "font-size: 18pt" in card._value.styleSheet()


def test_jump_report_cards_fit_without_overlapping_at_minimum_height(qtbot):
    report = JumpTestReport(
        touch_count=5,
        lift_count=5,
        air_times=(0.40, 0.42, 0.39),
        contact_times=(0.20, 0.21, 0.22),
        cycle_times=(0.60, 0.63, 0.61),
        avg_jump_height=0.198,
        max_jump_height=0.216,
        avg_air_time=0.403,
        max_air_time=0.420,
        avg_contact_time=0.210,
        avg_cadence=97.8,
        finish_reason="jump_count_reached",
        jump_heights=(0.196, 0.216, 0.190),
        cadences=(100.0, 95.2, 98.4),
        min_jump_height=0.190,
        std_jump_height=0.011,
        min_air_time=0.390,
        std_air_time=0.012,
        min_contact_time=0.200,
        max_contact_time=0.220,
        std_contact_time=0.008,
    )
    view = ReportView()
    qtbot.addWidget(view)
    view.resize(996, 720)
    view.load_report(report)
    view.show()
    QApplication.processEvents()

    visible_cards = [card for card in view._stat_cards if card.isVisible()]
    for column_x in {card.x() for card in visible_cards}:
        column = sorted(
            (card for card in visible_cards if card.x() == column_x),
            key=lambda card: card.y(),
        )
        for previous, current in zip(column, column[1:]):
            assert previous.geometry().bottom() < current.geometry().top()

    assert len(visible_cards) == 9
    assert not hasattr(view, "_stats_scroll")
    assert view._tabs.objectName() == "ReportTabs"
    assert view.btn_export.objectName() == "ReportSecondaryButton"
    assert view.btn_home.objectName() == "ReportPrimaryButton"


def _step(index: int, side: str):
    from config.treadmill_report import TreadmillStepResult

    return TreadmillStepResult(
        index=index,
        side=side,
        row_status="valid",
        is_event_valid=True,
        is_included_in_statistics=True,
        correction_source="none",
        contact_time_s=0.25,
        flight_time_s=0.1,
        step_time_s=0.7,
        step_length_cm=60.0,
        step_reference_cm=40.0,
        speed_m_s=0.833,
    )


def _summary():
    from config.treadmill_report import MetricSummary

    return MetricSummary(
        count=1,
        mean=0.25,
        min=0.25,
        max=0.25,
        std=0.0,
        cv_percent=0.0,
    )


def _cycle(**overrides):
    values = {
        "index": 0,
        "side": "left",
        "start_time_s": 0.0,
        "end_time_s": 1.0,
        "gait_cycle_s": 1.0,
        "stance_phase_s": 0.6,
        "stance_phase_percent": 60.0,
        "swing_phase_s": 0.4,
        "swing_phase_percent": 40.0,
        "step_time_s": 0.5,
        "single_support_s": 0.4,
        "single_support_percent": 40.0,
        "total_double_support_s": 0.2,
        "total_double_support_percent": 20.0,
        "load_response_s": 0.1,
        "load_response_percent": 10.0,
        "pre_swing_s": 0.1,
        "pre_swing_percent": 10.0,
        "total_flight_time_s": 0.0,
    }
    values.update(overrides)
    return GaitCycleRecord(**values)


def _column_index(table, label):
    return next(
        index
        for index in range(table.columnCount())
        if table.horizontalHeaderItem(index).text() == label
    )
