"""Session-local mapping from camera stream time to the host monotonic clock."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum
from statistics import median
from typing import Sequence


class ClockSyncStatus(str, Enum):
    WARMING_UP = "warming_up"
    READY = "ready"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class ClockSyncSnapshot:
    status: ClockSyncStatus
    aligned_time_s: float | None = None
    offset_ms: float | None = None
    uncertainty_ms: float | None = None
    sample_period_ms: float | None = None
    reason: str = "warming_up"
    warmup_ms: float | None = None


class CameraClockSynchronizer:
    """Freeze a robust DirectShow-to-``perf_counter`` offset per session."""

    def __init__(
        self,
        *,
        min_samples: int = 30,
        min_span_s: float = 0.8,
        max_uncertainty_ms: float = 40.0,
        drift_window_s: float = 10.0,
        max_drift_ms: float = 40.0,
    ) -> None:
        if min_samples < 2:
            raise ValueError("min_samples must be at least 2")
        if min_span_s <= 0:
            raise ValueError("min_span_s must be positive")
        if max_uncertainty_ms <= 0:
            raise ValueError("max_uncertainty_ms must be positive")
        if drift_window_s <= 0:
            raise ValueError("drift_window_s must be positive")
        if max_drift_ms <= 0:
            raise ValueError("max_drift_ms must be positive")
        self.min_samples = min_samples
        self.min_span_s = min_span_s
        self.max_uncertainty_ms = max_uncertainty_ms
        self.drift_window_s = drift_window_s
        self.max_drift_ms = max_drift_ms
        self.reset()

    @property
    def snapshot(self) -> ClockSyncSnapshot:
        return self._snapshot

    @property
    def sample_count(self) -> int:
        return self._sample_count

    @property
    def history_sample_count(self) -> int:
        return len(self._pairs)

    def reset(self) -> None:
        self._pairs: deque[tuple[float, float]] = deque()
        self._sample_count = 0
        self._offset_s: float | None = None
        self._first_callback_time_s: float | None = None
        self._warmup_ms: float | None = None
        self._ready_sample_time_s: float | None = None
        self._last_frame_index: int | None = None
        self._last_sample_time_s: float | None = None
        self._last_aligned_time_s: float | None = None
        self._snapshot = ClockSyncSnapshot(ClockSyncStatus.WARMING_UP)

    def observe(
        self,
        sample_time_s: float,
        callback_time_s: float,
        *,
        frame_index: int | None = None,
    ) -> ClockSyncSnapshot:
        if self._snapshot.status is ClockSyncStatus.DEGRADED:
            return self._snapshot
        if not _finite_non_negative(sample_time_s) or not math.isfinite(callback_time_s):
            return self._degrade("invalid_timestamp")
        if frame_index is not None:
            if not isinstance(frame_index, int) or frame_index < 0:
                return self._degrade("invalid_frame_index")
            if (
                self._last_frame_index is not None
                and frame_index <= self._last_frame_index
            ):
                return self._degrade("non_monotonic_frame_index")
        if (
            self._last_sample_time_s is not None
            and sample_time_s <= self._last_sample_time_s
        ):
            return self._degrade("non_monotonic_sample_time")

        if self._first_callback_time_s is None:
            self._first_callback_time_s = callback_time_s
        if frame_index is not None:
            self._last_frame_index = frame_index
        self._last_sample_time_s = sample_time_s
        self._pairs.append((sample_time_s, callback_time_s))
        self._sample_count += 1
        sample_period_ms = _sample_period_ms(self._pairs)

        if self._offset_s is None:
            span_s = self._pairs[-1][0] - self._pairs[0][0]
            if len(self._pairs) < self.min_samples or span_s < self.min_span_s:
                self._snapshot = ClockSyncSnapshot(
                    ClockSyncStatus.WARMING_UP,
                    sample_period_ms=sample_period_ms,
                    warmup_ms=(
                        (callback_time_s - self._first_callback_time_s) * 1000.0
                    ),
                )
                return self._snapshot

            offsets = [callback - sample for sample, callback in self._pairs]
            offset_s = _percentile(offsets, 0.05)
            uncertainty_ms = _offset_spread_ms(offsets)
            if uncertainty_ms > self.max_uncertainty_ms:
                return self._degrade(
                    "clock_uncertainty_exceeded",
                    offset_s=offset_s,
                    uncertainty_ms=uncertainty_ms,
                    sample_period_ms=sample_period_ms,
                )
            self._offset_s = offset_s
            self._warmup_ms = (
                (callback_time_s - self._first_callback_time_s) * 1000.0
            )
            self._ready_sample_time_s = sample_time_s

        offset_s = self._offset_s
        assert offset_s is not None
        self._prune_history(sample_time_s)
        sample_period_ms = _sample_period_ms(self._pairs)
        aligned_time_s = sample_time_s + offset_s
        if (
            self._last_aligned_time_s is not None
            and aligned_time_s <= self._last_aligned_time_s
        ):
            return self._degrade("non_monotonic_aligned_time")

        recent_pairs = self._recent_pairs(sample_time_s)
        recent_offsets = [callback - sample for sample, callback in recent_pairs]
        uncertainty_ms = _offset_spread_ms(recent_offsets)
        if uncertainty_ms > self.max_uncertainty_ms:
            return self._degrade(
                "clock_uncertainty_exceeded",
                offset_s=offset_s,
                uncertainty_ms=uncertainty_ms,
                sample_period_ms=sample_period_ms,
            )

        ready_at = self._ready_sample_time_s
        if ready_at is not None and sample_time_s - ready_at >= self.drift_window_s:
            tail_start_s = sample_time_s - self.drift_window_s / 2.0
            tail_offsets = [
                callback - sample
                for sample, callback in recent_pairs
                if sample >= tail_start_s
            ]
            recent_offset_s = _percentile(tail_offsets, 0.05)
            drift_ms = abs(recent_offset_s - offset_s) * 1000.0
            if drift_ms > self.max_drift_ms:
                return self._degrade(
                    "clock_drift_exceeded",
                    offset_s=offset_s,
                    uncertainty_ms=uncertainty_ms,
                    sample_period_ms=sample_period_ms,
                )

        self._last_aligned_time_s = aligned_time_s
        self._snapshot = ClockSyncSnapshot(
            status=ClockSyncStatus.READY,
            aligned_time_s=aligned_time_s,
            offset_ms=offset_s * 1000.0,
            uncertainty_ms=uncertainty_ms,
            sample_period_ms=sample_period_ms,
            reason="ready",
            warmup_ms=self._warmup_ms,
        )
        return self._snapshot

    def _recent_pairs(self, sample_time_s: float) -> list[tuple[float, float]]:
        cutoff_s = sample_time_s - self.drift_window_s
        return [pair for pair in self._pairs if pair[0] >= cutoff_s]

    def _prune_history(self, sample_time_s: float) -> None:
        cutoff_s = sample_time_s - self.drift_window_s
        while self._pairs and self._pairs[0][0] < cutoff_s:
            self._pairs.popleft()

    def _degrade(
        self,
        reason: str,
        *,
        offset_s: float | None = None,
        uncertainty_ms: float | None = None,
        sample_period_ms: float | None = None,
    ) -> ClockSyncSnapshot:
        effective_offset_s = self._offset_s if offset_s is None else offset_s
        previous = self._snapshot
        if uncertainty_ms is None:
            uncertainty_ms = previous.uncertainty_ms
        if sample_period_ms is None:
            sample_period_ms = previous.sample_period_ms
        self._snapshot = ClockSyncSnapshot(
            status=ClockSyncStatus.DEGRADED,
            offset_ms=(
                effective_offset_s * 1000.0
                if effective_offset_s is not None
                else None
            ),
            uncertainty_ms=uncertainty_ms,
            sample_period_ms=sample_period_ms,
            reason=reason,
            warmup_ms=(
                self._warmup_ms
                if self._warmup_ms is not None
                else previous.warmup_ms
            ),
        )
        return self._snapshot


def _finite_non_negative(value: float) -> bool:
    return math.isfinite(value) and value >= 0.0


def _sample_period_ms(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    ordered = list(pairs)
    periods = [
        current[0] - previous[0]
        for previous, current in zip(ordered, ordered[1:])
    ]
    return median(periods) * 1000.0


def _offset_spread_ms(offsets: list[float]) -> float:
    if len(offsets) < 2:
        return 0.0
    return (_percentile(offsets, 0.95) - _percentile(offsets, 0.05)) * 1000.0


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
