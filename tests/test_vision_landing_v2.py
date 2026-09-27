from __future__ import annotations

import math
from dataclasses import replace

import pytest

from vision.foot_reference import FootLabel, FootPoseSample, Landmark
from vision.event_scheduler import EventWindowScheduler
from vision.foot_reference import VisionConfig
from vision.landing_v2 import (
    LandingV2Classifier,
    TreadmillAxisCalibration,
    classify_landing_v2,
    _identity_anomaly,
)


def _point(x: float, y: float, quality: float = 0.99) -> Landmark:
    return Landmark(x, y, 0.0, quality, quality)


def _sample(timestamp: float, left_x: float, right_x: float) -> FootPoseSample:
    return FootPoseSample(
        timestamp_s=timestamp,
        left_hip=_point(0.45, 0.35),
        left_knee=_point((0.45 + left_x) / 2, 0.60),
        left_ankle=_point(left_x, 0.85),
        left_heel=_point(left_x - 0.01, 0.86),
        left_foot_index=_point(left_x + 0.02, 0.86),
        right_hip=_point(0.55, 0.35),
        right_knee=_point((0.55 + right_x) / 2, 0.60),
        right_ankle=_point(right_x, 0.85),
        right_heel=_point(right_x - 0.01, 0.86),
        right_foot_index=_point(right_x + 0.02, 0.86),
    )


def _calibration() -> TreadmillAxisCalibration:
    return TreadmillAxisCalibration.create((0.1, 0.8), (0.9, 0.8), (0.0, 1.0))


def test_calibration_normalizes_basis_and_solves_non_orthogonal_coordinates():
    calibration = TreadmillAxisCalibration.create(
        (0.1, 0.8), (0.9, 0.7), (0.2, 1.0)
    )
    longitudinal, vertical = calibration.solve(calibration.forward_axis_unit)

    assert math.hypot(*calibration.forward_axis_unit) == pytest.approx(1.0)
    assert math.hypot(*calibration.vertical_axis_unit) == pytest.approx(1.0)
    assert longitudinal == pytest.approx(1.0)
    assert vertical == pytest.approx(0.0)


def test_calibration_rejects_degenerate_basis():
    with pytest.raises(ValueError, match="calibration_basis_degenerate"):
        TreadmillAxisCalibration.create((0.1, 0.1), (0.9, 0.1), (1.0, 0.1))


def test_resolution_change_invalidates_cached_axis_points():
    classifier = LandingV2Classifier((0.1, 0.8), (0.9, 0.8))
    assert classifier.axis_points is not None
    assert classifier.set_frame_geometry(1280, 720)
    assert classifier.axis_points is None


def test_v2_selects_side_whose_forward_peak_turns_backward_at_contact():
    timestamps = (-0.24, -0.12, -0.005, 0.04, 0.12, 0.19)
    left = (0.42, 0.50, 0.56, 0.53, 0.47, 0.40)
    right = (0.60, 0.61, 0.62, 0.63, 0.64, 0.65)
    samples = [_sample(t, lx, rx) for t, lx, rx in zip(timestamps, left, right)]

    decision = classify_landing_v2(1, 0.0, samples, _calibration())

    assert decision.label is FootLabel.LEFT
    assert decision.left_evidence is not None
    assert decision.right_evidence is not None
    assert decision.left_evidence > decision.right_evidence
    assert decision.classifier_diagnostics["left_post_velocity"] < 0


def test_v2_rejects_low_quality_side_instead_of_single_side_correction():
    samples = [_sample(t, 0.5, 0.60) for t in (-0.18, -0.08, 0.04, 0.14)]
    samples = [
        FootPoseSample(
            **{**sample.__dict__, "right_ankle": _point(0.60, 0.85, 0.2)}
        )
        for sample in samples
    ]

    decision = classify_landing_v2(1, 0.0, samples, _calibration())

    assert decision.label is FootLabel.UNKNOWN
    assert decision.reason == "landmarks_not_visible"


def _persistent_swap_samples():
    original = _sample(0.0, 0.45, 0.55)
    swapped = {
        f"{side}_{joint}": getattr(original, f"{other}_{joint}")
        for side, other in (("left", "right"), ("right", "left"))
        for joint in ("hip", "knee", "ankle", "heel", "foot_index")
    }
    return [original] + [
        replace(original, timestamp_s=i * 0.06, **swapped) for i in range(1, 13)
    ]


def test_identity_gate_rejects_one_swap_followed_by_stable_wrong_labels():
    samples = _persistent_swap_samples()
    assert _identity_anomaly(samples) is not None


def test_online_and_replay_reject_swap_before_overlapping_event_windows(tmp_path):
    from vision.annotations import save_annotations, set_annotation
    from vision.replay import replay_session
    from vision.session import (
        VisionSessionRecorder, canonical_reject_reason, pose_sample_to_record,
    )

    samples = _persistent_swap_samples()
    config = VisionConfig(
        pre_event_ms=250, post_event_ms=200, inference_interval_ms=60,
        decision_timeout_ms=500,
    )
    scheduler = EventWindowScheduler(config)
    classifier = LandingV2Classifier((0.1, 0.8), (0.9, 0.8))
    for sample in samples:
        scheduler.add_frame(sample, sample.timestamp_s)
    for event_id, timestamp in ((1, 0.42), (2, 0.48)):
        scheduler.add_event(event_id, timestamp, submitted_at_s=timestamp)
    inferred = []

    def infer(sample, timestamp_ms):
        inferred.append(timestamp_ms)
        return sample

    decisions = scheduler.process_ready(infer, classifier, now_s=0.72)
    assert [d.reason for d in decisions] == ["identity_anomaly"] * 2
    assert all(d.label is FootLabel.UNKNOWN for d in decisions)
    assert all(
        d.classifier_diagnostics["identity_reason"]
        == "media_pipe_identity_swap_detected" for d in decisions
    )
    scheduler.process_ready(infer, classifier, now_s=0.72)
    assert inferred == [round(s.timestamp_s * 1000) for s in samples]

    recorder = VisionSessionRecorder(tmp_path, metadata={
        "treadmill_axis_calibration": {
            "rear_normalized": [0.1, 0.8], "front_normalized": [0.9, 0.8],
        },
    })
    for sample in samples:
        points = [_point(0.5, 0.5)] * 33
        for side, offset in (("left", 0), ("right", 1)):
            for joint, index in (("hip", 23), ("knee", 25), ("ankle", 27),
                                 ("heel", 29), ("foot_index", 31)):
                points[index + offset] = getattr(sample, f"{side}_{joint}")
        recorder.record_pose(pose_sample_to_record(
            replace(sample, landmarks_33=tuple(points)), frame_index=None,
            camera_sample_timestamp=None, perf_counter_timestamp=sample.timestamp_s,
            inference_start_timestamp=sample.timestamp_s,
            inference_end_timestamp=sample.timestamp_s,
        ))
    annotations = {}
    for event_id, timestamp in ((1, 0.42), (2, 0.48)):
        recorder.record_contact({
            "event_id": event_id, "contact_timestamp": timestamp,
            "event_role": "grid_touch", "valid_for_benchmark": "1",
        })
        set_annotation(annotations, event_id, "Left")
    recorder.close()
    save_annotations(recorder.paths.annotations, annotations)
    _, rows = replay_session(recorder.session_root, mode="visual-evidence-v2")
    assert [r["prediction"] for r in rows] == ["Unknown"] * 2
    assert [r["reason"] for r in rows] == [
        canonical_reject_reason(d.reason, d.label.value) for d in decisions
    ]

    # A new session must not retain the prior session's ambiguous tracks.
    scheduler.reset()
    for sample in samples:
        scheduler.add_frame(replace(samples[0], timestamp_s=sample.timestamp_s),
                            sample.timestamp_s)
    scheduler.add_event(3, 0.42, submitted_at_s=0.42)
    decision = scheduler.process_ready(infer, classifier, now_s=0.72)[0]
    assert decision.reason == "evidence_below_threshold"
