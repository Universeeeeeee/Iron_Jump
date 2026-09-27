"""OptoGait manual behavior plus raw-frame evidence regression cases."""

from dataclasses import replace

import pytest

from config.treadmill_config import TreadmillGaitConfig
from engine.gait_cycle import GaitCycleBuilder
from engine.modes.treadmill_processor import TreadmillProcessor


def processor(**kwargs):
    config = TreadmillGaitConfig(
        stop_type="Software command", test_length=None,
        starting_foot_override="left",
    )
    return TreadmillProcessor(replace(config, **kwargs), "treadmill_gait")


def replay(p, contacts, end=1400):
    events = []
    for sample in range(end):
        bits = [0] * 96
        for begin, finish, lo, hi in contacts:
            if begin <= sample < finish:
                bits[lo:hi] = [1] * (hi - lo)
        events.extend(p.process_raw_frame(bits, sample / 1000, sample / 1000))
    return events


def test_three_observed_frames_cannot_become_eight_via_retained_tracks():
    p = processor(min_contact_time=0)
    assert replay(p, [(100, 103, 20, 32)], end=150) == []


def test_lift_is_first_clear_sample_not_track_retention_deadline():
    events = replay(processor(), [(100, 201, 20, 32)], end=250)
    assert [e.kind for e in events] == ["touch", "lift"]
    assert events[0].contact.touch_time == pytest.approx(.100)
    assert events[1].contact.lift_time == pytest.approx(.201)


def test_gaitr_threshold_and_foot_size_have_separate_roles():
    contacts = [(100, 110, 20, 21), (110, 120, 20, 23),
                (120, 220, 20, 32), (220, 230, 20, 23), (230, 240, 20, 21)]
    plain = replay(processor(), contacts)
    filtered = replay(processor(filter_gaitr_in=3, filter_gaitr_out=3), contacts)
    assert plain[0].contact.touch_time == pytest.approx(.100)
    assert plain[1].contact.lift_time == pytest.approx(.240)
    assert filtered[0].contact.touch_time == pytest.approx(.120)
    assert filtered[1].contact.lift_time == pytest.approx(.220)
    assert replay(processor(min_foot_length=40), contacts) == []


def test_short_rejected_contact_does_not_advance_foot_identity():
    p = processor()
    events = replay(p, [(100, 103, 20, 32), (300, 450, 50, 62)])
    touches = [e for e in events if e.kind == "touch"]
    assert len(touches) == 1
    assert p._contact_side[touches[0].contact.contact_id] == "left"


def test_unconfirmed_starting_foot_never_defaults_to_left():
    p = processor(starting_foot_override=None)
    replay(p, [(100, 401, 20, 32), (500, 801, 50, 62), (1000, 1301, 20, 32)])
    report = p.build_report("manual", (), ())
    assert report.gait_cycles == ()
    assert len(report.per_step_results) == 3
    assert all(r.side == "unknown" for r in report.per_step_results)
    assert report.resolved_starting_foot == "unknown"


def test_merge_does_not_manufacture_a_lift_or_keep_side_identity():
    p = processor()
    events = replay(p, [(100, 250, 20, 32), (200, 250, 36, 48),
                        (250, 400, 25, 48), (600, 800, 20, 32)])
    assert not any(e.kind == "lift" and .250 <= e.contact.lift_time < .400 for e in events)
    later = [e for e in events if e.kind == "touch" and e.contact.touch_time >= .6]
    assert later and p._contact_side[later[0].contact.contact_id] == "unknown"
    assert p.build_report("manual", (), ()).report_config_snapshot["evidence_issues"]


def test_cycle_waits_for_earlier_lift_and_uses_complete_event_timeline():
    p = processor(min_contact_time=0)
    replay(p, [(100, 401, 20, 32), (500, 998, 50, 62), (1000, 1301, 20, 32)])
    report = p.build_report("manual", (), ())
    cycle = next(c for c in report.gait_cycles if c.side == "left")
    assert cycle.total_flight_time_s == pytest.approx((.500 - .401) + (1 - .998))
    times = [e.time_s for e in report.raw_gait_events]
    assert times == sorted(times)
    right_lift = next(e for e in report.raw_gait_events if e.side == "right" and e.kind == "lift")
    last_touch = next(e for e in report.raw_gait_events if e.time_s == 1.0)
    assert right_lift.confirmed_time_s > last_touch.confirmed_time_s


def test_missing_initial_opposite_contact_is_unknown_not_zero():
    b = GaitCycleBuilder()
    b.record_touch(0, "left")
    b.record_touch(.6, "right")
    b.record_lift(.7, "left")
    b.record_lift(1.1, "right")
    c = b.record_touch(1.2, "left")
    assert c.gait_cycle_s == pytest.approx(1.2)
    assert c.load_response_s is None
    assert c.total_double_support_s is None
    assert c.single_support_s is None
    assert c.total_flight_time_s is None


def test_pause_never_reuses_pre_pause_contact_or_side_assumption():
    p = processor()
    replay(p, [(100, 401, 20, 32)], end=200)
    p.pause_boundary()
    events = []
    for sample in range(200, 700):
        bits = [0] * 96
        if sample < 401 or sample >= 500:
            bits[20:32] = [1] * 12
        events.extend(p.process_raw_frame(bits, sample / 1000, sample / 1000))
    assert not any(e.kind == "lift" and e.contact.touch_time == .1 for e in events)
    assert p.build_report("manual", (), ()).gait_cycles == ()


def sensor_frame(sample, *, received=0, stream="one", valid=True):
    from hardware.sensor_frame import SensorFrame, DeviceLayout
    return SensorFrame(stream, DeviceLayout.linear(), sample % 256, sample,
                       received, bytes(96), bytes([int(valid)] * 96), bytes(12))


def test_device_sample_clock_ignores_usb_delivery_jitter(qtbot):
    from engine.gait_engine import GaitEngine
    engine = GaitEngine(processor()._config)
    engine.begin_session(100.)
    engine.process_sensor_frame(sensor_frame(100, received=100_000_000_000))
    engine.process_sensor_frame(sensor_frame(101, received=105_000_000_000))
    assert engine.export_timestamps == pytest.approx([0, .001])


def test_device_gaps_and_invalid_samples_break_cycle_continuity(qtbot):
    from engine.gait_engine import GaitEngine
    engine = GaitEngine(processor()._config)
    engine.begin_session(100.)
    engine.process_sensor_frame(sensor_frame(100))
    engine._processor._cycle_builder.record_touch(0, "left")
    engine.process_sensor_frame(sensor_frame(110))
    assert engine._processor._cycle_builder.record_touch(.01, "left") is None
    engine.process_sensor_frame(sensor_frame(111, valid=False))
    assert len(engine.export_timestamps) == 2
    assert len(engine._processor._evidence_issues) == 2


def test_device_pause_rebases_clock_and_never_compares_different_streams(qtbot):
    from engine.gait_engine import GaitEngine
    engine = GaitEngine(processor()._config)
    engine.begin_session(100.)
    engine.process_sensor_frame(sensor_frame(100))
    engine.process_sensor_frame(sensor_frame(101))
    engine.pause_session()
    engine.process_sensor_frame(sensor_frame(300))
    engine.resume_session()
    engine.process_sensor_frame(sensor_frame(0, stream="two"))
    engine.process_sensor_frame(sensor_frame(1, stream="two"))
    assert engine.export_timestamps == pytest.approx([0, .001, .001, .002])


@pytest.mark.parametrize("gap,expected_contacts", [(9, 1), (10, 2), (11, 2)])
def test_debounce_boundary_does_not_rejoin_already_finished_contacts(gap, expected_contacts):
    events = replay(processor(), [(100, 300, 20, 32), (300 + gap, 600, 20, 32)])
    assert sum(e.kind == "touch" for e in events) == expected_contacts


def test_short_clear_glitch_is_merged_before_identity_assignment():
    p = processor(min_flight_time=50)
    events = replay(p, [(100, 300, 20, 32), (330, 600, 20, 32)])
    assert [e.kind for e in events] == ["touch", "lift"]
    assert events[-1].contact.contact_duration == pytest.approx(.5)


@pytest.mark.parametrize("direction,front", [("Interface side", 50), ("Opposite side", 20)])
def test_startup_double_support_anchors_front_foot_without_inventing_touch(direction, front):
    p = processor(direction=direction, starting_foot_override="right")
    bits = [0] * 96
    bits[20:32] = bits[50:62] = [1] * 12
    assert p.process_raw_frame(bits, 0., 0.) == []
    contacts = p._contact_tracker.active_contacts.values()
    right = next(c for c in contacts if c.side == "right")
    assert right.latest_cluster_start_cm == pytest.approx(front * 1.04)
    assert p._cycle_builder.raw_events == ()
    assert p._cycle_builder.completed_cycles == ()
    assert p.make_status_snapshot(0)["gait_cycle_state"]["support_state"] == "双支撑"


def test_incomplete_opposite_support_is_not_reported_as_zero_in_step_row():
    p = processor()
    # One unknown ongoing startup contact, followed by a known first touch.
    replay(p, [(0, 300, 50, 62), (100, 700, 20, 32)])
    row = p.build_report("manual", (), ()).per_step_results[0]
    assert row.double_support_s is None
    assert row.single_support_s is None


def test_event_confirmation_metadata_survives_report_serialization():
    from dataclasses import asdict
    from config.treadmill_report import GaitEventRecord
    p = processor()
    replay(p, [(100, 300, 20, 32)])
    event = p.build_report("manual", (), ()).raw_gait_events[0]
    assert event.time_s == pytest.approx(.1)
    assert event.confirmed_time_s >= .16 - 1e-9
    assert event.foot_label == "A" and event.contact_id is not None
    assert GaitEventRecord(**asdict(event)) == event
    assert GaitEventRecord(0, .1, "left", "touch").confirmed_time_s is None


def test_statistical_filter_handles_anonymous_contacts_and_is_idempotent():
    p = processor(starting_foot_override=None, automatic_data_filter=30)
    replay(p, [(100, 200, 20, 32), (400, 500, 50, 62), (700, 1000, 20, 32)])
    first = p.build_report("manual", (), ())
    second = p.build_report("manual", (), ())
    assert len(first.per_step_results) == 3
    assert not first.per_step_results[-1].is_included_in_statistics
    assert first.per_step_results == second.per_step_results
    assert first.raw_gait_events == second.raw_gait_events


@pytest.mark.parametrize("value", [-1, 96, 1.5])
def test_invalid_led_thresholds_are_rejected(value):
    with pytest.raises(ValueError, match="GaitR"):
        processor(filter_gaitr_in=value)


@pytest.mark.parametrize("step_ms,stance_ms", [(500, 650), (300, 200)])
def test_complete_cycles_match_independent_raw_contact_masks(step_ms, stance_ms):
    p = processor()
    contacts = [(100 + i * step_ms, 100 + i * step_ms + stance_ms,
                 20 if i % 2 == 0 else 50, 32 if i % 2 == 0 else 62)
                for i in range(8)]
    replay(p, contacts, end=contacts[-1][1] + 100)
    cycles = p.build_report("manual", (), ()).gait_cycles
    assert len(cycles) == 6
    for c in cycles:
        masks = []
        for sample in range(round(c.start_time_s * 1000), round(c.end_time_s * 1000)):
            left = any(a <= sample < b for a, b, lo, _ in contacts if lo == 20)
            right = any(a <= sample < b for a, b, lo, _ in contacts if lo == 50)
            masks.append((left, right))
        double = sum(left and right for left, right in masks) / 1000
        flight = sum(not left and not right for left, right in masks) / 1000
        assert c.gait_cycle_s == pytest.approx(2 * step_ms / 1000)
        assert c.stance_phase_s == pytest.approx(stance_ms / 1000)
        assert c.total_double_support_s == pytest.approx(double)
        assert c.single_support_s == pytest.approx(stance_ms / 1000 - double)
        assert c.total_flight_time_s == pytest.approx(flight)


@pytest.mark.parametrize("start", [100, 400, 700, 800, 1000])
def test_exact_minimum_contact_duration_is_not_rejected_by_float_rounding(start):
    p = processor()
    replay(p, [(start, start + 60, 20, 32)])
    row = p.build_report("manual", (), ()).per_step_results[0]
    assert row.contact_time_s == pytest.approx(.060)
    assert row.is_event_valid
