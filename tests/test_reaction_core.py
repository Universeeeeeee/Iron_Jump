"""Deterministic tests for the GUI-independent reaction timing contract."""
from dataclasses import asdict, replace
from random import Random

import pytest

from config.config_validation import validate_runtime_config
from config.reaction_config import ReactionConfig
from config.reaction_report import ReactionTestReport, ReactionTrialRecord
from config.test_config import config_from_dict
from engine.reaction_session import ReactionSession
from hardware.sensor_frame import DeviceLayout, SensorFrame


MS = 1_000_000


def config(**kwargs):
    values = dict(ready_hold_ms=2, confirmation_ms=2, stimulus_delay_min_ms=20,
                  stimulus_delay_max_ms=20, minimum_pause="00:00", response_timeout_ms=100)
    values.update(kwargs)
    return ReactionConfig(**values)


def frame(sample, host_ms, occupied=True, **kwargs):
    bits = bytes([int(occupied)] + [0] * 95)
    values = dict(stream_id="stream", layout=DeviceLayout.linear(1), frame_index=sample,
                  sample_index=sample, received_monotonic_ns=int(host_ms * MS),
                  contact_bits=bits, valid_bits=b"\x01" * 96, wire_payload=b"\xff" * 12)
    values.update(kwargs)
    return SensorFrame(**values)


def ready(session, start=0, host_ms=0, occupied=True):
    for n in range(3):
        session.on_frame(frame(start + n, host_ms + n, occupied))
    assert session.state == "waiting"


def stimulated(session, request_ms=22):
    events = session.poll(request_ms * MS)
    assert [event.kind for event in events] == ["state_changed", "stimulus_requested"]
    event = events[-1]
    session.acknowledge_stimulus(event.trial_index, request_ms * MS, event.modality, host_ns=request_ms * MS)
    assert session.state == "responding"


def test_roundtrip_and_strict_validation():
    original = ReactionConfig()
    assert config_from_dict(original.to_dict()) == original
    assert validate_runtime_config(original) == []
    for changes in ({"number_of_repetitions": True}, {"number_of_repetitions": 100},
                    {"stimulus_delay_max_ms": 1}, {"confirmation_ms": 0},
                    {"minimum_pause": "bad"}, {"stimulus_type": "simultaneous"},
                    {"stimulus_type": []}, {"start_position": {}}, {"response_timeout_ms": float("nan")}):
        assert validate_runtime_config(replace(original, **changes))


def test_valid_uses_host_request_and_backdated_candidate_not_device_clock():
    session = ReactionSession(config(number_of_repetitions=1), clock=lambda: 0)
    session.begin(0)
    ready(session, start=10000)
    stimulated(session)
    # USB batch delivers all three device samples with the same host timestamp.
    for sample in range(10003, 10006):
        session.on_frame(frame(sample, 55, False))
    report = session.build_report()
    trial = report.trials[0]
    assert trial.status == "valid"
    assert trial.reaction_time_ms == 33
    assert trial.response_sample_index == 10003
    assert trial.confirmation_sample_index == 10005
    assert trial.confirmation_received_host_ns == 55 * MS
    assert trial.stimulus_scheduled_host_ns == 22 * MS
    assert trial.response_received_host_ns == 55 * MS
    assert trial.actual_stimulus_onset_ns is None
    assert trial.timing_quality == "uncalibrated"
    assert report.finish_reason == "completed"
    assert session.is_finished
    assert report.mean_reaction_time_ms == 33


def test_outside_entry_and_no_universal_100ms_false_start():
    session = ReactionSession(config(start_position="Outside area", number_of_repetitions=1))
    session.begin(0)
    ready(session, occupied=False)
    stimulated(session)
    for n in range(3):
        session.on_frame(frame(3 + n, 23 + n, True))
    assert session.trials[0].status == "valid"
    assert session.trials[0].reaction_time_ms == 1
    assert session.trials[0].action == "entry"


def test_candidate_before_request_confirmed_after_is_early():
    session = ReactionSession(config(number_of_repetitions=1))
    session.begin(0)
    ready(session)
    session.on_frame(frame(3, 21, False))
    stimulated(session)
    session.on_frame(frame(4, 23, False))
    session.on_frame(frame(5, 24, False))
    assert session.trials[0].status == "early"
    assert session.trials[0].response_received_host_ns == 21 * MS
    assert session.trials[0].reaction_time_ms is None


def test_pending_ack_buffers_confirmed_edge_until_request_time_known():
    session = ReactionSession(config(number_of_repetitions=1))
    session.begin(0)
    ready(session)
    session.poll(22 * MS)
    for n in range(3):
        session.on_frame(frame(3 + n, 25 + n, False))
    assert session.state == "stimulus_pending"
    session.acknowledge_stimulus(1, 23 * MS, "visual", host_ns=27 * MS)
    assert session.trials[0].status == "valid"
    assert session.trials[0].reaction_time_ms == 2


def test_waiting_movement_is_early_and_resets_candidates():
    session = ReactionSession(config(number_of_repetitions=2))
    session.begin(0)
    ready(session)
    for n in range(3):
        session.on_frame(frame(3 + n, 4 + n, False))
    assert session.trials[0].status == "early"
    session.poll(6 * MS)
    assert session.state == "preparing"
    ready(session, start=6, host_ms=7)
    assert session._candidate is None


@pytest.mark.parametrize("changes,flag", [
    ({"sample_index": 9}, "frame_gap"),
    ({"dropped_frames_before": 1}, "frame_gap"),
    ({"stream_id": "new"}, "stream_changed"),
    ({"valid_bits": b"\x00" + b"\x01" * 95}, "invalid_beams"),
    ({"contact_bits": b"\x01" * 96}, "all_beams_blocked"),
    ({"layout": DeviceLayout.linear(2)}, "unsupported_layout"),
    ({"contact_bits": b"\x02" + b"\x00" * 95}, "invalid_contact_bits"),
])
def test_bad_data_halts_without_consuming_remaining_trials(changes, flag):
    session = ReactionSession(config(number_of_repetitions=5))
    session.begin(0)
    ready(session)
    session.on_frame(frame(3, 3, **changes))
    assert session.is_finished
    assert len(session.trials) == 1
    assert session.trials[0].status == "gap"
    assert flag in session.trials[0].quality_flags
    session.poll(999999 * MS)
    assert len(session.trials) == 1


def test_timeout_boundary_and_pending_candidate_confirmation():
    session = ReactionSession(config(number_of_repetitions=1))
    session.begin(0)
    ready(session)
    stimulated(session)
    session.on_frame(frame(3, 122, False))
    session.poll(123 * MS)
    assert session.state == "responding"
    session.on_frame(frame(4, 123, False))
    session.on_frame(frame(5, 124, False))
    assert session.trials[0].status == "valid"
    assert session.trials[0].reaction_time_ms == 100


def test_timeout_excludes_unconfirmed_glitch():
    session = ReactionSession(config(number_of_repetitions=1))
    session.begin(0)
    ready(session)
    stimulated(session)
    session.on_frame(frame(3, 121, False))
    session.on_frame(frame(4, 123, True))
    assert session.trials[0].status == "timeout"
    assert session.trials[0].reaction_time_ms is None


def test_stale_and_missing_ack_halt():
    session = ReactionSession(config())
    session.begin(0)
    session.poll(500 * MS)
    assert session.is_finished
    assert session.trials[0].status == "gap"
    session = ReactionSession(config())
    session.begin(0)
    ready(session)
    session.poll(22 * MS)
    # Fresh data prevents the independent stale watchdog from firing first.
    for n in range(3, 1003):
        session.on_frame(frame(n, n + 20))
    assert session.is_finished
    assert session.trials[0].status == "stimulus_failed"


def test_manual_next_respects_rest_and_cancel_cleanup():
    session = ReactionSession(config(number_of_repetitions=2, sequence_type="Manual", minimum_pause="00:01"))
    session.begin(0)
    ready(session)
    stimulated(session)
    for n in range(3):
        session.on_frame(frame(3 + n, 30 + n, False))
    assert session.state == "rest"
    assert session.next_trial(1000 * MS) == ()
    session.poll(1032 * MS)
    assert session.snapshot()["next_allowed"]
    session.next_trial(1032 * MS)
    assert session.state == "preparing"
    session.cancel(1033 * MS)
    assert [trial.status for trial in session.trials] == ["valid", "cancelled"]
    assert session.build_report().finish_reason == "cancelled"
    assert session.on_frame(frame(100, 2000)) == ()
    assert session.acknowledge_stimulus(2, 2000 * MS) == ()
    assert session.cancel(2001 * MS) == ()
    assert session._candidate is None


def test_random_modalities_are_exclusive_and_deterministic():
    a = ReactionSession(config(stimulus_type="Visual/Acoustic stimulus"), rng=Random(7))
    b = ReactionSession(config(stimulus_type="Visual/Acoustic stimulus"), rng=Random(7))
    assert a.begin(0)[0].modality == b.begin(0)[0].modality
    assert a._modality in {"visual", "acoustic"}


def test_grouped_statistics_and_frozen_serialization():
    trials = (ReactionTrialRecord(1, "visual", "takeoff", "valid", reaction_time_ms=50),
              ReactionTrialRecord(2, "visual", "takeoff", "valid", reaction_time_ms=150),
              ReactionTrialRecord(3, "visual", "takeoff", "early"),
              ReactionTrialRecord(4, "acoustic", "takeoff", "timeout"))
    report = ReactionTestReport(trials)
    assert report.valid_count == 2
    assert report.median_reaction_time_ms == 100
    assert report.grouped_statistics["visual"] == dict(count=2, mean_ms=100, median_ms=100, min_ms=50, max_ms=150, std_ms=50)
    assert report.grouped_statistics["acoustic"]["mean_ms"] is None
    assert asdict(report)["trials"][0]["timing_quality"] == "uncalibrated"
    with pytest.raises(AttributeError):
        report.trials[0].status = "timeout"


def test_hold_and_confirmation_use_elapsed_device_sample_duration():
    session = ReactionSession(config(ready_hold_ms=3, confirmation_ms=3, number_of_repetitions=1))
    session.begin(0)
    for n in range(3):
        session.on_frame(frame(n, n))
    assert session.state == "preparing"
    session.on_frame(frame(3, 3))
    assert session.state == "waiting"
    stimulated(session, request_ms=23)
    for n in range(4, 7):
        session.on_frame(frame(n, 24 + n, False))
    assert session.state == "responding"
    session.on_frame(frame(7, 31, False))
    assert session.trials[0].response_sample_index == 4
    assert session.trials[0].reaction_time_ms == 5


def test_unknown_quality_flag_cannot_become_valid():
    session = ReactionSession(config())
    session.begin(0)
    session.on_frame(frame(0, 0, quality_flags=("clock_uncertain",)))
    assert session.trials[0].status == "gap"
    assert "sensor_quality:clock_uncertain" in session.trials[0].quality_flags


def test_pending_confirmed_response_survives_return_to_baseline_before_ack():
    session = ReactionSession(config(number_of_repetitions=1))
    session.begin(0)
    ready(session)
    session.poll(22 * MS)
    for n in range(3):
        session.on_frame(frame(3 + n, 25 + n, False))
    session.on_frame(frame(6, 28, True))
    session.acknowledge_stimulus(1, 23 * MS, "visual", host_ns=29 * MS)
    assert session.trials[0].status == "valid"
    assert session.trials[0].response_received_host_ns == 25 * MS
    assert session.trials[0].confirmation_sample_index == 5
    assert session.trials[0].confirmation_received_host_ns == 27 * MS


@pytest.mark.parametrize("stamp", [float("nan"), float("inf"), True, 24 * MS, 21 * MS])
def test_bad_or_future_ack_timestamp_rejected(stamp):
    session = ReactionSession(config())
    session.begin(0)
    ready(session)
    session.poll(22 * MS)
    session.acknowledge_stimulus(1, stamp, host_ns=23 * MS)
    assert session.trials[0].status == "stimulus_failed"
    assert session.is_finished


def test_stale_ack_and_ack_timeout_cannot_resurrect_session():
    session = ReactionSession(config())
    session.begin(0)
    ready(session)
    session.poll(22 * MS)
    session.acknowledge_stimulus(1, 22 * MS, host_ns=502 * MS)
    assert session.is_finished
    assert session.trials[0].status == "gap"
    assert session.acknowledge_stimulus(1, 22 * MS, host_ns=503 * MS) == ()

    session = ReactionSession(config())
    session.begin(0)
    ready(session)
    session.poll(22 * MS)
    # Keep fresh frames just before the acknowledgement deadline.
    for n in range(3, 1002):
        session.on_frame(frame(n, n + 20))
    session.acknowledge_stimulus(1, 22 * MS, host_ns=1022 * MS)
    assert session.trials[0].status == "stimulus_failed"


def test_rest_preserves_device_continuity_and_rejects_reboot():
    session = ReactionSession(config(number_of_repetitions=2))
    session.begin(0)
    ready(session)
    stimulated(session)
    for n in range(3):
        session.on_frame(frame(3 + n, 30 + n, False))
    assert session.state == "rest"
    session.on_frame(frame(0, 33, stream_id="reboot"))
    assert session.is_finished
    assert len(session.trials) == 1
    assert session.build_report().finish_reason == "error"


def test_ack_before_candidate_with_tiny_host_rt_is_valid():
    session = ReactionSession(config(number_of_repetitions=1))
    session.begin(0)
    ready(session)
    stimulated(session)
    for n in range(3):
        session.on_frame(frame(3 + n, 22, False))
    assert session.trials[0].status == "valid"
    assert session.trials[0].reaction_time_ms == 0


def test_manual_stop_reason_is_retained_in_report():
    session = ReactionSession(config())
    assert session.cancel(0) == ()
    session.begin(0)
    session.halt("manual", 1)
    assert session.build_report().finish_reason == "manual"
    assert session.build_report("override").finish_reason == "override"


def test_interarrival_stale_is_rejected_even_when_timer_has_not_polled():
    session = ReactionSession(config())
    session.begin(0)
    ready(session)
    stimulated(session)
    session.on_frame(frame(3, 502, False))
    assert session.is_finished
    assert session.trials[0].status == "gap"
    assert session.trials[0].quality_flags == ("stale_sensor_data",)


def test_report_captures_timing_contract_without_claiming_synchronization():
    report = ReactionSession(config()).build_report()
    snapshot = report.report_config_snapshot
    assert snapshot["hardware_sample_rate_hz"] == 1000
    assert snapshot["host_clock"] == "perf_counter_ns"
    assert snapshot["timing_quality"] == "uncalibrated"
    assert snapshot["actual_stimulus_onset_available"] is False
    assert snapshot["device_host_synchronization"] == "unavailable"


def cascade_frame(sample, host_ms, occupied, segment_count=5):
    layout = DeviceLayout.linear(segment_count)
    # The last beam proves the complete configured area participates in the edge.
    bits = b"\x00" * (layout.bit_count - 1) + bytes([int(occupied)])
    return frame(sample, host_ms, layout=layout, contact_bits=bits,
                 valid_bits=b"\x01" * layout.bit_count,
                 wire_payload=b"\xff" * layout.payload_bytes)


@pytest.mark.parametrize("segment_count", [1, 5, 10])
@pytest.mark.parametrize("start_position,action", [("Inside area", "takeoff"), ("Outside area", "entry")])
def test_complete_cascade_uses_last_segment_with_same_host_timing(segment_count, start_position, action):
    session = ReactionSession(config(start_position=start_position, number_of_repetitions=1))
    session.begin(0)
    baseline = start_position == "Inside area"
    for sample in range(3):
        session.on_frame(cascade_frame(sample, sample, baseline, segment_count))
    assert session.state == "waiting"
    stimulated(session)
    for sample in range(3, 6):
        session.on_frame(cascade_frame(sample, 55, not baseline, segment_count))
    trial = session.build_report().trials[0]
    assert trial.status == "valid"
    assert trial.action == action
    assert trial.reaction_time_ms == 33
    assert trial.response_sample_index == 3
    assert trial.confirmation_sample_index == 5
    assert trial.response_received_host_ns == 55 * MS
    assert trial.timing_quality == "uncalibrated"
    assert trial.actual_stimulus_onset_ns is None


@pytest.mark.parametrize("name,length", [("contact_bits", 96), ("contact_bits", 479),
                                           ("contact_bits", 481), ("valid_bits", 96),
                                           ("valid_bits", 479), ("valid_bits", 481)])
def test_cascade_requires_full_exact_bit_lengths(name, length):
    session = ReactionSession(config())
    session.begin(0)
    sample = cascade_frame(0, 0, True)
    session.on_frame(replace(sample, **{name: b"\x01" * length}))
    assert session.is_finished
    assert session.trials[0].status == "gap"
    assert session.trials[0].quality_flags == ("unsupported_layout",)


def test_cascade_invalid_beam_in_last_segment_is_fatal():
    session = ReactionSession(config())
    session.begin(0)
    sample = cascade_frame(0, 0, True)
    session.on_frame(replace(sample, valid_bits=b"\x01" * 479 + b"\x00"))
    assert session.trials[0].quality_flags == ("invalid_beams",)
    assert session.is_finished


def test_cascade_layout_change_is_fatal_with_complete_new_frames():
    session = ReactionSession(config())
    session.begin(0)
    session.on_frame(cascade_frame(0, 0, True, 5))
    session.on_frame(cascade_frame(1, 1, True, 4))
    assert session.is_finished
    assert session.trials[0].status == "gap"
    assert session.trials[0].quality_flags == ("stream_changed",)


def test_cascade_declared_mask_is_fatal_even_with_all_valid_bytes():
    session = ReactionSession(config())
    session.begin(0)
    sample = cascade_frame(0, 0, True)
    layout = replace(sample.layout, invalid_bit_indices=(479,))
    session.on_frame(replace(sample, layout=layout))
    assert session.is_finished
    assert session.trials[0].quality_flags == ("invalid_beams",)
