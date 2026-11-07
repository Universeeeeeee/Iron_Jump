"""Tests for treadmill report data models and MetricSummary."""

import math

import pytest

from config.treadmill_report import (
    GaitCycleRecord,
    TreadmillGaitReport,
    TreadmillRunningReport,
    TreadmillStepResult,
    summarize,
)
from engine.footprint_visualization import FootprintVisualFrame


def test_metric_summary_computes_population_std_and_cv():
    summary = summarize((1.0, 2.0, 3.0))

    assert summary.count == 3
    assert summary.mean == 2.0
    assert summary.min == 1.0
    assert summary.max == 3.0
    assert math.isclose(summary.std, math.sqrt(2 / 3))
    assert math.isclose(summary.cv_percent, math.sqrt(2 / 3) / 2.0 * 100)


def test_metric_summary_empty_values_return_none_metrics():
    summary = summarize(())

    assert summary.count == 0
    assert summary.mean is None
    assert summary.cv_percent is None


def test_treadmill_report_keeps_row_validity_and_config_snapshot():
    row = TreadmillStepResult(
        index=1,
        side="left",
        row_status="valid",
        is_event_valid=True,
        is_included_in_statistics=True,
        correction_source="none",
        contact_time_s=0.21,
        step_length_cm=72.0,
    )
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(row,),
        metric_summaries={"contact_time_s": summarize((0.21,))},
        report_config_snapshot={"treadmill_speed": 5.0},
    )

    assert report.test_type == "Treadmill Gait Test"
    assert report.per_step_results[0].is_included_in_statistics is True
    assert report.metric_summaries["contact_time_s"].mean == 0.21
    assert report.report_config_snapshot["treadmill_speed"] == 5.0
    assert row.gap_between_feet_cm is None
    assert row.quality_flags == ()


def test_running_report_uses_running_test_type():
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        per_step_results=(),
        metric_summaries={},
        report_config_snapshot={},
    )

    assert report.test_type == "Treadmill Running Test"


def test_treadmill_report_defaults_visual_timeline_to_empty_tuple():
    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
    )

    assert report.visual_timeline == ()


def test_treadmill_report_accepts_visual_timeline_frames():
    frame = FootprintVisualFrame(timestamp_s=0.0, contact_bits=(0,) * 96)
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=0,
        lift_count=0,
        resolved_starting_foot="unknown",
        starting_foot_source="unknown",
        visual_timeline=(frame,),
    )

    assert report.visual_timeline == (frame,)


def test_treadmill_metric_rows_include_validity_columns():

    from ui.views.report_view import _treadmill_metric_rows

    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(
            TreadmillStepResult(
                index=1,
                side="left",
                row_status="valid",
                is_event_valid=True,
                is_included_in_statistics=True,
                correction_source="none",
                contact_time_s=0.25,
                step_length_cm=70.0,
            ),
        ),
        metric_summaries={},
        report_config_snapshot={"treadmill_speed": 5.0},
    )

    rows = _treadmill_metric_rows(report)

    assert rows == [[
        1, "left", "valid", True, True, 0.25, "N/A",
        "N/A", 70.0, "N/A", "N/A", "N/A", "none", "N/A", "N/A", "N/A",
    ]]


def test_treadmill_metric_rows_match_export_header_order():

    from ui.views.report_view import TREADMILL_EXPORT_COLUMNS, _treadmill_metric_rows

    report = TreadmillGaitReport(
        finish_reason="manual",
        touch_count=1,
        lift_count=1,
        resolved_starting_foot="left",
        starting_foot_source="auto_first_contact",
        per_step_results=(
            TreadmillStepResult(
                index=1,
                side="left",
                row_status="valid",
                is_event_valid=True,
                is_included_in_statistics=True,
                correction_source="none",
                contact_time_s=0.25,
                flight_time_s=0.05,
                step_time_s=0.70,
                step_length_cm=70.0,
                gap_between_feet_cm=8.5,
                distance_cm=123.0,
                speed_m_s=1.5,
                step_reference_cm=42.0,
                quality_flags=(
                    "gap_below_minimum",
                    "running_overlap_above_tolerance",
                ),
            ),
        ),
        metric_summaries={},
        report_config_snapshot={"treadmill_speed": 5.0},
    )

    row = _treadmill_metric_rows(report)[0]
    values = dict(zip(TREADMILL_EXPORT_COLUMNS, row))

    assert len(row) == len(TREADMILL_EXPORT_COLUMNS)
    assert values["flight_time_s"] == 0.05
    assert values["step_time_s"] == 0.70
    assert values["step_length_cm"] == 70.0
    assert values["gap_between_feet_cm"] == 8.5
    assert values["quality_flags"] == "两脚间距低于最小阈值、跑步时双脚重叠超过容差"
    assert values["step_reference_cm"] == 42.0


def test_gait_cycle_export_includes_exclusion_reason_and_quality_flags():

    from ui.views.report_view import (
        GAIT_CYCLE_EXPORT_HEADERS,
        _gait_cycle_rows,
    )

    cycle = GaitCycleRecord(
        index=0,
        side="left",
        start_time_s=0.0,
        end_time_s=0.8,
        gait_cycle_s=0.8,
        stance_phase_s=0.4,
        stance_phase_percent=50.0,
        swing_phase_s=0.4,
        swing_phase_percent=50.0,
        step_time_s=0.4,
        single_support_s=0.4,
        single_support_percent=50.0,
        total_double_support_s=0.0,
        total_double_support_percent=0.0,
        load_response_s=0.0,
        load_response_percent=0.0,
        pre_swing_s=0.0,
        pre_swing_percent=0.0,
        total_flight_time_s=0.1,
        stride_length_cm=103.5,
        is_included_in_statistics=False,
        statistics_exclusion_reason="Contact time below minimum threshold",
        quality_flags=("gap_below_minimum",),
    )
    report = TreadmillRunningReport(
        finish_reason="manual",
        touch_count=2,
        lift_count=2,
        resolved_starting_foot="left",
        starting_foot_source="manual_override",
        gait_cycles=(cycle,),
    )

    row = _gait_cycle_rows(report)[0]
    values = dict(zip(GAIT_CYCLE_EXPORT_HEADERS, row))

    assert len(row) == len(GAIT_CYCLE_EXPORT_HEADERS)
    assert values["步幅(cm)"] == 103.5
    assert values["未纳入原因"] == "触地时间低于最小阈值"
    assert values["质量提示"] == "两脚间距低于最小阈值"
