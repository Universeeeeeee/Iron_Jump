"""Pure offline replay for saved contact events and MediaPipe landmarks."""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .annotations import is_benchmark_event, load_annotations
from .foot_reference import (
    LANDING_CLASSIFIER_ENTRYPOINT,
    LANDING_CLASSIFIER_VERSION,
    FootLabel,
    FootPoseSample,
    Landmark,
    VisionConfig,
    classify_landing_event,
)
from .session import (
    canonical_reject_reason,
    load_csv,
    load_jsonl,
    load_session,
    normalize_label,
    software_version_metadata,
)
from .landing_v2 import (
    LANDING_V2_ENTRYPOINT,
    LANDING_V2_VERSION,
    LandingV2Classifier,
)
from .phase_resync import (
    DevicePhaseInput,
    FootPhaseManager,
    opposite,
)
from .leg_identity import LegIdentityAnalyzer


REPLAY_PRE_MS = 250
REPLAY_POST_MS = 200
HIGH_CONFIDENCE_THRESHOLD = 0.90

REPLAY_FIELDS = (
    "event_id",
    "scenario",
    "ground_truth",
    "prediction",
    "visual_raw_label",
    "confidence",
    "reason",
    "correct",
    "accepted",
    "high_confidence_wrong",
    "pose_samples",
    "raw_device_label",
    "effective_device_label",
    "final_label",
    "visual_label",
    "left_evidence",
    "right_evidence",
    "phase_offset",
    "phase_epoch",
    "phase_action",
    "phase_flip_start_event_id",
    "phase_flip_confirm_event_id",
)


def replay_session(
    session_root: str | Path,
    *,
    classifier=classify_landing_event,
    mode: str = "landing-v1",
    inject_phase_slip_at: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata, paths = load_session(session_root)
    events = load_csv(paths.contact_events)
    annotations = load_annotations(paths.annotations)
    identity = LegIdentityAnalyzer()
    samples = []
    for record in sorted(
        load_jsonl(paths.pose_frames),
        key=lambda item: float(item["perf_counter_timestamp"]),
    ):
        sample = pose_record_to_sample(record)
        if mode == "visual-evidence-v2":
            sample = identity.annotate(sample)
        if sample is not None:
            samples.append(sample)
    config_values = dict(metadata.get("vision_config") or {})
    config_values["pre_event_ms"] = REPLAY_PRE_MS
    config_values["post_event_ms"] = REPLAY_POST_MS
    allowed = set(VisionConfig.__dataclass_fields__)
    config = VisionConfig(**{key: value for key, value in config_values.items() if key in allowed})

    if mode == "phase-resync-v1":
        return replay_phase_resync(
            events,
            inject_phase_slip_at=inject_phase_slip_at,
            metadata=metadata,
        )
    if mode not in {"landing-v1", "visual-evidence-v2"}:
        raise ValueError(f"unsupported replay mode: {mode}")
    if mode == "visual-evidence-v2":
        calibration = metadata.get("treadmill_axis_calibration") or {}
        resolution = metadata.get("camera_resolution") or {}
        rear = calibration.get("rear_normalized")
        front = calibration.get("front_normalized")
        classifier = LandingV2Classifier(
            tuple(rear) if rear else None,
            tuple(front) if front else None,
            analysis_mirrored=bool(calibration.get("analysis_mirrored", False)),
            frame_width=int(resolution.get("width") or 1920),
            frame_height=int(resolution.get("height") or 1080),
        )

    rows: list[dict[str, Any]] = []
    for event in events:
        if not is_benchmark_event(event):
            continue
        event_id = str(event.get("event_id", ""))
        annotation = annotations.get(event_id, {})
        truth = normalize_label(annotation.get("ground_truth", ""), allow_skip=True)
        if truth not in {"Left", "Right"}:
            continue
        if str(annotation.get("valid", "1")).strip().lower() in {"0", "false", "no"}:
            continue
        contact_time = float(event["contact_timestamp"])
        window = [
            sample
            for sample in samples
            if contact_time - REPLAY_PRE_MS / 1000.0
            <= sample.timestamp_s
            <= contact_time + REPLAY_POST_MS / 1000.0
        ]
        decision = classifier(int(event_id), contact_time, window, config)
        raw_label = decision.label.value
        prediction = normalize_label(raw_label) or "Unknown"
        if raw_label == "both":
            prediction = "Unknown"
        accepted = prediction in {"Left", "Right"}
        correct = accepted and prediction == truth
        high_confidence_wrong = (
            accepted
            and not correct
            and decision.confidence >= HIGH_CONFIDENCE_THRESHOLD
        )
        rows.append(
            {
                "event_id": event_id,
                "scenario": annotation.get("scenario") or event.get("scenario") or metadata.get("scenario") or "normal",
                "ground_truth": truth,
                "prediction": prediction,
                "visual_raw_label": raw_label,
                "confidence": round(float(decision.confidence), 6),
                "reason": canonical_reject_reason(decision.reason, raw_label),
                "correct": "1" if correct else "0",
                "accepted": "1" if accepted else "0",
                "high_confidence_wrong": "1" if high_confidence_wrong else "0",
                "pose_samples": len(window),
                "left_evidence": decision.left_evidence,
                "right_evidence": decision.right_evidence,
            }
        )

    summary = metrics_for_rows(rows)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["scenario"])].append(row)
    summary["scenarios"] = {
        scenario: metrics_for_rows(values) for scenario, values in sorted(grouped.items())
    }
    summary["classifier_entrypoint"] = (
        LANDING_V2_ENTRYPOINT if mode == "visual-evidence-v2" else LANDING_CLASSIFIER_ENTRYPOINT
    )
    summary["classifier_version"] = (
        LANDING_V2_VERSION if mode == "visual-evidence-v2" else LANDING_CLASSIFIER_VERSION
    )
    summary["replay_mode"] = mode
    summary["recorded_classifier_version"] = metadata.get(
        "classifier_version", "unknown"
    )
    version = software_version_metadata()
    summary["replay_time"] = datetime.now().astimezone().isoformat()
    summary["git_commit"] = version["git_commit"]
    summary["git_dirty"] = version["git_dirty"]
    summary["window_ms"] = {"pre": REPLAY_PRE_MS, "post": REPLAY_POST_MS}
    return summary, rows


def replay_phase_resync(
    events: Iterable[dict[str, Any]],
    *,
    inject_phase_slip_at: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replay phase state from immutable device and visual inputs."""

    manager = FootPhaseManager()
    rows: list[dict[str, Any]] = []
    injected = inject_phase_slip_at is not None
    for event in events:
        event_id = int(event.get("event_id") or 0)
        raw = _foot_label(event.get("raw_device_label") or event.get("original_grating_label"))
        if inject_phase_slip_at is not None and event_id >= inject_phase_slip_at:
            raw = opposite(raw)
        visual = _foot_label(event.get("visual_label") or event.get("visual_raw_label"))
        anomaly_reasons = tuple(
            value for value in str(event.get("anomaly_reasons") or "").split("|") if value
        )
        value = DevicePhaseInput(
            event_id=event_id,
            raw_device_symbol=str(event.get("raw_device_symbol") or event.get("original_grating_label") or ""),
            raw_device_label=raw,
            visual_label=visual,
            left_evidence=_optional_float(event.get("left_evidence")),
            right_evidence=_optional_float(event.get("right_evidence")),
            device_anomaly=str(event.get("device_anomaly", "0")).lower() in {"1", "true", "yes"},
            anomaly_reasons=anomaly_reasons,
            manual_flip=str(event.get("phase_action", "")) == "manual_flip",
        )
        rows.extend(_phase_result_row(item) for item in manager.process(value))
    rows.extend(_phase_result_row(item) for item in manager.flush())
    rows.sort(key=lambda item: int(item["event_id"]))

    automatic_flips = sum(row["phase_action"] == "auto_flip" for row in rows)
    recovered = bool(injected and automatic_flips)
    recovery_contacts = None
    if recovered and inject_phase_slip_at is not None:
        confirm_ids = [
            int(row["phase_flip_confirm_event_id"])
            for row in rows
            if row.get("phase_flip_confirm_event_id") not in (None, "")
        ]
        if confirm_ids:
            recovery_contacts = min(confirm_ids) - inject_phase_slip_at + 1
    summary = {
        "replay_mode": "phase-resync-v1",
        "total_events": len(rows),
        "automatic_phase_flips": automatic_flips,
        "injected_phase_slip_at": inject_phase_slip_at,
        "phase_slip_recovered": recovered,
        "recovery_contact_count": recovery_contacts,
        "final_phase_offset": manager.phase_offset,
        "final_phase_epoch": manager.phase_epoch,
        "recorded_classifier_version": (metadata or {}).get("classifier_version", "unknown"),
    }
    version = software_version_metadata()
    summary["replay_time"] = datetime.now().astimezone().isoformat()
    summary.update(git_commit=version["git_commit"], git_dirty=version["git_dirty"])
    return summary, rows


def compare_replay(session_root: str | Path) -> dict[str, Any]:
    """Run V1 and V2 on the same immutable Session for tuning review."""

    v1, _ = replay_session(session_root, mode="landing-v1")
    v2, _ = replay_session(session_root, mode="visual-evidence-v2")
    return {"landing_v1": v1, "visual_evidence_v2": v2}


def run_phase_slip_injections(
    events: Iterable[dict[str, Any]],
    *,
    count: int = 100,
    seed: int = 0,
) -> dict[str, Any]:
    """Run deterministic random phase-slip injections without mutating input."""

    values = [dict(event) for event in events]
    candidates = [
        int(event.get("event_id") or 0)
        for event in values
        if _foot_label(event.get("raw_device_label") or event.get("original_grating_label"))
        in (FootLabel.LEFT, FootLabel.RIGHT)
    ]
    if count <= 0:
        raise ValueError("injection count must be positive")
    if not candidates:
        return {
            "requested_injections": count,
            "recoverable_injections": 0,
            "recovered_injections": 0,
            "phase_slip_recovery_rate": 0.0,
            "recovery_contacts_p95": None,
            "trials": [],
        }
    rng = random.Random(seed)
    trials = []
    for _ in range(count):
        event_id = rng.choice(candidates)
        recoverable = _recoverable_in_four_contacts(values, event_id)
        summary, _ = replay_phase_resync(values, inject_phase_slip_at=event_id)
        trials.append(
            {
                "event_id": event_id,
                "recoverable": recoverable,
                "recovered": bool(summary["phase_slip_recovered"]),
                "recovery_contact_count": summary["recovery_contact_count"],
            }
        )
    eligible = [trial for trial in trials if trial["recoverable"]]
    recovered = [trial for trial in eligible if trial["recovered"]]
    counts = sorted(
        int(trial["recovery_contact_count"])
        for trial in recovered
        if trial["recovery_contact_count"] is not None
    )
    p95 = counts[max(0, math.ceil(len(counts) * 0.95) - 1)] if counts else None
    return {
        "seed": seed,
        "requested_injections": count,
        "recoverable_injections": len(eligible),
        "recovered_injections": len(recovered),
        "phase_slip_recovery_rate": _ratio(len(recovered), len(eligible)),
        "recovery_contacts_p95": p95,
        "trials": trials,
    }


def pose_record_to_sample(record: dict[str, Any]) -> FootPoseSample | None:
    if not record.get("pose_available"):
        return None
    raw = record.get("landmarks") or []
    if len(raw) < 33:
        return None
    points = tuple(_landmark_from_dict(value) for value in raw[:33])
    return FootPoseSample(
        timestamp_s=float(record["perf_counter_timestamp"]),
        left_hip=points[23],
        left_knee=points[25],
        left_ankle=points[27],
        left_heel=points[29],
        left_foot_index=points[31],
        right_hip=points[24],
        right_knee=points[26],
        right_ankle=points[28],
        right_heel=points[30],
        right_foot_index=points[32],
        landmarks_33=points,
    )


def metrics_for_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    total = len(values)
    accepted = sum(str(row.get("accepted")) == "1" for row in values)
    correct = sum(str(row.get("correct")) == "1" for row in values)
    wrong = accepted - correct
    unknown = total - accepted
    return {
        "total_events": total,
        "events": total,
        "left_ground_truth": sum(row.get("ground_truth") == "Left" for row in values),
        "right_ground_truth": sum(row.get("ground_truth") == "Right" for row in values),
        "correct": correct,
        "wrong": wrong,
        "unknown": unknown,
        "accuracy": _ratio(correct, total),
        "accepted_accuracy": _ratio(correct, accepted),
        "coverage": _ratio(accepted, total),
        "unknown_rate": _ratio(unknown, total),
        "accepted_error_rate": _ratio(wrong, accepted),
        "high_confidence_wrong_count": sum(
            str(row.get("high_confidence_wrong")) == "1" for row in values
        ),
        "wrong_event_ids": [
            str(row["event_id"])
            for row in values
            if str(row.get("accepted")) == "1" and str(row.get("correct")) == "0"
        ],
    }


def write_replay_outputs(
    output_dir: str | Path,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "replay_summary.json"
    events_path = root / "replay_events.csv"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with events_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REPLAY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return summary_path, events_path


def _landmark_from_dict(value: dict[str, Any]) -> Landmark:
    return Landmark(
        x=float(value["x"]),
        y=float(value["y"]),
        z=float(value["z"]),
        visibility=float(value.get("visibility", 0.0)),
        presence=float(value.get("presence", value.get("visibility", 0.0))),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _foot_label(value: Any) -> FootLabel:
    text = str(value or "").strip().lower()
    if text in {"left", "l", "a"}:
        return FootLabel.LEFT
    if text in {"right", "r", "b"}:
        return FootLabel.RIGHT
    return FootLabel.UNKNOWN


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _phase_result_row(result) -> dict[str, Any]:
    return {
        "event_id": result.event_id,
        "raw_device_label": result.raw_device_label.value,
        "effective_device_label": result.effective_device_label.value,
        "final_label": result.final_label.value,
        "visual_label": result.visual_label.value,
        "left_evidence": result.left_evidence,
        "right_evidence": result.right_evidence,
        "phase_offset": "1" if result.phase_offset else "0",
        "phase_epoch": result.phase_epoch,
        "phase_action": result.phase_action,
        "phase_flip_start_event_id": result.phase_flip_start_event_id,
        "phase_flip_confirm_event_id": result.phase_flip_confirm_event_id,
    }


def _recoverable_in_four_contacts(
    events: list[dict[str, Any]], inject_at: int
) -> bool:
    mismatches: set[FootLabel] = set()
    contacts = 0
    for event in events:
        event_id = int(event.get("event_id") or 0)
        if event_id < inject_at:
            continue
        raw = _foot_label(event.get("raw_device_label") or event.get("original_grating_label"))
        visual = _foot_label(event.get("visual_label") or event.get("visual_raw_label"))
        if raw not in (FootLabel.LEFT, FootLabel.RIGHT):
            continue
        contacts += 1
        injected = opposite(raw)
        if visual is opposite(injected):
            mismatches.add(injected)
        if len(mismatches) == 2:
            return True
        if contacts >= 4:
            return False
    return False


__all__ = [
    "HIGH_CONFIDENCE_THRESHOLD",
    "REPLAY_FIELDS",
    "REPLAY_POST_MS",
    "REPLAY_PRE_MS",
    "metrics_for_rows",
    "pose_record_to_sample",
    "compare_replay",
    "replay_phase_resync",
    "run_phase_slip_injections",
    "replay_session",
    "write_replay_outputs",
]
