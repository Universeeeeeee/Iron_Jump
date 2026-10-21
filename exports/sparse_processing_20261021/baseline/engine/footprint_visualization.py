"""Canonical footprint visualization frame model.

This module is intentionally UI-free. It represents the engine/report data
that live views and replay renderers can consume without owning lifecycle
state themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


FootSideVisual = Literal["left", "right", "unknown"]
FootStatusVisual = Literal["candidate", "confirmed", "lifted"]

_LED_COUNT = 96
_VALID_STATUSES = {"candidate", "confirmed", "lifted"}


@dataclass(frozen=True)
class FootprintActiveState:
    contact_id: int
    side: FootSideVisual
    centroid_cm: float | None
    length_cm: float | None
    status: FootStatusVisual


@dataclass(frozen=True)
class FootprintVisualFrame:
    timestamp_s: float
    contact_bits: tuple[int, ...]
    feet: tuple[FootprintActiveState, ...] = ()

    def to_dict(self) -> dict:
        return {
            "timestamp_s": self.timestamp_s,
            "contact_bits": list(self.contact_bits),
            "feet": [
                {
                    "contact_id": foot.contact_id,
                    "side": foot.side,
                    "centroid_cm": foot.centroid_cm,
                    "length_cm": foot.length_cm,
                    "status": foot.status,
                }
                for foot in self.feet
            ],
        }


def led_index_to_unit_y(index: float, led_count: int = _LED_COUNT) -> float:
    if led_count <= 1:
        return 0.0
    value = float(index) / float(led_count - 1)
    return max(0.0, min(1.0, value))


def side_from_foot_label(label: object) -> FootSideVisual:
    if label == "A":
        return "left"
    if label == "B":
        return "right"
    return "unknown"


def _normalized_bits(contact_bits: Iterable[object]) -> tuple[int, ...]:
    bits = tuple(1 if bit else 0 for bit in contact_bits)
    if len(bits) >= _LED_COUNT:
        return bits[:_LED_COUNT]
    return bits + (0,) * (_LED_COUNT - len(bits))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def build_visual_frame(
    timestamp_s: float, contact_bits: Iterable[object], tracker: object
) -> FootprintVisualFrame:
    feet = []
    active_contacts = getattr(tracker, "active_contacts", {})
    for contact in sorted(
        active_contacts.values(), key=lambda item: item.contact_id
    ):
        if getattr(contact, "is_initial_baseline", False):
            continue
        status = contact.status
        if status not in _VALID_STATUSES:
            continue

        centroid_cm = contact.latest_centroid
        if centroid_cm is None:
            centroid_cm = contact.centroid_at_touch
        length_cm = contact.latest_cluster_length
        if length_cm is None:
            length_cm = contact.cluster_length_at_touch

        feet.append(
            FootprintActiveState(
                contact_id=contact.contact_id,
                side=getattr(contact, "side", side_from_foot_label(contact.foot_label)),
                centroid_cm=_optional_float(centroid_cm),
                length_cm=_optional_float(length_cm),
                status=status,
            )
        )

    return FootprintVisualFrame(
        timestamp_s=timestamp_s,
        contact_bits=_normalized_bits(contact_bits),
        feet=tuple(feet),
    )


class FootprintTimelineRecorder:
    def __init__(self, interval_s: float = 1 / 25):
        self.interval_s = float(interval_s)
        self._frames: list[FootprintVisualFrame] = []
        self._pending: list[FootprintVisualFrame] = []
        self._next_due_s: float | None = None

    @property
    def frames(self) -> tuple[FootprintVisualFrame, ...]:
        return tuple(self._frames)

    def reset(self) -> None:
        self._frames.clear()
        self._pending.clear()
        self._next_due_s = None

    def record_if_due(
        self, timestamp_s: float, contact_bits: Iterable[object], tracker: object
    ) -> FootprintVisualFrame | None:
        if self._next_due_s is not None and timestamp_s < self._next_due_s:
            return None

        frame = build_visual_frame(timestamp_s, contact_bits, tracker)
        self._frames.append(frame)
        self._pending.append(frame)

        if self._next_due_s is None:
            self._next_due_s = timestamp_s + self.interval_s
        else:
            while timestamp_s >= self._next_due_s:
                self._next_due_s += self.interval_s

        return frame

    def pop_pending(self) -> tuple[FootprintVisualFrame, ...]:
        frames = tuple(self._pending)
        self._pending.clear()
        return frames


__all__ = [
    "FootSideVisual",
    "FootStatusVisual",
    "FootprintActiveState",
    "FootprintTimelineRecorder",
    "FootprintVisualFrame",
    "build_visual_frame",
    "led_index_to_unit_y",
    "side_from_foot_label",
]
