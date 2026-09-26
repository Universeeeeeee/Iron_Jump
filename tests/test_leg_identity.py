from __future__ import annotations

from vision.foot_reference import FootPoseSample, Landmark
from vision.leg_identity import LegIdentityAnalyzer, LegIdentityState


def _point(x: float, y: float, quality: float = 0.99) -> Landmark:
    return Landmark(x, y, 0.0, quality, quality)


def _sample(
    timestamp: float,
    *,
    left_x: float = 0.35,
    right_x: float = 0.65,
    quality: float = 0.99,
) -> FootPoseSample:
    return FootPoseSample(
        timestamp,
        _point(left_x, 0.30, quality),
        _point(left_x, 0.55, quality),
        _point(left_x, 0.80, quality),
        _point(left_x - 0.02, 0.82, quality),
        _point(left_x + 0.03, 0.82, quality),
        _point(right_x, 0.30, quality),
        _point(right_x, 0.55, quality),
        _point(right_x, 0.80, quality),
        _point(right_x - 0.02, 0.82, quality),
        _point(right_x + 0.03, 0.82, quality),
    )


def test_first_valid_pose_warms_up_then_stable_continuity():
    analyzer = LegIdentityAnalyzer()

    first = analyzer.update(_sample(1.0))
    second = analyzer.update(_sample(1.1, left_x=0.36, right_x=0.66))

    assert first.state is LegIdentityState.UNAVAILABLE
    assert first.reason == "identity_warming_up"
    assert second.state is LegIdentityState.STABLE


def test_low_quality_core_point_is_unavailable():
    analyzer = LegIdentityAnalyzer()
    result = analyzer.update(_sample(1.0, quality=0.40))

    assert result.state is LegIdentityState.UNAVAILABLE
    assert result.reason == "core_landmarks_low_quality"


def test_crossed_labels_are_ambiguous_and_never_silently_reassigned():
    analyzer = LegIdentityAnalyzer()
    analyzer.update(_sample(1.0))

    first = analyzer.update(_sample(1.1, left_x=0.65, right_x=0.35))
    second = analyzer.update(_sample(1.2, left_x=0.64, right_x=0.36))

    assert first.state is LegIdentityState.AMBIGUOUS
    assert first.reason == "media_pipe_identity_swap_suspected"
    assert second.state is LegIdentityState.AMBIGUOUS
    assert second.reason == "media_pipe_identity_swap_detected"
    assert second.swapped_cost < second.original_cost


def test_overlapping_knees_and_ankles_are_ambiguous():
    analyzer = LegIdentityAnalyzer()
    result = analyzer.update(_sample(1.0, left_x=0.50, right_x=0.51))

    assert result.state is LegIdentityState.AMBIGUOUS
    assert result.reason == "legs_overlap"


def test_identity_requires_three_clean_transitions_to_recover():
    analyzer = LegIdentityAnalyzer()
    analyzer.update(_sample(1.0))
    analyzer.update(_sample(1.1, left_x=0.65, right_x=0.35))
    analyzer.update(_sample(1.2, left_x=0.64, right_x=0.36))

    states = [
        analyzer.update(_sample(1.3 + index * 0.1)).state
        for index in range(3)
    ]

    assert states == [
        LegIdentityState.AMBIGUOUS,
        LegIdentityState.AMBIGUOUS,
        LegIdentityState.STABLE,
    ]


def test_missing_pose_is_unavailable_without_exception():
    result = LegIdentityAnalyzer().update(None)

    assert result.state is LegIdentityState.UNAVAILABLE
    assert result.reason == "pose_unavailable"
