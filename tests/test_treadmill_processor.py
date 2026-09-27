"""
test_treadmill_processor.py — Tests for treadmill processor and accumulator
"""

import pytest
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from config.treadmill_report import (
    GaitCycleRecord,
    TreadmillRunningReport,
    TreadmillStepResult,
)
from engine.modes.treadmill_accumulator import TreadmillAccumulator
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from engine.modes.treadmill_processor import TreadmillProcessor
from engine.contact_tracker import ContactState, GaitStepEvent
from engine.modes.treadmill_running_accumulator import (
    RUNNING_OVERLAP_TOLERANCE_S,
    TreadmillRunningAccumulator,
)


def _emit_contact(
    processor, *, kind, contact_id, label, time_s, centroid_cm
):
    contact = ContactState(
        contact_id=contact_id,
        foot_label=label,
        touch_time=time_s if kind == "touch" else None,
        lift_time=time_s if kind == "lift" else None,
        centroid_at_touch=centroid_cm,
        latest_centroid=centroid_cm,
    )
    processor._handle_step_event(GaitStepEvent(kind, contact), time_s)


def _summary_cycle(index, side, gait_cycle_s, stride_length_cm=100.0):
    return GaitCycleRecord(
        index=index,
        side=side,
        start_time_s=float(index),
        end_time_s=float(index) + gait_cycle_s,
        gait_cycle_s=gait_cycle_s,
        stance_phase_s=gait_cycle_s * 0.6,
        stance_phase_percent=60.0,
        swing_phase_s=gait_cycle_s * 0.4,
        swing_phase_percent=40.0,
        step_time_s=gait_cycle_s / 2.0,
        single_support_s=gait_cycle_s * 0.4,
        single_support_percent=40.0,
        total_double_support_s=gait_cycle_s * 0.2,
        total_double_support_percent=20.0,
        load_response_s=gait_cycle_s * 0.1,
        load_response_percent=10.0,
        pre_swing_s=gait_cycle_s * 0.1,
        pre_swing_percent=10.0,
        total_flight_time_s=0.0,
        stride_length_cm=stride_length_cm,
    )


@pytest.mark.parametrize(
    ("direction", "start_centroid", "end_centroid", "expected_cm"),
    [
        ("Interface side", 40.0, 45.0, 105.0),
        ("Opposite side", 40.0, 35.0, 105.0),
    ],
)
def test_treadmill_stride_uses_belt_travel_and_same_side_displacement(
    direction, start_centroid, end_centroid, expected_cm
):
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction=direction,
        starting_foot_override="left",
        step_length_calculation="Heel-to-Heel",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _emit_contact(
        processor,
        kind="touch",
        contact_id=1,
        label="A",
        time_s=0.0,
        centroid_cm=start_centroid,
    )
    _emit_contact(
        processor,
        kind="lift",
        contact_id=1,
        label="A",
        time_s=0.4,
        centroid_cm=start_centroid,
    )
    _emit_contact(
        processor,
        kind="touch",
        contact_id=2,
        label="A",
        time_s=1.0,
        centroid_cm=end_centroid,
    )

    report = processor.build_report("manual", (), ())

    assert report.gait_cycles[0].stride_length_cm == pytest.approx(expected_cm)


def test_treadmill_stride_does_not_require_endpoint_lift():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    _emit_contact(
        processor,
        kind="touch",
        contact_id=1,
        label="A",
        time_s=0.0,
        centroid_cm=40.0,
    )
    _emit_contact(
        processor,
        kind="lift",
        contact_id=1,
        label="A",
        time_s=0.25,
        centroid_cm=40.0,
    )
    _emit_contact(
        processor,
        kind="touch",
        contact_id=2,
        label="A",
        time_s=0.8,
        centroid_cm=43.0,
    )

    report = processor.build_report("manual", (), ())

    assert report.gait_cycles[0].stride_length_cm == pytest.approx(83.0)
    assert len(report.per_step_results) == 1
    assert report.per_step_results[0].stride_length_cm is None


def test_non_positive_stride_is_omitted_and_flagged():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _emit_contact(
        processor,
        kind="touch",
        contact_id=1,
        label="A",
        time_s=0.0,
        centroid_cm=200.0,
    )
    _emit_contact(
        processor,
        kind="lift",
        contact_id=1,
        label="A",
        time_s=0.3,
        centroid_cm=200.0,
    )
    _emit_contact(
        processor,
        kind="touch",
        contact_id=2,
        label="A",
        time_s=1.0,
        centroid_cm=90.0,
    )

    cycle = processor.build_report("manual", (), ()).gait_cycles[0]

    assert cycle.stride_length_cm is None
    assert "non_positive_stride_length" in cycle.quality_flags


def test_stride_is_omitted_when_cycle_boundary_has_no_spatial_reference():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _emit_contact(
        processor,
        kind="touch",
        contact_id=1,
        label="A",
        time_s=0.0,
        centroid_cm=None,
    )
    _emit_contact(
        processor,
        kind="lift",
        contact_id=1,
        label="A",
        time_s=0.3,
        centroid_cm=None,
    )
    _emit_contact(
        processor,
        kind="touch",
        contact_id=2,
        label="A",
        time_s=1.0,
        centroid_cm=None,
    )

    cycle = processor.build_report("manual", (), ()).gait_cycles[0]

    assert cycle.stride_length_cm is None


def test_report_aggregates_stride_cadence_and_side_metrics():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    for index, (time_s, label, centroid) in enumerate(
        [
            (0.0, "A", 40.0),
            (0.5, "B", 42.0),
            (1.0, "A", 45.0),
            (1.5, "B", 47.0),
        ]
    ):
        _emit_contact(
            processor,
            kind="touch",
            contact_id=index,
            label=label,
            time_s=time_s,
            centroid_cm=centroid,
        )
        _emit_contact(
            processor,
            kind="lift",
            contact_id=index,
            label=label,
            time_s=time_s + 0.3,
            centroid_cm=centroid,
        )

    report = processor.build_report("manual", (), ())

    assert report.cycle_metric_summaries[
        "stride_length_cm"
    ].mean == pytest.approx(105.0)
    assert report.metric_summaries[
        "cadence_steps_per_min"
    ].mean == pytest.approx(120.0)
    assert report.left_right_results["left_step_length_cm"].count > 0
    assert report.left_right_results["right_contact_time_s"].count > 0


def test_cycle_asymmetry_requires_three_values_per_side():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    cycles = (
        _summary_cycle(0, "left", 1.0),
        _summary_cycle(1, "right", 1.1),
    )

    overall, by_side, asymmetry = processor._build_cycle_summaries(cycles)

    assert overall["gait_cycle_s"].count == 2
    assert by_side["left"]["gait_cycle_s"].count == 1
    assert "gait_cycle_s" not in asymmetry


def test_cycle_asymmetry_is_computed_with_three_values_per_side():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    cycles = tuple(
        _summary_cycle(index, side, duration)
        for index, (side, duration) in enumerate(
            [
                ("left", 1.0),
                ("right", 1.1),
                ("left", 1.0),
                ("right", 1.1),
                ("left", 1.0),
                ("right", 1.1),
            ]
        )
    )

    _, _, asymmetry = processor._build_cycle_summaries(cycles)

    assert asymmetry["gait_cycle_s"] == pytest.approx(
        0.1 / 1.05 * 100.0
    )


def test_accumulator_resolves_starting_foot_from_first_contact():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    acc = TreadmillAccumulator(config)

    acc.record_touch(time_s=0.10, side="right", heel_cm=20.0, toe_cm=45.0)

    assert acc.resolved_starting_foot == "right"
    assert acc.starting_foot_source == "auto_first_contact"


def test_processor_uses_configured_starting_foot_for_internal_labels():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        starting_foot_override="right",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    def event(kind, contact_id, label, time_s):
        contact = ContactState(
            contact_id=contact_id,
            foot_label=label,
            centroid_at_touch=40.0,
            latest_centroid=40.0,
        )
        processor._handle_step_event(GaitStepEvent(kind=kind, contact=contact), time_s)

    event("touch", 1, "A", 0.0)
    event("lift", 1, "A", 0.4)
    event("touch", 2, "B", 0.5)
    event("lift", 2, "B", 0.9)
    event("touch", 3, "A", 1.0)

    assert [raw.side for raw in processor._cycle_builder.raw_events] == [
        "right", "right", "left", "left", "right",
    ]
    assert processor._cycle_builder.completed_cycles[0].side == "right"


def test_processor_uses_detected_contact_boundaries_not_emit_delay():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    first = ContactState(
        contact_id=1,
        foot_label="A",
        touch_time=0.10,
        lift_time=0.40,
        centroid_at_touch=40.0,
        latest_centroid=40.0,
    )
    second = ContactState(
        contact_id=2,
        foot_label="A",
        touch_time=1.10,
        centroid_at_touch=40.0,
        latest_centroid=40.0,
    )

    processor._handle_step_event(GaitStepEvent("touch", first), rel_time=0.18)
    processor._handle_step_event(GaitStepEvent("lift", first), rel_time=0.50)
    processor._handle_step_event(GaitStepEvent("touch", second), rel_time=1.18)

    assert [event.time_s for event in processor._cycle_builder.raw_events] == [
        0.10, 0.40, 1.10,
    ]
    cycle = processor._cycle_builder.completed_cycles[0]
    assert cycle.gait_cycle_s == pytest.approx(1.0)
    assert cycle.stance_phase_s == pytest.approx(0.3)


def test_processor_report_preserves_cycles_raw_events_and_boundary_partials():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=8.0,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    processor._cycle_builder.record_touch(0.0, "left")
    processor._cycle_builder.record_lift(0.2, "left")
    processor._cycle_builder.record_touch(0.3, "right")
    processor._cycle_builder.record_lift(0.5, "right")
    processor._cycle_builder.record_touch(0.6, "left")
    processor._last_rel_time = 0.6

    report = processor.build_report("manual", (), ())

    assert len(report.raw_gait_events) == 5
    assert len(report.gait_cycles) == 1
    assert report.gait_cycles[0].side == "left"
    assert {partial.side for partial in report.boundary_partials} == {"left", "right"}


def test_processor_uses_gait_accumulator_for_overlapping_contacts():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
        min_contact_time=0,
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    def emit(kind, contact_id, label, time_s):
        contact = ContactState(
            contact_id=contact_id,
            foot_label=label,
            touch_time=time_s if kind == "touch" else None,
            lift_time=time_s if kind == "lift" else None,
            centroid_at_touch=40.0,
            latest_centroid=40.0,
        )
        processor._handle_step_event(GaitStepEvent(kind, contact), time_s)

    emit("touch", 1, "A", 0.0)
    emit("touch", 2, "B", 0.5)
    emit("lift", 1, "A", 0.8)
    emit("lift", 2, "B", 1.3)

    rows = processor._accumulator.rows
    assert [row.row_status for row in rows] == ["valid", "valid"]
    assert [row.contact_time_s for row in rows] == pytest.approx([0.8, 0.8])


def test_invalid_contact_excludes_its_completed_cycle_from_statistics():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        starting_foot_override="left",
        min_contact_time=600,
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    def emit(kind, contact_id, label, time_s):
        contact = ContactState(
            contact_id=contact_id,
            foot_label=label,
            touch_time=time_s if kind == "touch" else None,
            lift_time=time_s if kind == "lift" else None,
            centroid_at_touch=40.0,
            latest_centroid=40.0,
        )
        processor._handle_step_event(GaitStepEvent(kind, contact), time_s)

    emit("touch", 1, "A", 0.0)
    emit("lift", 1, "A", 0.1)
    emit("touch", 2, "B", 0.2)
    emit("lift", 2, "B", 0.3)
    emit("touch", 3, "A", 1.0)

    report = processor.build_report("manual", (), ())

    assert report.gait_cycles[0].is_included_in_statistics is False
    assert (
        report.gait_cycles[0].statistics_exclusion_reason
        == "Contact time below minimum threshold"
    )
    assert report.cycle_metric_summaries["gait_cycle_s"].count == 0


def test_repeated_touch_without_lift_keeps_cycle_with_explicit_reason():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    first = ContactState(
        contact_id=1,
        foot_label="A",
        touch_time=0.0,
        centroid_at_touch=40.0,
        latest_centroid=40.0,
    )
    second = ContactState(
        contact_id=2,
        foot_label="A",
        touch_time=0.8,
        centroid_at_touch=40.0,
        latest_centroid=40.0,
    )
    processor._handle_step_event(GaitStepEvent("touch", first), 0.0)
    processor._handle_step_event(GaitStepEvent("touch", second), 0.8)

    report = processor.build_report("manual", (), ())

    assert len(report.gait_cycles) == 1
    cycle = report.gait_cycles[0]
    assert cycle.gait_cycle_s == pytest.approx(0.8)
    assert cycle.is_included_in_statistics is False
    assert (
        cycle.statistics_exclusion_reason
        == "Touch was replaced before lift"
    )


def test_report_propagates_post_filter_exclusion_reason_to_cycle():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        automatic_data_filter=60,
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    processor._cycle_builder.record_touch(0.0, "left")
    processor._cycle_builder.record_lift(0.4, "left")
    processor._cycle_builder.record_touch(1.0, "left")
    processor._accumulator._rows.extend([
        TreadmillStepResult(
            index=0,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            time_s=0.4,
            contact_time_s=0.4,
            step_length_cm=120.0,
        ),
        TreadmillStepResult(
            index=1,
            side="right",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            time_s=0.9,
            contact_time_s=0.4,
            step_length_cm=50.0,
        ),
        TreadmillStepResult(
            index=2,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            time_s=1.4,
            contact_time_s=0.4,
            step_length_cm=50.0,
        ),
    ])

    report = processor.build_report("manual", (), ())

    cycle = report.gait_cycles[0]
    assert cycle.is_included_in_statistics is False
    assert (
        cycle.statistics_exclusion_reason
        == "Excluded by automatic_data_filter"
    )


def test_processor_live_snapshot_returns_completed_cycles_incrementally():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    builder = processor._cycle_builder
    builder.record_touch(0.0, "left")
    builder.record_lift(0.4, "left")
    builder.record_touch(1.0, "left")

    first = processor.make_status_snapshot(1.0)["gait_cycle_state"]
    second = processor.make_status_snapshot(1.1)["gait_cycle_state"]

    assert first["completed_cycle_count"] == 1
    assert len(first["completed_cycles"]) == 1
    assert second["completed_cycle_count"] == 1
    assert second["completed_cycles"] == []


def test_cycle_summaries_allow_different_side_counts_without_asymmetry():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")
    builder = processor._cycle_builder

    builder.record_touch(0.0, "left")
    builder.record_lift(0.4, "left")
    builder.record_touch(0.5, "right")
    builder.record_lift(0.9, "right")
    builder.record_touch(1.0, "left")
    builder.record_lift(1.4, "left")
    builder.record_touch(1.5, "right")
    builder.record_lift(1.9, "right")
    builder.record_touch(2.2, "left")
    processor._last_rel_time = 2.2

    report = processor.build_report("manual", (), ())

    left = report.cycle_side_summaries["left"]["gait_cycle_s"]
    right = report.cycle_side_summaries["right"]["gait_cycle_s"]
    assert left.count == 2
    assert right.count == 1
    assert left.mean == pytest.approx(1.1)
    assert right.mean == pytest.approx(1.0)
    assert "gait_cycle_s" not in report.cycle_asymmetry_percent
    live = processor.make_status_snapshot(2.2)
    assert live["gait_cycle_asymmetry_percent"]["gait_cycle_s"] == pytest.approx(
        0.1 / 1.05 * 100.0
    )


def test_accumulator_marks_short_contact_as_invalid_and_excluded():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_contact_time=100,
    )
    acc = TreadmillAccumulator(config)

    acc.record_touch(time_s=0.00, side="left", heel_cm=10.0, toe_cm=35.0)
    acc.record_lift(time_s=0.05, side="left")
    rows = acc.rows

    assert rows[0].row_status == "tc_not_valid"
    assert rows[0].is_event_valid is False
    assert rows[0].is_included_in_statistics is False
    assert rows[0].correction_source == "threshold_filter"


def test_gait_automatic_data_filter_excludes_outlier_from_statistics():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        automatic_data_filter=20,
    )
    acc = TreadmillAccumulator(config)

    acc.append_valid_row_for_test(side="left", contact_time_s=0.30, step_length_cm=60.0)
    acc.append_valid_row_for_test(side="right", contact_time_s=0.31, step_length_cm=62.0)
    acc.append_valid_row_for_test(side="left", contact_time_s=0.90, step_length_cm=130.0)
    acc.apply_automatic_data_filter()

    assert acc.rows[2].is_event_valid is True
    assert acc.rows[2].is_included_in_statistics is False
    assert acc.rows[2].correction_source == "automatic_data_filter"


def test_gait_automatic_data_filter_preserves_step_reference():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        automatic_data_filter=20,
    )
    acc = TreadmillAccumulator(config)
    acc._rows.extend([
        TreadmillStepResult(
            index=0,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=0.30,
            step_length_cm=60.0,
            step_reference_cm=35.0,
        ),
        TreadmillStepResult(
            index=1,
            side="right",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=0.31,
            step_length_cm=62.0,
            step_reference_cm=40.0,
        ),
        TreadmillStepResult(
            index=2,
            side="left",
            row_status="valid",
            is_event_valid=True,
            is_included_in_statistics=True,
            correction_source="none",
            contact_time_s=0.90,
            step_length_cm=130.0,
            step_reference_cm=37.0,
        ),
    ])

    acc.apply_automatic_data_filter()

    assert acc.rows[2].is_included_in_statistics is False
    assert acc.rows[2].step_reference_cm == 37.0


def test_treadmill_processor_builds_running_report_with_config_snapshot():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=10.0,
        direction="Interface side",
        foot_length_cm_snapshot=26.0,
        foot_length_source="manual",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")
    report = processor.build_report(reason="manual", export_frames=(), export_timestamps=())

    assert isinstance(report, TreadmillRunningReport)
    assert report.report_config_snapshot["treadmill_speed"] == 10.0
    assert report.report_config_snapshot["foot_length_cm_snapshot"] == 26.0


def test_processor_selects_gait_accumulator_for_gait_config():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )

    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    assert isinstance(processor._accumulator, TreadmillGaitAccumulator)


def test_processor_selects_running_accumulator_for_running_config():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=8.0,
        direction="Interface side",
    )

    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    assert isinstance(processor._accumulator, TreadmillRunningAccumulator)


def test_treadmill_distance_metrics_are_derived_from_belt_speed_and_time():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
    )
    acc = TreadmillAccumulator(config)

    row = acc.build_valid_row_for_test(
        side="left",
        elapsed_time_s=10.0,
        step_time_s=0.5,
        gait_cycle_s=1.0,
    )

    assert row.speed_m_s == 2.0
    assert row.distance_cm == 2000.0
    assert row.step_length_cm == 100.0
    assert row.stride_length_cm is None


def test_gait_accumulator_allows_double_support_without_no_step():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.5, "right", 15.0, 40.0)
    acc.record_lift(0.8, "left")
    acc.record_lift(1.3, "right")

    rows = acc.rows
    assert len(rows) == 2
    assert [row.row_status for row in rows] == ["valid", "valid"]
    assert rows[0].contact_time_s == pytest.approx(0.8)
    assert rows[1].contact_time_s == pytest.approx(0.8)
    assert rows[0].double_support_s == pytest.approx(0.3)
    assert rows[1].double_support_s == pytest.approx(0.3)
    assert rows[1].step_time_s == pytest.approx(0.5)
    assert rows[1].step_length_cm == pytest.approx(50.0)
    assert rows[0].flight_time_s is None
    assert rows[1].flight_time_s is None


def test_gait_accumulator_filters_step_length_below_minimum():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        min_step_length=60.0,
    )
    acc = TreadmillGaitAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    acc.record_touch(0.5, "right", 15.0, 40.0)
    acc.record_lift(0.8, "right")

    row = acc.rows[1]
    assert row.step_length_cm == pytest.approx(50.0)
    assert row.is_event_valid is True
    assert row.is_included_in_statistics is False
    assert row.correction_source == "threshold_filter"
    assert row.statistics_exclusion_reason == "Step length below minimum threshold"


# ---- P1-4 tests: flight time thresholds, step_time semantics, step_length_calculation ----


def test_flight_time_min_threshold_triggers_tf_not_valid():
    """Row with flight_time below min_flight_time should be tf_not_valid."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_flight_time=50,
    )
    acc = TreadmillAccumulator(cfg)
    # First step: touch, lift, touch again — flight between first lift and second touch
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")        # row 0: valid
    acc.record_touch(0.32, "right", 15.0, 40.0)  # 20 ms flight (< 50 ms min)
    acc.record_lift(0.62, "right")      # row 1: should be tf_not_valid
    assert len(acc.rows) == 2
    r1 = acc.rows[1]
    assert r1.row_status == "tf_not_valid", f"Expected tf_not_valid, got {r1.row_status}"
    assert r1.is_event_valid is False
    assert r1.is_included_in_statistics is False
    assert r1.correction_source == "threshold_filter"
    # Even invalid rows retain timing fields
    assert r1.flight_time_s is not None
    assert r1.step_time_s is not None
    assert r1.contact_time_s is not None


def test_flight_time_max_threshold_triggers_tf_not_valid():
    """Row with flight_time above max_flight_time should be tf_not_valid."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        max_flight_time=200,
    )
    acc = TreadmillAccumulator(cfg)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    acc.record_touch(0.60, "right", 15.0, 40.0)  # 300 ms flight (> 200 ms max)
    acc.record_lift(0.90, "right")
    assert len(acc.rows) == 2
    r1 = acc.rows[1]
    assert r1.row_status == "tf_not_valid", f"Expected tf_not_valid, got {r1.row_status}"


def test_flight_time_threshold_disabled_when_zero():
    """min_flight_time=0 or max_flight_time=0 means threshold is disabled."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_flight_time=0,   # disabled
    )
    acc = TreadmillAccumulator(cfg)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    acc.record_touch(0.31, "right", 15.0, 40.0)  # 10 ms flight, but min=0 so OK
    acc.record_lift(0.61, "right")
    assert acc.rows[1].row_status != "tf_not_valid"
    assert acc.rows[1].is_event_valid is True


def test_first_step_skips_flight_time_check():
    """First step (no previous row so flight_time_s is None) must not trigger tf_not_valid."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
        min_flight_time=1,  # non-zero, but first step has no flight_time
    )
    acc = TreadmillAccumulator(cfg)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.3, "left")
    # Only one row — flight_time_s was never computed
    assert len(acc.rows) == 1
    assert acc.rows[0].row_status == "valid"
    assert acc.rows[0].flight_time_s is None


def test_inter_touch_step_time_not_contact_time():
    """step_time_s must be the inter-touch interval, not contact_time_s."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    acc = TreadmillAccumulator(cfg)
    # Step 1: touch at 0.0, lift at 0.30 (contact = 0.30 s)
    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.30, "left")
    # Step 2: touch at 0.80, lift at 1.10 (contact = 0.30 s, inter-touch = 0.80 s)
    acc.record_touch(0.80, "right", 15.0, 40.0)
    acc.record_lift(1.10, "right")

    r0 = acc.rows[0]
    # First row: no previous touch, step_time_s stays None
    assert r0.step_time_s is None, f"First row step_time should be None"

    r1 = acc.rows[1]
    assert r1.contact_time_s == pytest.approx(0.30, abs=0.01)
    # step_time must be inter-touch: 0.80 - 0.0 = 0.80, NOT contact_time
    assert r1.step_time_s == pytest.approx(0.80, abs=0.01), (
        f"step_time_s should be inter-touch (0.80), got {r1.step_time_s}"
    )


def test_step_length_calculation_does_not_alter_formula():
    """step_length_calculation selects reference point only, step_length_cm
    formula is always treadmill_speed * inter-touch step_time."""
    cfg_tip = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Tip-to-Tip",
    )
    acc_tip = TreadmillAccumulator(cfg_tip)

    cfg_heel = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Heel-to-Heel",
    )
    acc_heel = TreadmillAccumulator(cfg_heel)

    # Same touch/lift sequence for both
    belt_speed_ms = 7.2 / 3.6  # = 2.0 m/s
    for acc in (acc_tip, acc_heel):
        acc.record_touch(0.0, "left", 10.0, 35.0)
        acc.record_lift(0.30, "left")
        acc.record_touch(0.80, "right", 15.0, 40.0)
        acc.record_lift(1.10, "right")

    r_tip = acc_tip.rows[1]
    r_heel = acc_heel.rows[1]

    # step_length_cm formula is belt_speed * inter-touch step_time
    expected_step_length = belt_speed_ms * 0.80 * 100.0  # = 160 cm

    assert r_tip.step_length_cm == pytest.approx(expected_step_length, abs=0.01)
    assert r_heel.step_length_cm == pytest.approx(expected_step_length, abs=0.01)
    # Both produce identical step_length_cm
    assert abs(r_tip.step_length_cm - r_heel.step_length_cm) < 0.001


def test_step_length_calculation_records_toe_reference():
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Tip-to-Tip",
    )
    acc = TreadmillAccumulator(cfg)

    acc.record_touch(0.0, "left", heel_cm=10.0, toe_cm=35.0)
    acc.record_lift(0.30, "left")
    acc.record_touch(0.80, "right", heel_cm=15.0, toe_cm=40.0)
    acc.record_lift(1.10, "right")

    assert acc.rows[1].step_reference_cm == 40.0


def test_step_length_calculation_records_heel_reference():
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Heel-to-Heel",
    )
    acc = TreadmillAccumulator(cfg)

    acc.record_touch(0.0, "left", heel_cm=10.0, toe_cm=35.0)
    acc.record_lift(0.30, "left")
    acc.record_touch(0.80, "right", heel_cm=15.0, toe_cm=40.0)
    acc.record_lift(1.10, "right")

    assert acc.rows[1].step_reference_cm == 15.0


def test_step_reference_does_not_change_speed_time_step_length():
    cfg_tip = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Tip-to-Tip",
    )
    cfg_heel = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        step_length_calculation="Heel-to-Heel",
    )

    rows = []
    for cfg in (cfg_tip, cfg_heel):
        acc = TreadmillAccumulator(cfg)
        acc.record_touch(0.0, "left", heel_cm=10.0, toe_cm=35.0)
        acc.record_lift(0.30, "left")
        acc.record_touch(0.80, "right", heel_cm=15.0, toe_cm=40.0)
        acc.record_lift(1.10, "right")
        rows.append(acc.rows[1])

    assert rows[0].step_reference_cm != rows[1].step_reference_cm
    assert rows[0].step_time_s == pytest.approx(rows[1].step_time_s)
    assert rows[0].step_length_cm == pytest.approx(rows[1].step_length_cm)


def test_running_accumulator_records_airborne_flight_time():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.45, "right", 15.0, 40.0)
    acc.record_lift(0.70, "right")

    row = acc.rows[1]
    assert row.flight_time_s == pytest.approx(0.20)
    assert row.step_time_s == pytest.approx(0.45)
    assert row.step_length_cm == pytest.approx(90.0)


def test_running_accumulator_allows_short_overlap():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)
    overlap = RUNNING_OVERLAP_TOLERANCE_S / 2

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.25 - overlap, "right", 15.0, 40.0)
    acc.record_lift(0.25, "left")
    acc.record_lift(0.50, "right")

    assert acc.rows[1].is_event_valid is True
    assert acc.rows[1].is_included_in_statistics is True
    assert acc.rows[1].statistics_exclusion_reason is None


def test_running_accumulator_keeps_long_overlap_as_quality_flag():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)
    overlap = RUNNING_OVERLAP_TOLERANCE_S + 0.02

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.25 - overlap, "right", 15.0, 40.0)
    acc.record_lift(0.25, "left")
    acc.record_lift(0.50, "right")

    assert acc.rows[1].is_event_valid is True
    assert acc.rows[1].is_included_in_statistics is True
    assert acc.rows[1].correction_source == "none"
    assert acc.rows[1].statistics_exclusion_reason is None
    assert acc.rows[1].quality_flags == ("running_overlap_above_tolerance",)


def test_running_accumulator_can_record_overlap_and_gap_quality_flags_together():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=20.0,
    )
    acc = TreadmillRunningAccumulator(config)
    overlap = RUNNING_OVERLAP_TOLERANCE_S + 0.02

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_touch(0.25 - overlap, "right", 15.0, 40.0)
    acc.record_lift(0.25, "left")
    acc.record_lift(0.50, "right")

    row = acc.rows[1]
    assert row.gap_between_feet_cm == pytest.approx(16.0)
    assert row.is_included_in_statistics is True
    assert row.quality_flags == (
        "running_overlap_above_tolerance",
        "gap_below_minimum",
    )


def test_running_accumulator_keeps_small_gap_as_quality_flag():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=80.0,
        step_length_calculation="Tip-to-Tip",
    )
    acc = TreadmillRunningAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 35.0)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.45, "right", 15.0, 45.0)
    acc.record_lift(0.70, "right")

    row = acc.rows[1]
    assert row.step_reference_cm == 45.0
    assert row.gap_between_feet_cm == pytest.approx(70.0)
    assert row.is_event_valid is True
    assert row.is_included_in_statistics is True
    assert row.correction_source == "none"
    assert row.statistics_exclusion_reason is None
    assert row.quality_flags == ("gap_below_minimum",)


@pytest.mark.parametrize(
    (
        "direction",
        "previous_heel",
        "previous_toe",
        "current_heel",
        "current_toe",
        "expected_gap_cm",
    ),
    [
        ("Interface side", 10.0, 35.0, 15.0, 40.0, 70.0),
        ("Opposite side", 50.0, 35.0, 30.0, 15.0, 95.0),
    ],
)
def test_running_gap_uses_previous_toe_current_heel_and_belt_compensation(
    direction,
    previous_heel,
    previous_toe,
    current_heel,
    current_toe,
    expected_gap_cm,
):
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction=direction,
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)

    acc.record_touch(0.0, "left", previous_heel, previous_toe)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.45, "right", current_heel, current_toe)
    acc.record_lift(0.70, "right")

    assert acc.rows[0].gap_between_feet_cm is None
    assert acc.rows[1].gap_between_feet_cm == pytest.approx(expected_gap_cm)


def test_running_gap_clamps_negative_signed_distance_to_zero():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(config)

    acc.record_touch(0.0, "left", 10.0, 100.0)
    acc.record_lift(0.05, "left")
    acc.record_touch(0.10, "right", 20.0, 30.0)
    acc.record_lift(0.15, "right")

    assert acc.rows[1].gap_between_feet_cm == pytest.approx(0.0)


def test_running_gap_does_not_depend_on_step_length_reference():
    rows = []
    for step_length_calculation in ("Tip-to-Tip", "Heel-to-Heel"):
        config = TreadmillRunningConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=7.2,
            direction="Interface side",
            min_gap_between_feet=1.0,
            step_length_calculation=step_length_calculation,
        )
        acc = TreadmillRunningAccumulator(config)
        acc.record_touch(0.0, "left", 10.0, 35.0)
        acc.record_lift(0.25, "left")
        acc.record_touch(0.45, "right", 15.0, 45.0)
        acc.record_lift(0.70, "right")
        rows.append(acc.rows[1])

    assert rows[0].step_reference_cm != rows[1].step_reference_cm
    assert rows[0].gap_between_feet_cm == pytest.approx(70.0)
    assert rows[1].gap_between_feet_cm == pytest.approx(70.0)


def test_running_normal_sequence_does_not_exclude_every_row_after_first():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=10.0,
    )
    acc = TreadmillRunningAccumulator(config)

    for index in range(6):
        touch_s = index * 0.4
        side = "left" if index % 2 == 0 else "right"
        acc.record_touch(touch_s, side, 10.0, 40.0)
        acc.record_lift(touch_s + 0.25, side)

    assert all(row.is_included_in_statistics for row in acc.rows)
    assert all(row.statistics_exclusion_reason is None for row in acc.rows)


def test_running_processor_report_includes_all_complete_normal_cycles():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=10.0,
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    for index in range(5):
        side_label = "A" if index % 2 == 0 else "B"
        touch_s = index * 0.4
        contact = ContactState(
            contact_id=index,
            foot_label=side_label,
            touch_time=touch_s,
            lift_time=touch_s + 0.25,
            centroid_at_touch=40.0,
            latest_centroid=40.0,
        )
        processor._handle_step_event(GaitStepEvent("touch", contact), touch_s)
        processor._handle_step_event(
            GaitStepEvent("lift", contact), touch_s + 0.25
        )

    report = processor.build_report("manual", (), ())

    assert len(report.gait_cycles) == 3
    assert all(cycle.is_included_in_statistics for cycle in report.gait_cycles)
    assert report.cycle_metric_summaries["gait_cycle_s"].count == 3


def test_running_processor_propagates_step_quality_flags_to_cycle():
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_gap_between_feet=20.0,
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    events = [
        ("touch", 1, "A", 0.00, None),
        ("touch", 2, "B", 0.18, None),
        ("lift", 1, "A", 0.25, 0.25),
        ("lift", 2, "B", 0.50, 0.50),
        ("touch", 3, "A", 0.60, None),
        ("touch", 4, "B", 0.80, None),
    ]
    for kind, contact_id, label, time_s, lift_time in events:
        contact = ContactState(
            contact_id=contact_id,
            foot_label=label,
            touch_time=time_s if kind == "touch" else None,
            lift_time=lift_time,
            centroid_at_touch=40.0,
            latest_centroid=40.0,
        )
        processor._handle_step_event(GaitStepEvent(kind, contact), time_s)

    report = processor.build_report("manual", (), ())
    right_cycle = next(
        cycle for cycle in report.gait_cycles if cycle.side == "right"
    )

    assert right_cycle.is_included_in_statistics is True
    assert right_cycle.statistics_exclusion_reason is None
    assert right_cycle.quality_flags == (
        "running_overlap_above_tolerance",
        "gap_below_minimum",
    )


@pytest.mark.parametrize(
    ("contact_time_s", "expected_included", "expected_reason"),
    [
        (0.030, False, "Contact time below minimum threshold"),
        (0.061, True, None),
    ],
)
def test_running_processor_keeps_short_complete_cycle_with_threshold_diagnosis(
    contact_time_s,
    expected_included,
    expected_reason,
):
    config = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,
        direction="Interface side",
        min_contact_time=60,
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_running")

    first = ContactState(
        contact_id=1,
        foot_label="A",
        touch_time=0.0,
        lift_time=contact_time_s,
        centroid_at_touch=40.0,
        latest_centroid=40.0,
    )
    second = ContactState(
        contact_id=2,
        foot_label="A",
        touch_time=0.067,
        centroid_at_touch=40.0,
        latest_centroid=40.0,
    )
    processor._handle_step_event(GaitStepEvent("touch", first), 0.0)
    processor._handle_step_event(
        GaitStepEvent("lift", first), contact_time_s
    )
    processor._handle_step_event(GaitStepEvent("touch", second), 0.067)

    report = processor.build_report("manual", (), ())

    assert len(report.gait_cycles) == 1
    cycle = report.gait_cycles[0]
    assert cycle.gait_cycle_s == pytest.approx(0.067)
    assert cycle.is_included_in_statistics is expected_included
    assert cycle.statistics_exclusion_reason == expected_reason


def test_treadmill_processor_records_fixed_cadence_visual_timeline():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    processor.process_raw_frame([0] * 96, rel_time=0.00, abs_time=0.00)
    processor.process_raw_frame([1] * 96, rel_time=0.01, abs_time=0.01)
    processor.process_raw_frame([1] * 96, rel_time=0.05, abs_time=0.05)
    report = processor.build_report(
        reason="manual",
        export_frames=(),
        export_timestamps=(),
    )

    assert [frame.timestamp_s for frame in report.visual_timeline] == [0.0, 0.05]
    assert report.visual_timeline[1].contact_bits == tuple([1] * 96)


def test_treadmill_processor_pop_visual_frames_returns_pending_once():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=5.0,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    processor.process_raw_frame([0] * 96, rel_time=0.00, abs_time=0.00)

    first = processor.pop_visual_frames()
    second = processor.pop_visual_frames()

    assert len(first) == 1
    assert second == ()


def _contact_bits(start: int, end: int) -> list[int]:
    bits = [0] * 96
    for idx in range(start, end + 1):
        bits[idx] = 1
    return bits


def _feed_frames(
    processor: TreadmillProcessor,
    bits: list[int],
    start_s: float,
    count: int,
    dt_s: float = 0.01,
) -> None:
    for offset in range(count):
        t = start_s + offset * dt_s
        processor.process_raw_frame(bits, rel_time=t, abs_time=t)


@pytest.mark.parametrize(
    ("config_type", "mode_name"),
    [
        (TreadmillGaitConfig, "treadmill_gait"),
        (TreadmillRunningConfig, "treadmill_running"),
    ],
)
def test_treadmill_ignores_startup_boundary_and_preserves_unknown_side(
    config_type, mode_name
):
    config = config_type(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    processor = TreadmillProcessor(config, mode_name=mode_name)
    initial_bits = _contact_bits(10, 25)
    initial_and_new_bits = initial_bits.copy()
    initial_and_new_bits[40:56] = [1] * 16

    _feed_frames(processor, initial_bits, start_s=0.00, count=12)
    events = []
    for offset in range(8):
        time_s = 0.20 + offset * 0.01
        events.extend(
            processor.process_raw_frame(
                initial_and_new_bits,
                rel_time=time_s,
                abs_time=time_s,
            )
        )

    touches = [event for event in events if event.kind == "touch"]
    assert len(touches) == 1
    assert touches[0].contact.foot_label == "A"
    assert processor._contact_side[touches[0].contact.contact_id] == "unknown"
    assert processor.make_status_snapshot(0.28)["touch_count"] == 1


def test_treadmill_processor_makes_live_status_snapshot_from_rows():
    config = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
        starting_foot_override="left",
    )
    processor = TreadmillProcessor(config, mode_name="treadmill_gait")

    _feed_frames(processor, [0] * 96, start_s=0.00, count=10)
    _feed_frames(processor, _contact_bits(10, 25), start_s=0.60, count=8)
    _feed_frames(processor, [0] * 96, start_s=0.70, count=20)
    _feed_frames(processor, _contact_bits(36, 51), start_s=1.30, count=8)
    _feed_frames(processor, [0] * 96, start_s=1.40, count=20)

    snapshot = processor.make_status_snapshot(rel_time=1.60)

    assert snapshot["touch_count"] == 2
    assert snapshot["lift_count"] == 2
    assert snapshot["stride_count"] == 1
    assert snapshot["latest_stride"] == pytest.approx(70.0, abs=0.01)
    assert snapshot["velocity_count"] == 2
    assert snapshot["velocity_sum"] / snapshot["velocity_count"] == pytest.approx(100.0)
    assert snapshot["latest_extra_metrics"]["imbalance_index"] == pytest.approx(0.0)


# ============================================================
# Spatial correction tests — per-step speed from foot placement
# ============================================================


def test_spatial_correction_produces_varying_speed():
    """After stagger baseline is established, drift in foot placement
    produces per-step speed values that differ from belt speed."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,  # 1.0 m/s belt
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(cfg)

    # Establish stagger baseline: two normal steps
    acc.record_touch(0.0, "left", heel_cm=25.0, toe_cm=40.0)
    acc.record_lift(0.30, "left")
    acc.record_touch(0.50, "right", heel_cm=45.0, toe_cm=60.0)
    acc.record_lift(0.80, "right")

    # Step 3: left foot with forward drift (+3 cm)
    acc.record_touch(1.10, "left", heel_cm=28.0, toe_cm=43.0)
    acc.record_lift(1.30, "left")

    # Step 4: right foot with backward drift (-2 cm)
    acc.record_touch(1.60, "right", heel_cm=43.0, toe_cm=58.0)
    acc.record_lift(1.80, "right")

    speeds = [r.speed_m_s for r in acc.rows if r.speed_m_s is not None]
    # Should have at least 3 valid speeds (steps 0,1,2,3 → 4 speeds)
    assert len(speeds) >= 3
    # Speeds should not all be identical
    unique = len(set(round(s, 4) for s in speeds))
    assert unique > 1, f"Expected varying speeds, got all {speeds[0]:.4f}"


def test_spatial_correction_first_step_uses_belt_speed():
    """The first step has no prior reference, so speed = belt speed."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,  # 2.0 m/s
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(cfg)

    acc.record_touch(0.0, "left", heel_cm=25.0, toe_cm=40.0)
    acc.record_lift(0.30, "left")

    row = acc.rows[0]
    # First step: step_time is None (no prior touch), speed = belt
    assert row.speed_m_s == 2.0
    assert row.step_length_cm is None  # no step_time → no step_length


def test_spatial_correction_respects_opposite_direction():
    """Opposite-side direction inverts the spatial correction sign."""
    cfg = TreadmillRunningConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=7.2,  # 2.0 m/s
        direction="Opposite side",
        min_gap_between_feet=1.0,
    )
    acc = TreadmillRunningAccumulator(cfg)

    # Establish baseline
    acc.record_touch(0.0, "left", heel_cm=50.0, toe_cm=35.0)
    acc.record_lift(0.15, "left")
    acc.record_touch(0.35, "right", heel_cm=30.0, toe_cm=15.0)
    acc.record_lift(0.50, "right")

    # Step 3: left foot with forward drift
    # Opposite side: forward = lower LED index (runner moves away from interface)
    acc.record_touch(0.70, "left", heel_cm=48.0, toe_cm=33.0)
    acc.record_lift(0.85, "left")

    # Step 4: right foot
    acc.record_touch(1.05, "right", heel_cm=32.0, toe_cm=17.0)
    acc.record_lift(1.20, "right")

    speeds = [r.speed_m_s for r in acc.rows if r.speed_m_s is not None]
    unique = len(set(round(s, 4) for s in speeds))
    assert unique > 1, f"Opposite direction should still produce varying speeds"


def test_spatial_correction_preserves_step_length_ordering():
    """Steps with forward drift should have larger step_length than
    steps with backward drift, relative to the stagger baseline."""
    cfg = TreadmillGaitConfig(
        stop_type="Software command",
        test_length=None,
        treadmill_speed=3.6,
        direction="Interface side",
    )
    acc = TreadmillGaitAccumulator(cfg)

    # Two baseline steps (establish stagger for both transition directions)
    acc.record_touch(0.0, "left", heel_cm=20.0, toe_cm=35.0)
    acc.record_lift(0.25, "left")
    acc.record_touch(0.50, "right", heel_cm=40.0, toe_cm=55.0)
    acc.record_lift(0.75, "right")
    # Second occurrence of each transition to establish stagger EWMA
    acc.record_touch(1.00, "left", heel_cm=20.0, toe_cm=35.0)
    acc.record_lift(1.25, "left")
    acc.record_touch(1.50, "right", heel_cm=40.0, toe_cm=55.0)
    acc.record_lift(1.75, "right")

    # Now introduce drift: forward on left (+4 cm), backward on right (-3 cm)
    acc.record_touch(2.00, "left", heel_cm=24.0, toe_cm=39.0)
    acc.record_lift(2.25, "left")
    acc.record_touch(2.50, "right", heel_cm=37.0, toe_cm=52.0)
    acc.record_lift(2.75, "right")

    belt_speed = 3.6 / 3.6  # 1.0 m/s
    drift_steps = [r for r in acc.rows if r.index >= 4 and r.step_time_s is not None]
    for r in drift_steps:
        belt_dist = belt_speed * r.step_time_s * 100.0
        assert r.step_length_cm != pytest.approx(belt_dist, abs=0.01), (
            f"Step {r.index}: expected spatial correction, "
            f"got step_length={r.step_length_cm} == belt_dist={belt_dist}"
        )
