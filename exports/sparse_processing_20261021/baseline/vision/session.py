"""Persistent, failure-tolerant vision session data contracts.

The recorder deliberately has no Qt, camera, USB, or MediaPipe dependency.  A
real-time callback only enqueues a small Python object; one daemon writer owns
all session files and reports failures without raising into the producer.
"""

from __future__ import annotations

import csv
import atexit
import json
import logging
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .foot_reference import (
    LANDING_CLASSIFIER_ENTRYPOINT,
    LANDING_CLASSIFIER_VERSION,
    FootPoseSample,
    Landmark,
)


log = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^(?P<date>\d{8})_(?P<number>\d{3,})$")
PERSISTED_LABELS = {"Left", "Right", "Unknown", "Skip"}

CONTACT_FIELDS = (
    "event_id",
    "contact_timestamp",
    "camera_sample_timestamp",
    "camera_aligned_timestamp",
    "camera_event_delta_ms",
    "original_grating_label",
    "raw_device_symbol",
    "raw_device_label",
    "effective_device_label",
    "final_label",
    "visual_label",
    "left_evidence",
    "right_evidence",
    "visual_raw_label",
    "visual_raw_score",
    "reject_reason",
    "raw_reason",
    "device_anomaly",
    "anomaly_reasons",
    "phase_suspect_trigger",
    "phase_offset",
    "phase_epoch",
    "phase_action",
    "suspect_start_event_id",
    "first_mismatch_device_label",
    "first_mismatch_visual_label",
    "pending_contact_count",
    "suspect_unknown_count",
    "phase_flip_reason",
    "phase_flip_start_event_id",
    "phase_flip_confirm_event_id",
    "sync_state",
    "sync_uncertainty_ms",
    "sync_offset_ms",
    "pre_pose_count",
    "post_pose_count",
    "max_pose_gap_ms",
    "left_observation_quality",
    "right_observation_quality",
    "left_contact_evidence",
    "right_contact_evidence",
    "left_peak_phase",
    "right_peak_phase",
    "left_velocity_turn",
    "right_velocity_turn",
    "left_post_backward",
    "right_post_backward",
    "left_pre_velocity",
    "right_pre_velocity",
    "left_post_velocity",
    "right_post_velocity",
    "left_longitudinal_peak_time_delta",
    "right_longitudinal_peak_time_delta",
    "left_hip_foot_distance_peak_time_delta",
    "right_hip_foot_distance_peak_time_delta",
    "calibration_status",
    "basis_determinant",
    "forward_axis_angle_degrees",
    "classifier_version",
    "classifier_entrypoint",
    "project_mode",
    "event_role",
    "source_contact_id",
    "valid_for_benchmark",
    "scenario",
)


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    session_json: Path
    pose_frames: Path
    contact_events: Path
    annotations: Path
    video: Path
    video_index: Path

    @classmethod
    def from_root(cls, root: Path) -> "SessionPaths":
        return cls(
            root=root,
            session_json=root / "session.json",
            pose_frames=root / "pose_frames.jsonl",
            contact_events=root / "contact_events.csv",
            annotations=root / "annotations.csv",
            video=root / "video.mjpg",
            video_index=root / "video.csv",
        )


def make_session_id(root: Path, now: datetime | None = None) -> str:
    """Return the next collision-free ``YYYYMMDD_NNN`` directory name."""

    now = now or datetime.now()
    date_text = now.strftime("%Y%m%d")
    used = []
    if root.exists():
        for child in root.iterdir():
            if not child.is_dir():
                continue
            match = SESSION_ID_RE.match(child.name)
            if match and match.group("date") == date_text:
                used.append(int(match.group("number")))
    return f"{date_text}_{max(used, default=0) + 1:03d}"


def normalize_label(value: Any, *, allow_skip: bool = False) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "left": "Left",
        "right": "Right",
        "unknown": "Unknown",
        "both": "Unknown",
        "skip": "Skip",
        "": "",
    }
    normalized = mapping.get(text, "")
    if normalized == "Skip" and not allow_skip:
        return ""
    return normalized


def canonical_reject_reason(raw_reason: str | None, raw_label: str | None) -> str:
    reason = str(raw_reason or "none").strip()
    if reason in {"clock_sync_degraded", "clock_sync_unavailable", "sync_degraded"}:
        return "sync_degraded"
    if str(raw_label or "").lower() == "both":
        return "identity_ambiguous"
    aliases = {
        "no_pose_samples": "insufficient_pose_samples",
        "insufficient_landing_samples": "insufficient_pose_samples",
        "pose_window_unavailable": "insufficient_pose_samples",
        "window_inconsistent": "identity_ambiguous",
        "confidence_below_threshold": "identity_ambiguous",
        "contact_foot_not_stable": "insufficient_motion",
        "decision_timeout": "timeout",
        "evidence_below_threshold": "insufficient_motion",
        "evidence_margin_too_small": "identity_ambiguous",
        "pose_gap_too_large": "insufficient_pose_samples",
        "identity_anomaly": "identity_ambiguous",
    }
    if reason in aliases:
        return aliases[reason]
    if reason in {
        "none",
        "landmarks_not_visible",
        "insufficient_motion",
        "no_landing_motion",
        "timeout",
        "calibration_required",
        "calibration_basis_degenerate",
    }:
        return reason
    if str(raw_label or "").lower() in {"left", "right"} and (
        reason.endswith("_foot_descended_and_settled")
        or reason.endswith("_foot_lower_and_stable")
    ):
        return "none"
    return "other"


def landmark_to_dict(point: Landmark | None) -> dict[str, float] | None:
    if point is None:
        return None
    return {
        "x": point.x,
        "y": point.y,
        "z": point.z,
        "visibility": point.visibility,
        "presence": point.presence,
    }


def pose_sample_to_record(
    sample: FootPoseSample | None,
    *,
    frame_index: int | None,
    camera_sample_timestamp: float | None,
    perf_counter_timestamp: float,
    inference_start_timestamp: float,
    inference_end_timestamp: float,
    error: str | None = None,
) -> dict[str, Any]:
    points = tuple(sample.landmarks_33 or ()) if sample is not None else ()
    return {
        "frame_index": frame_index,
        "camera_sample_timestamp": camera_sample_timestamp,
        "perf_counter_timestamp": perf_counter_timestamp,
        "inference_start_timestamp": inference_start_timestamp,
        "inference_end_timestamp": inference_end_timestamp,
        "inference_latency_ms": (inference_end_timestamp - inference_start_timestamp) * 1000.0,
        "pose_available": sample is not None,
        "landmarks": [landmark_to_dict(point) for point in points],
        "error": error,
    }


def _git_metadata() -> dict[str, Any]:
    for path in (
        Path(getattr(sys, "_MEIPASS", "")) / "build_info.json"
        if getattr(sys, "_MEIPASS", None)
        else None,
        Path(__file__).resolve().parents[1] / "build_info.json",
    ):
        if path is None or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return {
                "git_commit": str(value.get("git_commit") or "unknown"),
                "git_dirty": value.get("git_dirty", "unknown"),
            }
        except Exception:
            pass
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1.0,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
                timeout=1.0,
            ).stdout.strip()
        )
        return {"git_commit": commit or "unknown", "git_dirty": dirty}
    except Exception:
        return {"git_commit": "unknown", "git_dirty": "unknown"}


class VisionSessionRecorder:
    """Asynchronous JSONL/CSV writer for one vision session."""

    def __init__(
        self,
        output_root: str | Path = "data/vision_sessions",
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        clock: callable = time.perf_counter,
    ) -> None:
        root = Path(output_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        selected_id = session_id or make_session_id(root)
        session_root = root / selected_id
        if session_root.exists():
            if session_id is not None:
                raise FileExistsError(f"vision session already exists: {session_root}")
            selected_id = make_session_id(root)
            session_root = root / selected_id
        session_root.mkdir(parents=False, exist_ok=False)
        self.paths = SessionPaths.from_root(session_root)
        self._clock = clock
        self._lock = threading.Lock()
        self._errors: list[dict[str, Any]] = []
        self._writer_failures: dict[str, str] = {}
        self._closed = False
        self._queue: queue.Queue[tuple[str, Any] | None] = queue.Queue(maxsize=4096)
        self._files: dict[str, Any] = {}
        self._csv_writers: dict[str, csv.DictWriter] = {}
        git_info = _git_metadata()
        base = {
            "session_id": selected_id,
            "status": "recording",
            "start_time": datetime.now().astimezone().isoformat(),
            "perf_counter_start_timestamp": clock(),
            "camera_name": "TinySE",
            "camera_resolution": None,
            "camera_fps": None,
            "mediapipe_model": "Pose Landmarker Full",
            "mediapipe_mode": "VIDEO",
            "pose_inference_interval_ms": None,
            "classifier_version": LANDING_CLASSIFIER_VERSION,
            "classifier_entrypoint": LANDING_CLASSIFIER_ENTRYPOINT,
            "sync_method": "TinySE DirectShow sample clock → perf_counter offset",
            "software_version": git_info["git_commit"],
            "git_commit": git_info["git_commit"],
            "git_dirty": git_info["git_dirty"],
            "scenario": "normal",
            "recording": {"status": "not_started", "written": 0, "dropped": 0, "queue_peak": 0, "errors": []},
            "writers": {
                "pose": {"written": 0, "dropped": 0, "queue_peak": 0, "errors": []},
                "contact": {"written": 0, "dropped": 0, "queue_peak": 0, "errors": []},
                "video": {"written": 0, "dropped": 0, "queue_peak": 0, "errors": []},
            },
            "errors": [],
        }
        if metadata:
            _deep_update(base, metadata)
        self._metadata = base
        self._open_files()
        self._write_metadata()
        self._thread = threading.Thread(target=self._run, name="VisionSessionWriter", daemon=True)
        self._thread.start()
        atexit.register(self._close_at_exit)

    @property
    def session_id(self) -> str:
        return str(self._metadata["session_id"])

    @property
    def session_root(self) -> Path:
        return self.paths.root

    def update_metadata(self, **values: Any) -> None:
        with self._lock:
            _deep_update(self._metadata, values)

    def add_error(self, component: str, message: str) -> None:
        item = {"component": component, "message": str(message), "timestamp": time.time()}
        with self._lock:
            self._errors.append(item)
            self._metadata.setdefault("errors", []).append(item)
            writer = self._metadata.setdefault("writers", {}).get(component)
            if isinstance(writer, dict):
                writer.setdefault("errors", []).append(str(message))
        log.error("vision_recording_failed component=%s: %s", component, message)

    def record_pose(self, record: dict[str, Any]) -> None:
        self._enqueue("pose", record)

    def record_contact(self, record: dict[str, Any]) -> None:
        self._enqueue("contact", record)

    def _enqueue(self, kind: str, value: Any) -> None:
        if self._closed or kind in self._writer_failures:
            return
        try:
            self._queue.put_nowait((kind, value))
            with self._lock:
                writer = self._metadata["writers"][kind]
                writer["queue_peak"] = max(
                    int(writer.get("queue_peak", 0)), self._queue.qsize()
                )
        except queue.Full:
            self.add_error(kind, "writer queue full")
            with self._lock:
                writer = self._metadata["writers"][kind]
                writer["dropped"] = int(writer.get("dropped", 0)) + 1

    def close(self, *, recording: dict[str, Any] | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            atexit.unregister(self._close_at_exit)
        except Exception:
            pass
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            self.add_error("writer", "writer thread did not stop before timeout")
        for file in self._files.values():
            try:
                file.close()
            except Exception:
                pass
        with self._lock:
            if recording is not None:
                video_writer = self._metadata["writers"]["video"]
                existing_video_errors = list(video_writer.get("errors", []))
                _deep_update(self._metadata, {"recording": recording})
                _deep_update(video_writer, recording)
                video_writer["errors"] = existing_video_errors + list(
                    recording.get("errors", [])
                )
            for kind, message in self._writer_failures.items():
                self._metadata.setdefault("errors", []).append(
                    {"component": kind, "message": message, "timestamp": time.time()}
                )
            self._metadata["end_time"] = datetime.now().astimezone().isoformat()
            self._metadata["writer_failures"] = dict(self._writer_failures)
            writer_incomplete = any(
                int(writer.get("dropped", 0)) > 0 or bool(writer.get("errors"))
                for writer in self._metadata.get("writers", {}).values()
            )
            video_complete = self._metadata.get("recording", {}).get("status") == "complete"
            self._metadata["status"] = (
                "complete"
                if video_complete and not self._writer_failures and not writer_incomplete
                else "partial"
            )
            self._write_metadata()

    def _close_at_exit(self) -> None:
        self.close(
            recording={
                "status": "partial",
                "written": 0,
                "dropped": 0,
                "queue_peak": 0,
                "errors": ["process exited before normal recording finalization"],
            }
        )

    def _open_files(self) -> None:
        try:
            self._files["pose"] = self.paths.pose_frames.open("w", encoding="utf-8")
        except Exception as exc:
            self._writer_failures["pose"] = str(exc)
            self.add_error("pose", str(exc))
        try:
            self._files["contact"] = self.paths.contact_events.open("w", newline="", encoding="utf-8")
            self._csv_writers["contact"] = csv.DictWriter(
                self._files["contact"], fieldnames=CONTACT_FIELDS, extrasaction="ignore"
            )
            self._csv_writers["contact"].writeheader()
            self._files["contact"].flush()
        except Exception as exc:
            self._writer_failures["contact"] = str(exc)
            self.add_error("contact", str(exc))
        try:
            with self.paths.annotations.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=("event_id", "ground_truth", "valid", "scenario", "note"),
                )
                writer.writeheader()
        except Exception as exc:
            self.add_error("annotations", str(exc))

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            kind, value = item
            if kind in self._writer_failures:
                continue
            try:
                if kind == "pose":
                    file = self._files["pose"]
                    file.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
                    file.flush()
                elif kind == "contact":
                    self._csv_writers["contact"].writerow(value)
                    self._files["contact"].flush()
                with self._lock:
                    writer = self._metadata["writers"][kind]
                    writer["written"] = int(writer.get("written", 0)) + 1
            except Exception as exc:
                self._writer_failures[kind] = str(exc)
                self.add_error(kind, str(exc))

    def _write_metadata(self) -> None:
        temp = self.paths.session_json.with_suffix(".json.tmp")
        try:
            temp.write_text(json.dumps(self._metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.paths.session_json)
        except Exception as exc:
            log.error("vision_recording_failed component=session_json: %s", exc)


class NullVisionSessionRecorder:
    """No-op fallback used when creating a diagnostics package is impossible."""

    def __init__(self, output_root: str | Path = "data/vision_sessions") -> None:
        self.paths = SessionPaths.from_root(Path(output_root).expanduser().resolve())
        self._errors: list[dict[str, str]] = []

    @property
    def session_id(self) -> str:
        return "unavailable"

    @property
    def session_root(self) -> Path:
        return self.paths.root

    def update_metadata(self, **values: Any) -> None:
        return None

    def add_error(self, component: str, message: str) -> None:
        self._errors.append({"component": component, "message": str(message)})
        log.error("vision_recording_failed component=%s: %s", component, message)

    def record_pose(self, record: dict[str, Any]) -> None:
        return None

    def record_contact(self, record: dict[str, Any]) -> None:
        return None

    def close(self, *, recording: dict[str, Any] | None = None) -> None:
        return None


def load_session(path: str | Path) -> tuple[dict[str, Any], SessionPaths]:
    root = Path(path).expanduser().resolve()
    metadata = json.loads((root / "session.json").read_text(encoding="utf-8"))
    return metadata, SessionPaths.from_root(root)


def software_version_metadata() -> dict[str, Any]:
    return _git_metadata()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _deep_update(target: dict[str, Any], values: dict[str, Any]) -> None:
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


__all__ = [
    "CONTACT_FIELDS",
    "PERSISTED_LABELS",
    "SessionPaths",
    "VisionSessionRecorder",
    "NullVisionSessionRecorder",
    "canonical_reject_reason",
    "landmark_to_dict",
    "load_csv",
    "load_jsonl",
    "load_session",
    "make_session_id",
    "normalize_label",
    "pose_sample_to_record",
    "software_version_metadata",
]
