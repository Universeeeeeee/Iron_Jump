"""Conservative temporal validation of MediaPipe anatomical leg identities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .foot_reference import FootPoseSample, Landmark


class LegIdentityState(str, Enum):
    STABLE = "stable"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LegIdentityConfig:
    min_core_quality: float = 0.60
    min_overlap_ratio: float = 0.10
    swap_advantage_ratio: float = 0.12
    max_original_cost_ratio: float = 1.00
    swap_confirm_transitions: int = 2
    recovery_transitions: int = 3


@dataclass(frozen=True)
class LegIdentityResult:
    state: LegIdentityState
    reason: str
    left_quality: float
    right_quality: float
    original_cost: float | None = None
    swapped_cost: float | None = None
    assignment_margin: float | None = None
    swap_suspect_transitions: int = 0
    recovery_transitions: int = 0


class LegIdentityAnalyzer:
    """Check MediaPipe L/R labels without silently swapping them.

    A suspicious assignment is not accepted into the reference tracks. This is
    important: two consecutive swapped frames must both remain inconsistent
    with the last trusted anatomical tracks before the state becomes
    ``AMBIGUOUS``.
    """

    def __init__(self, config: LegIdentityConfig | None = None) -> None:
        self.config = config or LegIdentityConfig()
        self._trusted: FootPoseSample | None = None
        self._prior_trusted: FootPoseSample | None = None
        self._swap_streak = 0
        self._ambiguous = False
        self._recovery_streak = 0

    def reset(self) -> None:
        self._trusted = None
        self._prior_trusted = None
        self._swap_streak = 0
        self._ambiguous = False
        self._recovery_streak = 0

    def update(self, sample: FootPoseSample | None) -> LegIdentityResult:
        if sample is None:
            return self._unavailable("pose_unavailable")

        left_quality = _core_quality(sample, "left")
        right_quality = _core_quality(sample, "right")
        if min(left_quality, right_quality) < self.config.min_core_quality:
            self._swap_streak = 0
            self._recovery_streak = 0
            return LegIdentityResult(
                LegIdentityState.UNAVAILABLE,
                "core_landmarks_low_quality",
                left_quality,
                right_quality,
            )

        leg_scale = _leg_scale(sample)
        if _legs_overlap(sample, leg_scale, self.config.min_overlap_ratio):
            self._ambiguous = True
            self._swap_streak = 0
            self._recovery_streak = 0
            return LegIdentityResult(
                LegIdentityState.AMBIGUOUS,
                "legs_overlap",
                left_quality,
                right_quality,
            )

        previous = self._trusted
        if previous is None:
            self._trusted = sample
            return LegIdentityResult(
                LegIdentityState.UNAVAILABLE,
                "identity_warming_up",
                left_quality,
                right_quality,
            )

        original, swapped = _assignment_costs(
            previous,
            sample,
            leg_scale,
            older=self._prior_trusted,
        )
        margin = original - swapped
        swap_suspected = margin >= self.config.swap_advantage_ratio
        unexplained_jump = (
            original > self.config.max_original_cost_ratio and not swap_suspected
        )

        if swap_suspected:
            self._swap_streak += 1
            self._recovery_streak = 0
            if self._swap_streak >= self.config.swap_confirm_transitions:
                self._ambiguous = True
                reason = "media_pipe_identity_swap_detected"
            else:
                reason = "media_pipe_identity_swap_suspected"
            return LegIdentityResult(
                LegIdentityState.AMBIGUOUS,
                reason,
                left_quality,
                right_quality,
                original,
                swapped,
                margin,
                self._swap_streak,
                self._recovery_streak,
            )

        if unexplained_jump:
            self._ambiguous = True
            self._swap_streak = 0
            self._recovery_streak = 0
            return LegIdentityResult(
                LegIdentityState.AMBIGUOUS,
                "unexplained_landmark_jump",
                left_quality,
                right_quality,
                original,
                swapped,
                margin,
            )

        self._swap_streak = 0
        self._prior_trusted = self._trusted
        self._trusted = sample
        if self._ambiguous:
            self._recovery_streak += 1
            if self._recovery_streak < self.config.recovery_transitions:
                return LegIdentityResult(
                    LegIdentityState.AMBIGUOUS,
                    "identity_recovering",
                    left_quality,
                    right_quality,
                    original,
                    swapped,
                    margin,
                    0,
                    self._recovery_streak,
                )
            self._ambiguous = False
            self._recovery_streak = 0

        return LegIdentityResult(
            LegIdentityState.STABLE,
            "identity_stable",
            left_quality,
            right_quality,
            original,
            swapped,
            margin,
        )

    def _unavailable(self, reason: str) -> LegIdentityResult:
        self._swap_streak = 0
        self._recovery_streak = 0
        return LegIdentityResult(
            LegIdentityState.UNAVAILABLE,
            reason,
            0.0,
            0.0,
        )


def _core(sample: FootPoseSample, side: str) -> tuple[Landmark, Landmark, Landmark]:
    if side == "left":
        return sample.left_hip, sample.left_knee, sample.left_ankle
    return sample.right_hip, sample.right_knee, sample.right_ankle


def _core_quality(sample: FootPoseSample, side: str) -> float:
    return min(point.quality for point in _core(sample, side))


def _leg_scale(sample: FootPoseSample) -> float:
    values = []
    for side in ("left", "right"):
        hip, knee, ankle = _core(sample, side)
        values.append(_distance(hip, knee) + _distance(knee, ankle))
    return max(sum(values) / len(values), 1e-6)


def _legs_overlap(sample: FootPoseSample, scale: float, threshold: float) -> bool:
    left = _core(sample, "left")
    right = _core(sample, "right")
    knee_ratio = _distance(left[1], right[1]) / scale
    ankle_ratio = _distance(left[2], right[2]) / scale
    return knee_ratio < threshold and ankle_ratio < threshold


def _assignment_costs(
    previous: FootPoseSample,
    current: FootPoseSample,
    scale: float,
    *,
    older: FootPoseSample | None = None,
) -> tuple[float, float]:
    previous_left = _core(previous, "left")
    previous_right = _core(previous, "right")
    current_left = _core(current, "left")
    current_right = _core(current, "right")
    older_left = _core(older, "left") if older is not None else None
    older_right = _core(older, "right") if older is not None else None
    original = (
        _track_cost(
            previous_left,
            current_left,
            older=older_left,
            older_time_s=older.timestamp_s if older is not None else None,
            previous_time_s=previous.timestamp_s,
            current_time_s=current.timestamp_s,
        )
        + _track_cost(
            previous_right,
            current_right,
            older=older_right,
            older_time_s=older.timestamp_s if older is not None else None,
            previous_time_s=previous.timestamp_s,
            current_time_s=current.timestamp_s,
        )
    ) / (2.0 * scale)
    swapped = (
        _track_cost(
            previous_left,
            current_right,
            older=older_left,
            older_time_s=older.timestamp_s if older is not None else None,
            previous_time_s=previous.timestamp_s,
            current_time_s=current.timestamp_s,
        )
        + _track_cost(
            previous_right,
            current_left,
            older=older_right,
            older_time_s=older.timestamp_s if older is not None else None,
            previous_time_s=previous.timestamp_s,
            current_time_s=current.timestamp_s,
        )
    ) / (2.0 * scale)
    return original, swapped


def _track_cost(
    previous: tuple[Landmark, Landmark, Landmark],
    current: tuple[Landmark, Landmark, Landmark],
    *,
    older: tuple[Landmark, Landmark, Landmark] | None,
    older_time_s: float | None,
    previous_time_s: float,
    current_time_s: float,
) -> float:
    position = (
        0.25 * _distance(previous[0], current[0])
        + 0.35 * _distance(previous[1], current[1])
        + 0.40 * _distance(previous[2], current[2])
    )
    previous_length = _distance(previous[0], previous[1]) + _distance(
        previous[1], previous[2]
    )
    current_length = _distance(current[0], current[1]) + _distance(
        current[1], current[2]
    )
    prediction = 0.0
    if older is not None and older_time_s is not None:
        previous_dt = previous_time_s - older_time_s
        current_dt = current_time_s - previous_time_s
        if previous_dt > 1e-6 and current_dt > 0.0:
            ratio = min(2.0, current_dt / previous_dt)
            weights = (0.25, 0.35, 0.40)
            for weight, old, last, candidate in zip(
                weights, older, previous, current
            ):
                predicted_x = last.x + (last.x - old.x) * ratio
                predicted_y = last.y + (last.y - old.y) * ratio
                prediction += weight * math.hypot(
                    candidate.x - predicted_x,
                    candidate.y - predicted_y,
                )
    return (
        position
        + 0.20 * abs(current_length - previous_length)
        + 0.25 * prediction
    )


def _distance(first: Landmark, second: Landmark) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)


__all__ = [
    "LegIdentityAnalyzer",
    "LegIdentityConfig",
    "LegIdentityResult",
    "LegIdentityState",
]
