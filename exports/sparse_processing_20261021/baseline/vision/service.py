"""Threaded, Qt-independent service for event-triggered foot references."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .event_scheduler import EventWindowScheduler
from .foot_reference import (
    TouchEvent,
    VisionConfig,
    classify_event,
    unknown_decision,
)
from .mediapipe_pose import MediaPipePoseAdapter, VisionUnavailableError


log = logging.getLogger(__name__)


class EventHook:
    """Small thread-safe signal with a Qt-like ``connect`` method."""

    def __init__(self) -> None:
        self._callbacks: list[Callable] = []
        self._lock = threading.Lock()

    def connect(self, callback: Callable) -> None:
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def disconnect(self, callback: Callable) -> None:
        with self._lock:
            self._callbacks = [item for item in self._callbacks if item != callback]

    def emit(self, value) -> None:
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            try:
                callback(value)
            except Exception:
                log.exception("Vision event callback failed")


@dataclass(frozen=True)
class PoseFrameMetadata:
    """Original host callback provenance; independent of the mapped pose time."""

    frame_index: int
    sample_time_s: float
    callback_time_s: float
    decoded_at_s: float | None
    clock_sync_status: str
    clock_sync_uncertainty_ms: float | None
    camera_clock_epoch: int


@dataclass(frozen=True)
class _InferenceInput:
    frame: object
    metadata: PoseFrameMetadata


@dataclass(frozen=True)
class PoseInferenceRecord:
    """Timing and result for one actual MediaPipe inference attempt."""

    frame_timestamp_s: float
    inference_start_timestamp_s: float
    inference_end_timestamp_s: float
    pose: object | None
    error: str | None = None
    frame_metadata: PoseFrameMetadata | None = None


class FootVisionService:
    """Own an isolated pose adapter, scheduler, and bounded input queues."""

    def __init__(
        self,
        config: VisionConfig,
        model_path: str | Path,
        *,
        adapter_factory: Callable[[str | Path], object] = MediaPipePoseAdapter,
        classifier: Callable = classify_event,
        clock: Callable[[], float] = time.perf_counter,
        latest_frame_only: bool = False,
    ) -> None:
        self.config = config
        self.model_path = Path(model_path)
        self.decision_ready = EventHook()
        self.pose_ready = EventHook()
        self.pose_inference_ready = EventHook()
        self.status_changed = EventHook()

        self._adapter_factory = adapter_factory
        self._classifier = classifier
        self._clock = clock
        self._frames: deque[tuple[object, float]] = deque(
            maxlen=1 if latest_frame_only else config.max_frames
        )
        self._events: deque[TouchEvent] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._accepting = False

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    @property
    def queue_depth(self) -> dict[str, int]:
        with self._lock:
            return {"frames": len(self._frames), "events": len(self._events)}

    def start(self) -> None:
        if self.is_running:
            return
        with self._lock:
            self._frames.clear()
            self._events.clear()
            self._accepting = True
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="FootVisionService",
            daemon=True,
        )
        self._thread.start()

    def submit_frame(self, frame: object, captured_at_s: float, *,
                     metadata: PoseFrameMetadata | None = None) -> None:
        with self._lock:
            if not self._accepting:
                return
            if metadata is not None:
                frame = _InferenceInput(frame, metadata)
            self._frames.append((frame, captured_at_s))
        self._wake.set()

    def submit_touch_event(self, event_id: int, event_time_s: float) -> None:
        now_s = self._clock()
        with self._lock:
            if not self._accepting:
                decision = unknown_decision(
                    event_id,
                    event_time_s,
                    "service_not_running",
                    decided_at_s=now_s,
                )
            elif len(self._events) >= self.config.max_events:
                decision = unknown_decision(
                    event_id,
                    event_time_s,
                    "event_queue_full",
                    decided_at_s=now_s,
                )
            else:
                self._events.append(TouchEvent(event_id, event_time_s, now_s))
                decision = None
        if decision is not None:
            self.decision_ready.emit(decision)
        else:
            self._wake.set()

    def stop(self, timeout_s: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        with self._lock:
            self._accepting = False
        self._stop.set()
        self._wake.set()
        if thread is not threading.current_thread():
            thread.join(timeout_s)
        if not thread.is_alive():
            self._thread = None

    def _run(self) -> None:
        scheduler = EventWindowScheduler(self.config)
        adapter = self._adapter_factory(self.model_path)
        unavailable = False
        try:
            try:
                adapter.open()
            except VisionUnavailableError as exc:
                unavailable = True
                self.status_changed.emit(f"unavailable: {exc}")
            except Exception as exc:
                unavailable = True
                self.status_changed.emit(f"unavailable: {exc}")
            else:
                self.status_changed.emit("ready")

            def infer_pose(frame, timestamp_ms):
                metadata = None
                if isinstance(frame, _InferenceInput):
                    frame, metadata = frame.frame, frame.metadata
                inference_start_s = self._clock()
                try:
                    pose = adapter.infer_bgr(frame, timestamp_ms)
                except Exception as exc:
                    inference_end_s = self._clock()
                    self.pose_inference_ready.emit(
                        PoseInferenceRecord(
                            timestamp_ms / 1000.0,
                            inference_start_s,
                            inference_end_s,
                            None,
                            str(exc),
                            metadata,
                        )
                    )
                    raise
                inference_end_s = self._clock()
                self.pose_inference_ready.emit(
                    PoseInferenceRecord(
                        timestamp_ms / 1000.0,
                        inference_start_s,
                        inference_end_s,
                        pose,
                        frame_metadata=metadata,
                    )
                )
                if pose is not None:
                    self.pose_ready.emit(pose)
                return pose

            while not self._stop.is_set():
                frames, events = self._take_inputs()
                now_s = self._clock()
                if unavailable:
                    for event in events:
                        self.decision_ready.emit(
                            unknown_decision(
                                event.event_id,
                                event.event_time_s,
                                "model_unavailable",
                                decided_at_s=now_s,
                            )
                        )
                else:
                    for frame, captured_at_s in frames:
                        scheduler.add_frame(frame, captured_at_s)
                    for event in events:
                        scheduler.add_event(
                            event.event_id,
                            event.event_time_s,
                            submitted_at_s=event.submitted_at_s,
                        )
                    try:
                        decisions = scheduler.process_ready(
                            infer_pose,
                            self._classifier,
                            now_s=now_s,
                            decision_clock=self._clock,
                        )
                    except Exception as exc:
                        unavailable = True
                        self.status_changed.emit(f"inference_error: {exc}")
                        decisions = scheduler.reject_pending(
                            "inference_error", now_s=now_s
                        )
                    for decision in decisions:
                        self.decision_ready.emit(decision)

                if not frames and not events:
                    self._wake.wait(0.01)
                self._wake.clear()
        finally:
            now_s = self._clock()
            for decision in scheduler.reject_pending("service_stopped", now_s=now_s):
                self.decision_ready.emit(decision)
            _, queued_events = self._take_inputs()
            for event in queued_events:
                self.decision_ready.emit(
                    unknown_decision(
                        event.event_id,
                        event.event_time_s,
                        "service_stopped",
                        decided_at_s=now_s,
                    )
                )
            try:
                adapter.close()
            except Exception:
                log.exception("Could not close pose adapter")
            with self._lock:
                self._accepting = False
                self._frames.clear()
                self._events.clear()
            self.status_changed.emit("stopped")

    def _take_inputs(
        self,
    ) -> tuple[list[tuple[object, float]], list[TouchEvent]]:
        with self._lock:
            frames = list(self._frames)
            events = list(self._events)
            self._frames.clear()
            self._events.clear()
        return frames, events
