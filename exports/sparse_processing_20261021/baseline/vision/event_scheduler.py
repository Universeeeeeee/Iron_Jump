"""Session-scoped event windows with a monotonic MediaPipe VIDEO cursor."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import replace
from typing import Callable, Iterable

from .foot_reference import (
    FootPoseSample,
    FrameSample,
    TouchEvent,
    VisionConfig,
    VisionDecision,
    VisionWindowDiagnostics,
    unknown_decision,
)
from .leg_identity import LegIdentityAnalyzer


InferPose = Callable[[object, int], FootPoseSample | None]
ClassifyEvent = Callable[
    [int, float, list[FootPoseSample], VisionConfig], VisionDecision
]


class EventWindowScheduler:
    """Own the ordered frame/event timeline for one vision session."""

    def __init__(self, config: VisionConfig | None = None) -> None:
        self.config = config or VisionConfig()
        self.reset()

    @property
    def pending_event_count(self) -> int:
        return len(self._events)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def pose_cache_count(self) -> int:
        return len(self._pose_cache)

    @property
    def inference_cursor_ms(self) -> int | None:
        return self._inference_cursor_ms

    @property
    def inference_attempt_count(self) -> int:
        return len(self._inference_attempts)

    def reset(self) -> None:
        self._identity = LegIdentityAnalyzer()
        self._frames: list[FrameSample] = []
        self._events: list[TouchEvent] = []
        self._pose_cache: dict[int, FootPoseSample] = {}
        self._inference_attempts: dict[int, bool] = {}
        self._inference_cursor_ms: int | None = None
        self._evidence_cutoff_s = float('-inf')
        self._immediate: deque[VisionDecision] = deque()

    def add_frame(self, frame: object, captured_at_s: float) -> None:
        if captured_at_s < 0:
            return
        sample = FrameSample(captured_at_s=captured_at_s, frame=frame)
        positions = [item.captured_at_s for item in self._frames]
        self._frames.insert(bisect_right(positions, captured_at_s), sample)
        self._prune_frames()

    def add_frames(self, frames: Iterable[FrameSample]) -> None:
        for sample in frames:
            self.add_frame(sample.frame, sample.captured_at_s)

    def add_event(
        self,
        event_id: int,
        event_time_s: float,
        *,
        submitted_at_s: float,
    ) -> None:
        if event_time_s < 0:
            self._immediate.append(
                unknown_decision(event_id, event_time_s, "invalid_event_timestamp")
            )
            return
        if any(item.event_id == event_id for item in self._events):
            self._immediate.append(
                unknown_decision(event_id, event_time_s, "duplicate_event_id")
            )
            return
        if len(self._events) >= self.config.max_events:
            self._immediate.append(
                unknown_decision(event_id, event_time_s, "event_queue_full")
            )
            return
        event = TouchEvent(event_id, event_time_s, submitted_at_s)
        positions = [(item.event_time_s, item.event_id) for item in self._events]
        index = bisect_right(positions, (event.event_time_s, event.event_id))
        self._events.insert(index, event)

    def process_ready(
        self,
        infer_pose: InferPose,
        classify_event: ClassifyEvent,
        *,
        now_s: float,
        decision_clock: Callable[[], float] | None = None,
    ) -> list[VisionDecision]:
        """Return ready results promptly; callers may pump again for later windows."""
        decisions = list(self._immediate)
        self._immediate.clear()
        decisions.extend(self._decide_ready(classify_event, now_s, decision_clock))
        if decisions:
            return decisions
        # Publish a ready decision before unrelated inference can delay delivery.
        for _ in self._infer_new_frames(infer_pose):
            decisions.extend(self._decide_ready(classify_event, now_s, decision_clock))
            if decisions:
                return decisions
        return decisions

    def _decide_ready(self, classify_event, now_s, decision_clock):
        decisions = []
        while self._events:
            event = self._events[0]
            start_s = event.event_time_s - self.config.pre_event_ms / 1000.0
            end_s = event.event_time_s + self.config.post_event_ms / 1000.0
            diagnostics = self._window_diagnostics(event.event_time_s, start_s, end_s)
            decision_time_s = self._decision_time(now_s, decision_clock)
            deadline_s = (
                event.event_time_s + self.config.decision_timeout_ms / 1000.0
            )

            # The image count cap does not evict cached pose evidence.
            if self._evidence_cutoff_s > start_s + 1e-6:
                decisions.append(
                    unknown_decision(
                        event.event_id,
                        event.event_time_s,
                        "frame_window_expired",
                        decided_at_s=decision_time_s,
                        diagnostics=diagnostics,
                    )
                )
                self._events.pop(0)
                continue

            if decision_time_s > deadline_s:
                decisions.append(
                    unknown_decision(
                        event.event_id,
                        event.event_time_s,
                        "decision_timeout",
                        decided_at_s=decision_time_s,
                        diagnostics=diagnostics,
                    )
                )
                self._events.pop(0)
                continue

            latest_frame_s = self._frames[-1].captured_at_s if self._frames else None
            if latest_frame_s is None or latest_frame_s < end_s - 1e-6:
                break

            start_ms = round(start_s * 1000.0)
            end_ms = round(end_s * 1000.0)
            # Infer all retained, cadence-eligible inputs within this window first.
            if any(timestamp_ms <= end_ms for _, timestamp_ms in self._inference_frames()):
                break
            samples = [
                sample
                for timestamp_ms, sample in sorted(self._pose_cache.items())
                if start_ms <= timestamp_ms <= end_ms
            ]
            if not samples:
                decision = unknown_decision(
                    event.event_id,
                    event.event_time_s,
                    "pose_window_unavailable",
                    decided_at_s=decision_time_s,
                    diagnostics=diagnostics,
                )
            else:
                decision = classify_event(
                    event.event_id,
                    event.event_time_s,
                    samples,
                    self.config,
                )
                completed_at_s = self._decision_time(now_s, decision_clock)
                if completed_at_s > deadline_s:
                    decision = unknown_decision(event.event_id, event.event_time_s,
                                                "decision_timeout", decided_at_s=completed_at_s,
                                                diagnostics=diagnostics)
                else:
                    decision = replace(decision, diagnostics=diagnostics, decided_at_s=completed_at_s)
            decisions.append(decision)
            self._events.pop(0)
            break  # Deliver before another classifier can consume this deadline.

        return decisions

    def reject_pending(self, reason: str, *, now_s: float) -> list[VisionDecision]:
        decisions = [
            unknown_decision(
                event.event_id,
                event.event_time_s,
                reason,
                decided_at_s=now_s,
            )
            for event in self._events
        ]
        self._events.clear()
        return decisions

    def _inference_frames(self):
        last_ms = self._inference_cursor_ms
        for sample in self._frames:
            timestamp_ms = round(sample.captured_at_s * 1000.0)
            if last_ms is not None and timestamp_ms <= last_ms:
                continue
            if (
                last_ms is not None
                and timestamp_ms - last_ms < self.config.inference_interval_ms
            ):
                continue
            last_ms = timestamp_ms
            yield sample, timestamp_ms

    def _infer_new_frames(self, infer_pose: InferPose):
        for sample, timestamp_ms in self._inference_frames():
            pose = self._identity.annotate(infer_pose(sample.frame, timestamp_ms))
            self._inference_cursor_ms = timestamp_ms
            self._inference_attempts[timestamp_ms] = pose is not None
            if pose is not None:
                self._pose_cache[timestamp_ms] = pose
            yield timestamp_ms

    @staticmethod
    def _decision_time(
        now_s: float,
        decision_clock: Callable[[], float] | None,
    ) -> float:
        return decision_clock() if decision_clock is not None else now_s

    def _window_diagnostics(
        self,
        event_time_s: float,
        start_s: float,
        end_s: float,
    ) -> VisionWindowDiagnostics:
        start_ms = round(start_s * 1000.0)
        end_ms = round(end_s * 1000.0)
        attempt_timestamps = [
            timestamp_ms
            for timestamp_ms in sorted(self._inference_attempts)
            if start_ms <= timestamp_ms <= end_ms
        ]
        pose_samples = [
            sample
            for timestamp_ms, sample in sorted(self._pose_cache.items())
            if start_ms <= timestamp_ms <= end_ms
        ]
        pose_timestamps = [sample.timestamp_s for sample in pose_samples]
        gaps_ms = [
            (current - previous) * 1000.0
            for previous, current in zip(pose_timestamps, pose_timestamps[1:])
        ]
        return VisionWindowDiagnostics(
            frame_count=sum(
                start_s <= sample.captured_at_s <= end_s for sample in self._frames
            ),
            inference_attempts=len(attempt_timestamps),
            pose_total=len(pose_samples),
            pose_before=sum(
                sample.timestamp_s <= event_time_s for sample in pose_samples
            ),
            pose_after=sum(
                sample.timestamp_s >= event_time_s for sample in pose_samples
            ),
            max_pose_gap_ms=max(gaps_ms) if gaps_ms else None,
        )

    def _prune_frames(self) -> None:
        if not self._frames:
            return
        cutoff_s = self._frames[-1].captured_at_s - self.config.frame_buffer_ms / 1000.0
        self._evidence_cutoff_s = max(self._evidence_cutoff_s, cutoff_s)
        self._frames = [item for item in self._frames if item.captured_at_s >= cutoff_s]
        if len(self._frames) > self.config.max_frames:
            self._frames = self._frames[-self.config.max_frames :]
        cutoff_ms = round(cutoff_s * 1000.0)
        self._pose_cache = {
            timestamp_ms: sample
            for timestamp_ms, sample in self._pose_cache.items()
            if timestamp_ms >= cutoff_ms
        }
        self._inference_attempts = {
            timestamp_ms: succeeded
            for timestamp_ms, succeeded in self._inference_attempts.items()
            if timestamp_ms >= cutoff_ms
        }
