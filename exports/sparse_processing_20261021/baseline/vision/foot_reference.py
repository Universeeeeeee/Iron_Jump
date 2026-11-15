"""Pure data contracts and event-level left/right foot classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from statistics import median
from typing import Iterable, Sequence


LANDING_CLASSIFIER_VERSION = "landing_v1"
LANDING_CLASSIFIER_ENTRYPOINT = "vision.foot_reference.classify_landing_event"


class FootLabel(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VisionConfig:
    pre_event_ms: int = 120
    post_event_ms: int = 80
    inference_interval_ms: int = 33
    decision_timeout_ms: int = 200
    min_confidence: float = 0.90
    min_landmark_quality: float = 0.65
    frame_buffer_ms: int = 1200
    max_frames: int = 120
    max_events: int = 32

    def __post_init__(self) -> None:
        if self.pre_event_ms < 0:
            raise ValueError("pre_event_ms must be non-negative")
        if self.post_event_ms < 0:
            raise ValueError("post_event_ms must be non-negative")
        if self.inference_interval_ms <= 0:
            raise ValueError("inference_interval_ms must be positive")
        if self.decision_timeout_ms <= 0:
            raise ValueError("decision_timeout_ms must be positive")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if not 0.0 <= self.min_landmark_quality <= 1.0:
            raise ValueError("min_landmark_quality must be between 0 and 1")
        if self.frame_buffer_ms <= 0:
            raise ValueError("frame_buffer_ms must be positive")
        if self.max_frames <= 0:
            raise ValueError("max_frames must be positive")
        if self.max_events <= 0:
            raise ValueError("max_events must be positive")


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float
    visibility: float
    presence: float

    @property
    def quality(self) -> float:
        return min(self.visibility, self.presence)


@dataclass(frozen=True)
class FootPoseSample:
    timestamp_s: float
    left_hip: Landmark
    left_knee: Landmark
    left_ankle: Landmark
    left_heel: Landmark
    left_foot_index: Landmark
    right_hip: Landmark
    right_knee: Landmark
    right_ankle: Landmark
    right_heel: Landmark
    right_foot_index: Landmark
    # Raw MediaPipe output is optional so the online classifier contract stays
    # compatible with existing callers while diagnostics can persist all 33
    # landmarks.
    landmarks_33: tuple[Landmark, ...] | None = None
    # None means unchecked; an empty string means temporally stable.
    identity_reject_reason: str | None = None

    def landmarks(self) -> tuple[Landmark, ...]:
        return (
            self.left_hip,
            self.left_knee,
            self.left_ankle,
            self.left_heel,
            self.left_foot_index,
            self.right_hip,
            self.right_knee,
            self.right_ankle,
            self.right_heel,
            self.right_foot_index,
        )

    def foot_y(self, side: FootLabel) -> float:
        if side is FootLabel.LEFT:
            points = (self.left_ankle, self.left_heel, self.left_foot_index)
        elif side is FootLabel.RIGHT:
            points = (self.right_ankle, self.right_heel, self.right_foot_index)
        else:
            raise ValueError("foot_y requires left or right")
        return median(point.y for point in points)


@dataclass(frozen=True)
class FrameSample:
    captured_at_s: float
    frame: object


@dataclass(frozen=True)
class TouchEvent:
    event_id: int
    event_time_s: float
    submitted_at_s: float


@dataclass(frozen=True)
class VisionWindowDiagnostics:
    frame_count: int = 0
    inference_attempts: int = 0
    pose_total: int = 0
    pose_before: int = 0
    pose_after: int = 0
    max_pose_gap_ms: float | None = None


@dataclass(frozen=True)
class VisionDecision:
    event_id: int
    label: FootLabel
    confidence: float
    reason: str
    event_time_s: float
    decided_at_s: float | None = None
    candidate_label: FootLabel | None = None
    diagnostics: VisionWindowDiagnostics | None = None
    left_evidence: float | None = None
    right_evidence: float | None = None
    classifier_diagnostics: dict[str, object] | None = None


_BOTH_MARGIN = 0.04
_SINGLE_MARGIN = 0.08
_MAX_STABLE_RANGE = 0.04
_CONSISTENCY_RATIO = 0.80
_MIN_LANDING_EXTENSION = 0.025
_FULL_LANDING_EXTENSION = 0.08
_MAX_LANDING_SETTLE_RANGE = 0.05
_BOTH_LANDING_SCORE_MARGIN = 0.12


def unknown_decision(
    event_id: int,
    event_time_s: float,
    reason: str,
    *,
    decided_at_s: float | None = None,
    diagnostics: VisionWindowDiagnostics | None = None,
) -> VisionDecision:
    return VisionDecision(
        event_id=event_id,
        label=FootLabel.UNKNOWN,
        confidence=0.0,
        reason=reason,
        event_time_s=event_time_s,
        decided_at_s=decided_at_s,
        diagnostics=diagnostics,
    )


def classify_event(
    event_id: int,
    event_time_s: float,
    samples: Sequence[FootPoseSample],
    config: VisionConfig | None = None,
) -> VisionDecision:
    """Classify a pose window conservatively.

    Image ``y`` grows downwards. The lower, stable foot is therefore the
    contact candidate. This is a deliberately rejectable first-pass heuristic;
    its thresholds must be validated with the target camera positions.
    """

    cfg = config or VisionConfig()
    if not samples:
        return unknown_decision(event_id, event_time_s, "no_pose_samples")

    ordered = sorted(samples, key=lambda sample: sample.timestamp_s)
    qualities = [min(point.quality for point in sample.landmarks()) for sample in ordered]
    if median(qualities) < cfg.min_landmark_quality:
        return unknown_decision(event_id, event_time_s, "landmarks_not_visible")
    if len(ordered) < 2:
        return unknown_decision(event_id, event_time_s, "insufficient_pose_samples")

    left_y = [sample.foot_y(FootLabel.LEFT) for sample in ordered]
    right_y = [sample.foot_y(FootLabel.RIGHT) for sample in ordered]
    frame_labels = [_label_from_difference(left - right) for left, right in zip(left_y, right_y)]
    label, ratio = _dominant_label(frame_labels)
    if label is FootLabel.UNKNOWN or ratio < _CONSISTENCY_RATIO:
        return unknown_decision(event_id, event_time_s, "window_inconsistent")
    if label is FootLabel.BOTH:
        stable = (
            _value_range(left_y) <= _MAX_STABLE_RANGE
            and _value_range(right_y) <= _MAX_STABLE_RANGE
        )
    elif label is FootLabel.LEFT:
        stable = _value_range(left_y) <= _MAX_STABLE_RANGE
    else:
        stable = _value_range(right_y) <= _MAX_STABLE_RANGE
    if not stable:
        return unknown_decision(event_id, event_time_s, "contact_foot_not_stable")

    difference = abs(median(left_y) - median(right_y))
    quality = median(qualities)
    if label is FootLabel.BOTH:
        geometry = max(0.0, 1.0 - difference / _BOTH_MARGIN)
        reason = "both_feet_level_and_stable"
    else:
        geometry = min(1.0, difference / 0.15)
        reason = f"{label.value}_foot_lower_and_stable"
    confidence = min(1.0, quality * 0.6 + geometry * 0.3 + ratio * 0.1)
    if confidence < cfg.min_confidence:
        return VisionDecision(
            event_id=event_id,
            label=FootLabel.UNKNOWN,
            confidence=confidence,
            reason="confidence_below_threshold",
            event_time_s=event_time_s,
            candidate_label=label,
        )
    return VisionDecision(event_id, label, confidence, reason, event_time_s)


def classify_landing_event(
    event_id: int,
    event_time_s: float,
    samples: Sequence[FootPoseSample],
    config: VisionConfig | None = None,
) -> VisionDecision:
    """Classify which foot descends and settles around a real touch event.

    The optical grid supplies the contact time. This classifier only assigns
    the side by comparing each foot's extension relative to its hip before and
    after that timestamp. A stationary stance foot is therefore not selected
    merely because it remains lower in the image.
    """

    cfg = config or VisionConfig()
    ordered = sorted(samples, key=lambda sample: sample.timestamp_s)
    before = [sample for sample in ordered if sample.timestamp_s <= event_time_s]
    after = [sample for sample in ordered if sample.timestamp_s >= event_time_s]
    if len(before) < 2 or len(after) < 2:
        return unknown_decision(
            event_id,
            event_time_s,
            "insufficient_landing_samples",
        )

    qualities = {
        side: median(_landing_quality(sample, side) for sample in ordered)
        for side in (FootLabel.LEFT, FootLabel.RIGHT)
    }
    if min(qualities.values()) < cfg.min_landmark_quality:
        return unknown_decision(event_id, event_time_s, "landmarks_not_visible")

    descents: dict[FootLabel, float] = {}
    scores: dict[FootLabel, float] = {}
    for side in (FootLabel.LEFT, FootLabel.RIGHT):
        early_count = max(1, len(before) // 2)
        early_extension = median(
            _leg_extension(sample, side) for sample in before[:early_count]
        )
        contact_extensions = [_leg_extension(sample, side) for sample in after]
        contact_extension = median(contact_extensions)
        descent = max(0.0, contact_extension - early_extension)
        settle_range = _value_range(contact_extensions)
        movement_score = min(1.0, descent / _FULL_LANDING_EXTENSION)
        settle_score = max(
            0.0,
            1.0 - settle_range / _MAX_LANDING_SETTLE_RANGE,
        )
        descents[side] = descent
        scores[side] = (
            movement_score * 0.65
            + settle_score * 0.20
            + qualities[side] * 0.15
        )

    left_moved = descents[FootLabel.LEFT] >= _MIN_LANDING_EXTENSION
    right_moved = descents[FootLabel.RIGHT] >= _MIN_LANDING_EXTENSION
    if not left_moved and not right_moved:
        return unknown_decision(event_id, event_time_s, "no_landing_motion")

    if (
        left_moved
        and right_moved
        and abs(scores[FootLabel.LEFT] - scores[FootLabel.RIGHT])
        <= _BOTH_LANDING_SCORE_MARGIN
    ):
        label = FootLabel.BOTH
        confidence = median(
            (scores[FootLabel.LEFT], scores[FootLabel.RIGHT])
        )
        reason = "both_feet_descended_and_settled"
    else:
        eligible = []
        if left_moved:
            eligible.append(FootLabel.LEFT)
        if right_moved:
            eligible.append(FootLabel.RIGHT)
        label = max(eligible, key=lambda side: scores[side])
        other = FootLabel.RIGHT if label is FootLabel.LEFT else FootLabel.LEFT
        separation = max(0.0, scores[label] - scores[other])
        confidence = min(1.0, scores[label] + min(0.12, separation * 0.25))
        reason = f"{label.value}_foot_descended_and_settled"

    if confidence < cfg.min_confidence:
        return VisionDecision(
            event_id=event_id,
            label=FootLabel.UNKNOWN,
            confidence=confidence,
            reason="confidence_below_threshold",
            event_time_s=event_time_s,
            candidate_label=label,
        )
    return VisionDecision(event_id, label, confidence, reason, event_time_s)


def _label_from_difference(difference: float) -> FootLabel:
    if abs(difference) <= _BOTH_MARGIN:
        return FootLabel.BOTH
    if difference >= _SINGLE_MARGIN:
        return FootLabel.LEFT
    if difference <= -_SINGLE_MARGIN:
        return FootLabel.RIGHT
    return FootLabel.UNKNOWN


def _dominant_label(labels: Iterable[FootLabel]) -> tuple[FootLabel, float]:
    values = list(labels)
    if not values:
        return FootLabel.UNKNOWN, 0.0
    counts = {label: values.count(label) for label in FootLabel}
    label = max(counts, key=counts.get)  # type: ignore[arg-type]
    return label, counts[label] / len(values)


def _value_range(values: Sequence[float]) -> float:
    return max(values) - min(values) if values else 0.0


def _side_landmarks(
    sample: FootPoseSample,
    side: FootLabel,
) -> tuple[Landmark, Landmark, Landmark, Landmark]:
    if side is FootLabel.LEFT:
        return (
            sample.left_hip,
            sample.left_ankle,
            sample.left_heel,
            sample.left_foot_index,
        )
    if side is FootLabel.RIGHT:
        return (
            sample.right_hip,
            sample.right_ankle,
            sample.right_heel,
            sample.right_foot_index,
        )
    raise ValueError("side must be left or right")


def _landing_quality(sample: FootPoseSample, side: FootLabel) -> float:
    return min(point.quality for point in _side_landmarks(sample, side))


def _leg_extension(sample: FootPoseSample, side: FootLabel) -> float:
    hip = _side_landmarks(sample, side)[0]
    return sample.foot_y(side) - hip.y
