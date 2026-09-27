"""Treadmill event evidence in a calibrated image-plane coordinate system."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from statistics import median
from typing import Sequence

from .foot_reference import (
    FootLabel,
    FootPoseSample,
    Landmark,
    VisionConfig,
    VisionDecision,
    unknown_decision,
)
from .leg_identity import LegIdentityAnalyzer, LegIdentityState


LANDING_V2_VERSION = "landing_v2"
LANDING_V2_ENTRYPOINT = "vision.landing_v2.LandingV2Classifier"


@dataclass(frozen=True)
class TreadmillAxisCalibration:
    rear_normalized: tuple[float, float]
    front_normalized: tuple[float, float]
    forward_axis_unit: tuple[float, float]
    vertical_axis_unit: tuple[float, float]
    forward_axis_angle_degrees: float
    basis_determinant: float
    analysis_mirrored: bool = False
    frame_width: int = 1920
    frame_height: int = 1080

    @classmethod
    def create(
        cls,
        rear_normalized: tuple[float, float],
        front_normalized: tuple[float, float],
        vertical_axis: tuple[float, float],
        *,
        analysis_mirrored: bool = False,
        frame_width: int = 1920,
        frame_height: int = 1080,
    ) -> "TreadmillAxisCalibration":
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("calibration_resolution_invalid")
        forward_px = (
            (front_normalized[0] - rear_normalized[0]) * frame_width,
            (front_normalized[1] - rear_normalized[1]) * frame_height,
        )
        vertical_px = (
            vertical_axis[0] * frame_width,
            vertical_axis[1] * frame_height,
        )
        forward = _unit(forward_px)
        vertical = _unit(vertical_px)
        determinant = _cross(forward, vertical)
        if abs(determinant) < math.sin(math.radians(35.0)):
            raise ValueError("calibration_basis_degenerate")
        return cls(
            rear_normalized=rear_normalized,
            front_normalized=front_normalized,
            forward_axis_unit=forward,
            vertical_axis_unit=vertical,
            forward_axis_angle_degrees=math.degrees(
                math.atan2(forward[1], forward[0])
            ),
            basis_determinant=determinant,
            analysis_mirrored=analysis_mirrored,
            frame_width=frame_width,
            frame_height=frame_height,
        )

    def solve(self, delta: tuple[float, float]) -> tuple[float, float]:
        fx, fy = self.forward_axis_unit
        vx, vy = self.vertical_axis_unit
        determinant = self.basis_determinant
        longitudinal = (delta[0] * vy - vx * delta[1]) / determinant
        vertical = (fx * delta[1] - delta[0] * fy) / determinant
        return longitudinal, vertical

    def as_dict(self) -> dict[str, object]:
        return {
            "rear_normalized": list(self.rear_normalized),
            "front_normalized": list(self.front_normalized),
            "forward_axis_unit": list(self.forward_axis_unit),
            "vertical_axis_unit": list(self.vertical_axis_unit),
            "forward_axis_angle_degrees": self.forward_axis_angle_degrees,
            "basis_determinant": self.basis_determinant,
            "analysis_mirrored": self.analysis_mirrored,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
        }


@dataclass(frozen=True)
class LandingV2Config:
    direct_threshold: float = 0.72
    margin_threshold: float = 0.15
    landmark_quality: float = 0.60
    max_pose_gap_ms: float = 130.0


class LandingV2Classifier:
    """Thread-safe callable used by ``FootVisionService`` and Replay."""

    def __init__(
        self,
        rear_normalized: tuple[float, float] | None = None,
        front_normalized: tuple[float, float] | None = None,
        *,
        analysis_mirrored: bool = False,
        settings: LandingV2Config | None = None,
        frame_width: int = 1920,
        frame_height: int = 1080,
    ) -> None:
        self._rear = rear_normalized
        self._front = front_normalized
        self._analysis_mirrored = analysis_mirrored
        self._settings = settings or LandingV2Config()
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._lock = threading.Lock()

    def set_axis_points(
        self,
        rear_normalized: tuple[float, float],
        front_normalized: tuple[float, float],
    ) -> None:
        with self._lock:
            self._rear = rear_normalized
            self._front = front_normalized

    def set_frame_geometry(self, width: int, height: int) -> bool:
        """Update analysis geometry and invalidate points when it changes."""

        if width <= 0 or height <= 0:
            raise ValueError("calibration_resolution_invalid")
        with self._lock:
            changed = width != self._frame_width or height != self._frame_height
            self._frame_width = width
            self._frame_height = height
            if changed:
                self._rear = None
                self._front = None
            return changed

    @property
    def axis_points(self) -> tuple[tuple[float, float], tuple[float, float]] | None:
        with self._lock:
            if self._rear is None or self._front is None:
                return None
            return self._rear, self._front

    def __call__(
        self,
        event_id: int,
        event_time_s: float,
        samples: Sequence[FootPoseSample],
        config: VisionConfig | None = None,
    ) -> VisionDecision:
        with self._lock:
            rear, front = self._rear, self._front
        if rear is None or front is None:
            return unknown_decision(event_id, event_time_s, "calibration_required")
        try:
            vertical = _median_vertical_axis(samples)
            calibration = TreadmillAxisCalibration.create(
                rear,
                front,
                vertical,
                analysis_mirrored=self._analysis_mirrored,
                frame_width=self._frame_width,
                frame_height=self._frame_height,
            )
        except ValueError as exc:
            return unknown_decision(event_id, event_time_s, str(exc))
        return classify_landing_v2(
            event_id,
            event_time_s,
            samples,
            calibration,
            config=config,
            settings=self._settings,
        )


def classify_landing_v2(
    event_id: int,
    event_time_s: float,
    samples: Sequence[FootPoseSample],
    calibration: TreadmillAxisCalibration,
    *,
    config: VisionConfig | None = None,
    settings: LandingV2Config | None = None,
) -> VisionDecision:
    """Return conservative left/right touchdown-phase evidence around contact."""

    del config  # Windowing is owned by the scheduler; V2 has explicit gates.
    cfg = settings or LandingV2Config()
    ordered = sorted(samples, key=lambda item: item.timestamp_s)
    before = [item for item in ordered if item.timestamp_s < event_time_s]
    after = [item for item in ordered if item.timestamp_s >= event_time_s]
    if len(before) < 2 or len(after) < 2:
        return unknown_decision(event_id, event_time_s, "insufficient_pose_samples")
    max_gap_ms = max(
        (b.timestamp_s - a.timestamp_s) * 1000.0
        for a, b in zip(ordered, ordered[1:])
    )

    diagnostics: dict[str, object] = {
        "calibration_status": "ready",
        "basis_determinant": calibration.basis_determinant,
        "forward_axis_angle_degrees": calibration.forward_axis_angle_degrees,
        "pose_before": len(before),
        "pose_after": len(after),
        "max_pose_gap_ms": max_gap_ms,
    }
    if max_gap_ms > cfg.max_pose_gap_ms:
        return _unknown_with_diagnostics(
            event_id, event_time_s, "pose_gap_too_large", diagnostics
        )

    qualities = {
        side: median(_core_quality(sample, side) for sample in ordered)
        for side in (FootLabel.LEFT, FootLabel.RIGHT)
    }
    diagnostics.update(
        left_observation_quality=qualities[FootLabel.LEFT],
        right_observation_quality=qualities[FootLabel.RIGHT],
    )
    if min(qualities.values()) < cfg.landmark_quality:
        return _unknown_with_diagnostics(
            event_id, event_time_s, "landmarks_not_visible", diagnostics
        )

    identity_reason = _identity_anomaly(ordered)
    if identity_reason is not None:
        diagnostics["identity_reason"] = identity_reason
        return _unknown_with_diagnostics(
            event_id, event_time_s, "identity_anomaly", diagnostics
        )

    evidence: dict[FootLabel, float] = {}
    for side in (FootLabel.LEFT, FootLabel.RIGHT):
        features = _side_features(ordered, event_time_s, side, calibration)
        score = (
            0.50 * features["peak_phase"]
            + 0.25 * features["velocity_turn"]
            + 0.25 * features["post_backward"]
        )
        evidence[side] = score
        prefix = side.value
        diagnostics.update({f"{prefix}_{key}": value for key, value in features.items()})
        diagnostics[f"{prefix}_contact_evidence"] = score

    winner = max(evidence, key=evidence.get)  # type: ignore[arg-type]
    loser = opposite_side(winner)
    margin = evidence[winner] - evidence[loser]
    diagnostics["evidence_margin"] = margin
    if evidence[winner] < cfg.direct_threshold:
        return _unknown_with_evidence(
            event_id,
            event_time_s,
            "evidence_below_threshold",
            evidence,
            diagnostics,
            winner,
        )
    if margin < cfg.margin_threshold:
        return _unknown_with_evidence(
            event_id,
            event_time_s,
            "evidence_margin_too_small",
            evidence,
            diagnostics,
            winner,
        )
    return VisionDecision(
        event_id=event_id,
        label=winner,
        confidence=evidence[winner],
        reason=f"{winner.value}_touchdown_phase_evidence",
        event_time_s=event_time_s,
        left_evidence=evidence[FootLabel.LEFT],
        right_evidence=evidence[FootLabel.RIGHT],
        classifier_diagnostics=diagnostics,
    )


def opposite_side(side: FootLabel) -> FootLabel:
    return FootLabel.RIGHT if side is FootLabel.LEFT else FootLabel.LEFT


def _side_features(
    samples: Sequence[FootPoseSample],
    event_time_s: float,
    side: FootLabel,
    calibration: TreadmillAxisCalibration,
) -> dict[str, float]:
    points = [
        (sample.timestamp_s, _longitudinal_q(sample, side, calibration))
        for sample in samples
    ]
    contact = [item for item in points if abs(item[0] - event_time_s) <= 0.120]
    pre = [item for item in points if -0.250 <= item[0] - event_time_s <= -0.020]
    post = [item for item in points if 0.020 <= item[0] - event_time_s <= 0.200]
    peak_time, _ = max(contact or points, key=lambda item: item[1])
    peak_delta = peak_time - event_time_s
    pre_velocity = _linear_slope(pre)
    post_velocity = _linear_slope(post)
    peak_phase = _clamp01(1.0 - abs(peak_delta) / 0.120)
    velocity_turn = _clamp01((pre_velocity - post_velocity) / 6.0)
    post_backward = _clamp01(-post_velocity / 3.0)
    distance_delta = _hip_foot_peak_delta(
        samples, event_time_s, side, calibration
    )
    return {
        "peak_phase": peak_phase,
        "velocity_turn": velocity_turn,
        "post_backward": post_backward,
        "pre_velocity": pre_velocity,
        "post_velocity": post_velocity,
        "longitudinal_peak_time_delta": peak_delta,
        "hip_foot_distance_peak_time_delta": distance_delta,
    }


def _longitudinal_q(
    sample: FootPoseSample,
    side: FootLabel,
    calibration: TreadmillAxisCalibration,
) -> float:
    hip, knee, ankle = _core_points(sample, side)
    longitudinal, _ = calibration.solve(
        (
            (ankle.x - hip.x) * calibration.frame_width,
            (ankle.y - hip.y) * calibration.frame_height,
        )
    )
    leg_length = _distance_px(hip, knee, calibration) + _distance_px(
        knee, ankle, calibration
    )
    return longitudinal / max(leg_length, 1e-6)


def _hip_foot_peak_delta(
    samples: Sequence[FootPoseSample],
    event_time_s: float,
    side: FootLabel,
    calibration: TreadmillAxisCalibration | None = None,
) -> float:
    values = []
    for sample in samples:
        hip, _, _ = _core_points(sample, side)
        foot = sample.left_foot_index if side is FootLabel.LEFT else sample.right_foot_index
        if foot.quality < 0.60:
            continue
        knee, ankle = _core_points(sample, side)[1:]
        if calibration is None:
            leg_length = _distance(hip, knee) + _distance(knee, ankle)
            distance = _distance(hip, foot)
        else:
            leg_length = _distance_px(hip, knee, calibration) + _distance_px(
                knee, ankle, calibration
            )
            distance = _distance_px(hip, foot, calibration)
        values.append((sample.timestamp_s, distance / max(leg_length, 1e-6)))
    if not values:
        return math.nan
    return max(values, key=lambda item: item[1])[0] - event_time_s


def _identity_anomaly(samples: Sequence[FootPoseSample]) -> str | None:
    # Online and Replay samples carry session-scoped, causal identity results.
    # Raw standalone callers still receive a trusted-track check within the window.
    analyzer = LegIdentityAnalyzer()
    for sample in samples:
        if sample.identity_reject_reason is not None:
            if sample.identity_reject_reason:
                return sample.identity_reject_reason
            continue
        result = analyzer.update(sample)
        if result.state is LegIdentityState.AMBIGUOUS:
            return result.reason
    return None


def _median_vertical_axis(samples: Sequence[FootPoseSample]) -> tuple[float, float]:
    if not samples:
        raise ValueError("calibration_pose_unavailable")
    values = []
    for sample in samples:
        pelvis = (
            (sample.left_hip.x + sample.right_hip.x) / 2.0,
            (sample.left_hip.y + sample.right_hip.y) / 2.0,
        )
        ankle = (
            (sample.left_ankle.x + sample.right_ankle.x) / 2.0,
            (sample.left_ankle.y + sample.right_ankle.y) / 2.0,
        )
        values.append(_subtract(ankle, pelvis))
    return median(value[0] for value in values), median(value[1] for value in values)


def _core_points(
    sample: FootPoseSample, side: FootLabel
) -> tuple[Landmark, Landmark, Landmark]:
    if side is FootLabel.LEFT:
        return sample.left_hip, sample.left_knee, sample.left_ankle
    return sample.right_hip, sample.right_knee, sample.right_ankle


def _core_quality(sample: FootPoseSample, side: FootLabel) -> float:
    return min(point.quality for point in _core_points(sample, side))


def _unknown_with_diagnostics(
    event_id: int,
    event_time_s: float,
    reason: str,
    diagnostics: dict[str, object],
) -> VisionDecision:
    return VisionDecision(
        event_id,
        FootLabel.UNKNOWN,
        0.0,
        reason,
        event_time_s,
        classifier_diagnostics=diagnostics,
    )


def _unknown_with_evidence(
    event_id: int,
    event_time_s: float,
    reason: str,
    evidence: dict[FootLabel, float],
    diagnostics: dict[str, object],
    candidate: FootLabel,
) -> VisionDecision:
    return VisionDecision(
        event_id,
        FootLabel.UNKNOWN,
        evidence[candidate],
        reason,
        event_time_s,
        candidate_label=candidate,
        left_evidence=evidence[FootLabel.LEFT],
        right_evidence=evidence[FootLabel.RIGHT],
        classifier_diagnostics=diagnostics,
    )


def _linear_slope(values: Sequence[tuple[float, float]]) -> float:
    if len(values) < 2:
        return 0.0
    mean_t = sum(item[0] for item in values) / len(values)
    mean_v = sum(item[1] for item in values) / len(values)
    denominator = sum((item[0] - mean_t) ** 2 for item in values)
    if denominator <= 1e-12:
        return 0.0
    return sum((t - mean_t) * (value - mean_v) for t, value in values) / denominator


def _unit(value: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(*value)
    if length <= 1e-6:
        raise ValueError("calibration_axis_too_short")
    return value[0] / length, value[1] / length


def _subtract(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return a[0] - b[0], a[1] - b[1]


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _distance(a: Landmark, b: Landmark) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _distance_px(
    a: Landmark, b: Landmark, calibration: TreadmillAxisCalibration
) -> float:
    return math.hypot(
        (a.x - b.x) * calibration.frame_width,
        (a.y - b.y) * calibration.frame_height,
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


__all__ = [
    "LANDING_V2_ENTRYPOINT",
    "LANDING_V2_VERSION",
    "LandingV2Classifier",
    "LandingV2Config",
    "TreadmillAxisCalibration",
    "classify_landing_v2",
]
