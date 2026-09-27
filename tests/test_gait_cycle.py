import pytest

from engine.gait_cycle import GaitCycleBuilder


def test_walking_cycle_uses_same_side_boundaries_and_cross_side_events():
    builder = GaitCycleBuilder()

    builder.record_touch(-0.2, "right")
    builder.record_touch(0.0, "left")
    builder.record_lift(0.1, "right")
    builder.record_touch(0.6, "right")
    builder.record_lift(0.7, "left")
    builder.record_lift(0.8, "right")
    completed = builder.record_touch(1.0, "left")

    assert completed is not None
    assert completed.side == "left"
    assert completed.start_time_s == pytest.approx(0.0)
    assert completed.end_time_s == pytest.approx(1.0)
    assert completed.gait_cycle_s == pytest.approx(1.0)
    assert completed.stance_phase_s == pytest.approx(0.7)
    assert completed.swing_phase_s == pytest.approx(0.3)
    assert completed.step_time_s == pytest.approx(0.6)
    assert completed.load_response_s == pytest.approx(0.1)
    assert completed.pre_swing_s == pytest.approx(0.1)
    assert completed.total_double_support_s == pytest.approx(0.2)
    assert completed.single_support_s == pytest.approx(0.5)
    assert completed.stance_phase_percent == pytest.approx(70.0)
    assert completed.swing_phase_percent == pytest.approx(30.0)
    assert completed.total_double_support_percent == pytest.approx(20.0)


def test_running_cycle_reports_zero_overlap_and_total_flight_time():
    builder = GaitCycleBuilder()
    builder.record_clear(0.0)

    builder.record_touch(0.0, "left")
    builder.record_lift(0.2, "left")
    builder.record_touch(0.3, "right")
    builder.record_lift(0.5, "right")
    completed = builder.record_touch(0.6, "left")

    assert completed is not None
    assert completed.gait_cycle_s == pytest.approx(0.6)
    assert completed.stance_phase_s == pytest.approx(0.2)
    assert completed.swing_phase_s == pytest.approx(0.4)
    assert completed.total_double_support_s == pytest.approx(0.0)
    assert completed.load_response_s == pytest.approx(0.0)
    assert completed.pre_swing_s == pytest.approx(0.0)
    assert completed.total_flight_time_s == pytest.approx(0.2)


def test_current_state_is_temporary_and_boundary_partials_are_separate():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "left")
    builder.record_lift(0.2, "left")
    builder.record_touch(0.3, "right")

    snapshot = builder.make_live_snapshot(0.4)

    assert snapshot["support_state"] == "右脚单支撑"
    assert snapshot["current_cycles"]["left"]["phase"] == "摆动相"
    assert snapshot["current_cycles"]["right"]["phase"] == "支撑相"
    assert snapshot["completed_cycles"] == []

    partials = builder.build_boundary_partials(0.4)
    assert {partial.side for partial in partials} == {"left", "right"}
    assert builder.completed_cycles == ()


def test_raw_events_are_preserved_and_completed_records_are_immutable():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "left")
    builder.record_lift(0.4, "left")
    cycle = builder.record_touch(1.0, "left")

    assert [(event.kind, event.side) for event in builder.raw_events] == [
        ("touch", "left"),
        ("lift", "left"),
        ("touch", "left"),
    ]
    assert cycle is not None
    with pytest.raises((AttributeError, TypeError)):
        cycle.gait_cycle_s = 2.0


def test_cross_side_metrics_are_na_when_opposite_events_are_missing():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "left")
    builder.record_lift(0.4, "left")
    cycle = builder.record_touch(1.0, "left")

    assert cycle is not None
    assert cycle.gait_cycle_s == pytest.approx(1.0)
    assert cycle.stance_phase_s == pytest.approx(0.4)
    assert cycle.swing_phase_s == pytest.approx(0.6)
    assert cycle.step_time_s is None
    assert cycle.single_support_s is None
    assert cycle.total_double_support_s is None
    assert cycle.load_response_s is None
    assert cycle.pre_swing_s is None
    assert cycle.total_flight_time_s is None


def test_total_flight_is_na_when_same_side_lift_is_missing():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "left")
    cycle = builder.record_touch(1.0, "left")

    assert cycle is not None
    assert cycle.stance_phase_s is None
    assert cycle.swing_phase_s is None
    assert cycle.total_flight_time_s is None
    assert cycle.is_included_in_statistics is False


def test_continuous_double_support_is_not_counted_as_two_phases():
    builder = GaitCycleBuilder()

    builder.record_touch(-0.1, "right")
    builder.record_touch(0.0, "left")
    builder.record_lift(0.7, "left")
    builder.record_lift(0.8, "right")
    cycle = builder.record_touch(1.0, "left")

    assert cycle is not None
    assert cycle.total_double_support_s == pytest.approx(0.7)
    assert cycle.single_support_s == pytest.approx(0.0)
    assert cycle.load_response_s is None
    assert cycle.pre_swing_s is None


def test_live_snapshot_can_return_only_cycles_after_cursor():
    builder = GaitCycleBuilder()
    builder.record_touch(0.0, "left")
    builder.record_lift(0.4, "left")
    builder.record_touch(1.0, "left")

    first = builder.make_live_snapshot(1.0, completed_from_index=0)
    second = builder.make_live_snapshot(1.1, completed_from_index=1)

    assert first["completed_cycle_count"] == 1
    assert len(first["completed_cycles"]) == 1
    assert second["completed_cycle_count"] == 1
    assert second["completed_cycles"] == []


def test_unknown_side_events_are_preserved_but_never_form_official_cycle():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "unknown")
    builder.record_lift(0.4, "unknown")
    cycle = builder.record_touch(1.0, "unknown")

    assert cycle is None
    assert builder.completed_cycles == ()
    assert [event.kind for event in builder.raw_events] == [
        "touch", "lift", "touch",
    ]
    assert builder.make_live_snapshot(1.1)["support_state"] == "侧别未知接触"


def test_out_of_order_touch_is_preserved_without_rewinding_cycle_state():
    builder = GaitCycleBuilder()

    builder.record_touch(1.0, "left")
    builder.record_touch(0.5, "left")
    builder.record_lift(1.4, "left")
    cycle = builder.record_touch(2.0, "left")

    assert cycle is not None
    assert cycle.start_time_s == pytest.approx(1.0)
    assert cycle.gait_cycle_s == pytest.approx(1.0)
    assert len(builder.raw_events) == 4


def test_initial_and_final_boundary_partials_are_kept_outside_cycles():
    builder = GaitCycleBuilder()

    builder.record_touch(0.2, "left")
    builder.record_lift(0.6, "left")

    partials = builder.build_boundary_partials(0.9)

    assert builder.completed_cycles == ()
    assert [(partial.start_time_s, partial.snapshot_time_s, partial.phase) for partial in partials] == [
        (0.0, 0.2, "起始边界不完整"),
        (0.2, 0.9, "摆动相"),
    ]


def test_contact_exclusion_reason_and_quality_flags_propagate_to_cycle():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "left")
    builder.record_lift(
        0.4,
        "left",
        is_included_in_statistics=False,
        statistics_exclusion_reason="Contact time below minimum threshold",
        quality_flags=("gap_below_minimum",),
    )
    cycle = builder.record_touch(0.8, "left")

    assert cycle is not None
    assert cycle.is_included_in_statistics is False
    assert (
        cycle.statistics_exclusion_reason
        == "Contact time below minimum threshold"
    )
    assert cycle.quality_flags == ("gap_below_minimum", "opposite_contact_incomplete")


def test_repeated_touch_without_lift_has_explicit_cycle_exclusion_reason():
    builder = GaitCycleBuilder()

    builder.record_touch(0.0, "left")
    cycle = builder.record_touch(0.8, "left")

    assert cycle is not None
    assert cycle.is_included_in_statistics is False
    assert cycle.statistics_exclusion_reason == "Touch was replaced before lift"
