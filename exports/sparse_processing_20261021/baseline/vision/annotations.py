"""Ground-truth annotation persistence independent from the GUI."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from .session import normalize_label


ANNOTATION_FIELDS = ("event_id", "ground_truth", "valid", "scenario", "note")


def is_benchmark_event(event: dict[str, Any]) -> bool:
    return str(event.get("valid_for_benchmark", "")).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def load_annotations(path: str | Path) -> dict[str, dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open(newline="", encoding="utf-8-sig") as file:
        return {
            str(row["event_id"]): row
            for row in csv.DictReader(file)
            if row.get("event_id")
        }


def save_annotations(
    path: str | Path,
    annotations: dict[str, dict[str, Any]],
) -> None:
    file_path = Path(path)
    temporary = file_path.with_suffix(file_path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANNOTATION_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for event_id in sorted(annotations, key=_event_sort_key):
            row = dict(annotations[event_id])
            row["event_id"] = event_id
            writer.writerow(row)
    temporary.replace(file_path)


def set_annotation(
    annotations: dict[str, dict[str, str]],
    event_id: str | int,
    ground_truth: str,
    *,
    scenario: str = "normal",
    note: str = "",
) -> dict[str, str]:
    normalized = normalize_label(ground_truth, allow_skip=True)
    if normalized not in {"Left", "Right", "Skip"}:
        raise ValueError("ground_truth must be Left, Right, or Skip")
    row = {
        "event_id": str(event_id),
        "ground_truth": normalized,
        "valid": "0" if normalized == "Skip" else "1",
        "scenario": scenario or "normal",
        "note": note,
    }
    annotations[str(event_id)] = row
    return row


def first_unannotated_index(
    events: Iterable[dict[str, Any]],
    annotations: dict[str, dict[str, str]],
) -> int:
    values = list(events)
    if not values:
        return 0
    for index, event in enumerate(values):
        if not is_benchmark_event(event):
            continue
        event_id = str(event.get("event_id", ""))
        truth = normalize_label(
            annotations.get(event_id, {}).get("ground_truth", ""),
            allow_skip=True,
        )
        if truth not in {"Left", "Right", "Skip"}:
            return index
    return len(values) - 1


def _event_sort_key(event_id: str):
    try:
        return (0, int(event_id))
    except ValueError:
        return (1, event_id)


__all__ = [
    "ANNOTATION_FIELDS",
    "first_unannotated_index",
    "is_benchmark_event",
    "load_annotations",
    "save_annotations",
    "set_annotation",
]
