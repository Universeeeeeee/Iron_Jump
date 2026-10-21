"""Conservative visual assistance for device foot-phase resynchronization."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from enum import Enum
from statistics import median
from typing import Iterable

from .foot_reference import FootLabel


class PhaseState(str, Enum):
    NORMAL = "normal"
    SUSPECT = "suspect"


def opposite(label: FootLabel | str) -> FootLabel:
    value = FootLabel(label)
    if value is FootLabel.LEFT:
        return FootLabel.RIGHT
    if value is FootLabel.RIGHT:
        return FootLabel.LEFT
    return FootLabel.UNKNOWN


@dataclass(frozen=True)
class DevicePhaseInput:
    event_id: int
    raw_device_symbol: str
    raw_device_label: FootLabel
    visual_label: FootLabel = FootLabel.UNKNOWN
    left_evidence: float | None = None
    right_evidence: float | None = None
    device_anomaly: bool = False
    anomaly_reasons: tuple[str, ...] = ()
    manual_flip: bool = False


@dataclass(frozen=True)
class PhaseEventResult:
    event_id: int
    raw_device_symbol: str
    raw_device_label: FootLabel
    effective_device_label: FootLabel
    final_label: FootLabel
    visual_label: FootLabel
    left_evidence: float | None
    right_evidence: float | None
    device_anomaly: bool
    anomaly_reasons: tuple[str, ...]
    phase_suspect_trigger: bool
    phase_offset: bool
    phase_epoch: int
    phase_action: str
    suspect_start_event_id: int | None = None
    first_mismatch_device_label: FootLabel | None = None
    first_mismatch_visual_label: FootLabel | None = None
    pending_contact_count: int = 0
    suspect_unknown_count: int = 0
    phase_flip_reason: str = ""
    phase_flip_start_event_id: int | None = None
    phase_flip_confirm_event_id: int | None = None


class DeviceAnomalyDetector:
    """Generate device-side suspicion signals without changing any label."""

    def __init__(self) -> None:
        self._last_label = FootLabel.UNKNOWN
        self._last_time_s: float | None = None
        self._intervals: deque[float] = deque(maxlen=7)

    def observe(
        self,
        label: FootLabel,
        timestamp_s: float,
        *,
        label_confidence: float | None = None,
        quality_flags: Iterable[str] = (),
    ) -> tuple[bool, tuple[str, ...]]:
        reasons = [str(value) for value in quality_flags if str(value)]
        if label not in (FootLabel.LEFT, FootLabel.RIGHT):
            reasons.append("device_label_missing")
        elif self._last_label is label:
            reasons.append("repeated_device_label")
        if label_confidence is not None and label_confidence < 0.70:
            reasons.append("device_label_confidence_low")

        if self._last_time_s is not None:
            interval = timestamp_s - self._last_time_s
            if interval > 0 and len(self._intervals) >= 5:
                baseline = median(self._intervals)
                if interval < 0.55 * baseline:
                    reasons.append("short_interval_duplicate_suspect")
                elif interval > 1.65 * baseline:
                    reasons.append("long_interval_missed_touch_suspect")
            if interval > 0:
                self._intervals.append(interval)
        self._last_time_s = timestamp_s
        self._last_label = label
        return bool(reasons), tuple(dict.fromkeys(reasons))


class DeviceLabelMapper:
    """Resolve a session-stable device A/B to anatomical side mapping."""

    def __init__(self, starting_foot: str | None = None) -> None:
        self._starting_foot = FootLabel(starting_foot) if starting_foot else None
        self._mapping: dict[str, FootLabel] = {}

    def map(self, symbol: str | None) -> FootLabel:
        normalized = str(symbol or "").strip().upper()
        if normalized not in {"A", "B"}:
            return FootLabel.UNKNOWN
        if not self._mapping:
            if self._starting_foot is None:
                self._mapping = {"A": FootLabel.LEFT, "B": FootLabel.RIGHT}
            else:
                self._mapping[normalized] = self._starting_foot
                other = "B" if normalized == "A" else "A"
                self._mapping[other] = opposite(self._starting_foot)
        return self._mapping[normalized]


class FootPhaseManager:
    """Require a crossed L/R mismatch pair before changing phase offset.

    ``process`` may retain events while phase is suspect. Its returned tuple
    contains only finalized events that are safe to append to a Session CSV.
    """

    def __init__(self, *, max_unknown: int = 2, max_pending_contacts: int = 4) -> None:
        self.max_unknown = max_unknown
        self.max_pending_contacts = max_pending_contacts
        self.state = PhaseState.NORMAL
        self.phase_offset = False
        self.phase_epoch = 0
        self._pending: list[PhaseEventResult] = []
        self._suspect_start_event_id: int | None = None
        self._first_device: FootLabel | None = None
        self._first_visual: FootLabel | None = None
        self._unknown_count = 0
        self._anomaly_only_unknown_count = 0
        self._manual_from_next = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def process(self, value: DevicePhaseInput) -> tuple[PhaseEventResult, ...]:
        if value.manual_flip:
            finalized = list(self.manual_flip())
            finalized.extend(self.process(replace(value, manual_flip=False)))
            return tuple(finalized)

        if self._manual_from_next:
            action = "manual_flip"
            reason = "manual"
            self._manual_from_next = False
        else:
            action = "keep"
            reason = ""
        result = self._make_result(value, action=action, flip_reason=reason)

        if self.state is PhaseState.NORMAL:
            if self._is_mismatch(result):
                self._start_visual_suspect(result)
                return ()
            if result.visual_label is FootLabel.UNKNOWN and result.device_anomaly:
                self.state = PhaseState.SUSPECT
                self._anomaly_only_unknown_count = 1
                return (replace(result, phase_action="suspect_start"),)
            return (result,)

        if self._first_device is None:
            if self._is_mismatch(result):
                self._start_visual_suspect(result)
                return ()
            if result.visual_label is FootLabel.UNKNOWN:
                self._anomaly_only_unknown_count += 1
                if self._anomaly_only_unknown_count >= 2:
                    self._clear_suspect()
                return (replace(result, phase_action="suspect_hold"),)
            self._clear_suspect()
            return (result,)

        self._pending.append(replace(result, phase_action="suspect_hold"))
        if len(self._pending) > self.max_pending_contacts:
            return self._expire_pending()
        if self._is_agreement(result):
            return self._expire_pending()
        if result.visual_label is FootLabel.UNKNOWN:
            self._unknown_count += 1
        elif self._is_confirming_cross_pair(result):
            return self._confirm_flip(result.event_id)
        elif self._is_mismatch(result) and result.effective_device_label is self._first_device:
            self._pending[-1] = replace(
                self._pending[-1], phase_action="same_device_mismatch_not_confirming"
            )

        if self._unknown_count > self.max_unknown:
            return self._expire_pending()
        return ()

    def manual_flip(self) -> tuple[PhaseEventResult, ...]:
        self.phase_offset = not self.phase_offset
        self.phase_epoch += 1
        if not self._pending:
            self._manual_from_next = True
            self._clear_suspect()
            return ()
        start_id = self._suspect_start_event_id
        updated = tuple(
            replace(
                item,
                effective_device_label=(
                    opposite(item.raw_device_label)
                    if self.phase_offset
                    else item.raw_device_label
                ),
                final_label=(
                    opposite(item.raw_device_label)
                    if self.phase_offset
                    else item.raw_device_label
                ),
                phase_offset=self.phase_offset,
                phase_epoch=self.phase_epoch,
                phase_action="manual_flip" if index == 0 else "suspect_hold",
                phase_flip_reason="manual",
                phase_flip_start_event_id=start_id,
                phase_flip_confirm_event_id=None,
            )
            for index, item in enumerate(self._pending)
        )
        self._clear_suspect()
        return updated

    def flush(self) -> tuple[PhaseEventResult, ...]:
        return self._expire_pending()

    def _make_result(
        self, value: DevicePhaseInput, *, action: str, flip_reason: str
    ) -> PhaseEventResult:
        effective = (
            opposite(value.raw_device_label)
            if self.phase_offset
            else value.raw_device_label
        )
        visual_mismatch = (
            effective in (FootLabel.LEFT, FootLabel.RIGHT)
            and value.visual_label is opposite(effective)
        )
        return PhaseEventResult(
            event_id=value.event_id,
            raw_device_symbol=value.raw_device_symbol,
            raw_device_label=value.raw_device_label,
            effective_device_label=effective,
            final_label=effective,
            visual_label=value.visual_label,
            left_evidence=value.left_evidence,
            right_evidence=value.right_evidence,
            device_anomaly=value.device_anomaly,
            anomaly_reasons=value.anomaly_reasons,
            phase_suspect_trigger=value.device_anomaly or visual_mismatch,
            phase_offset=self.phase_offset,
            phase_epoch=self.phase_epoch,
            phase_action=action,
            phase_flip_reason=flip_reason,
        )

    @staticmethod
    def _is_mismatch(result: PhaseEventResult) -> bool:
        return (
            result.effective_device_label in (FootLabel.LEFT, FootLabel.RIGHT)
            and result.visual_label is opposite(result.effective_device_label)
        )

    @staticmethod
    def _is_agreement(result: PhaseEventResult) -> bool:
        return (
            result.effective_device_label in (FootLabel.LEFT, FootLabel.RIGHT)
            and result.visual_label is result.effective_device_label
        )

    def _start_visual_suspect(self, result: PhaseEventResult) -> None:
        self.state = PhaseState.SUSPECT
        self._suspect_start_event_id = result.event_id
        self._first_device = result.effective_device_label
        self._first_visual = result.visual_label
        self._unknown_count = 0
        self._pending = [
            replace(
                result,
                phase_action="suspect_start",
                suspect_start_event_id=result.event_id,
                first_mismatch_device_label=result.effective_device_label,
                first_mismatch_visual_label=result.visual_label,
                pending_contact_count=1,
            )
        ]

    def _is_confirming_cross_pair(self, result: PhaseEventResult) -> bool:
        return (
            self._first_device is not None
            and self._first_visual is not None
            and result.effective_device_label is opposite(self._first_device)
            and result.visual_label is opposite(result.effective_device_label)
            and result.visual_label is self._first_device
        )

    def _confirm_flip(self, confirm_event_id: int) -> tuple[PhaseEventResult, ...]:
        self.phase_offset = not self.phase_offset
        self.phase_epoch += 1
        start_id = self._suspect_start_event_id
        count = len(self._pending)
        updated = tuple(
            replace(
                item,
                effective_device_label=opposite(item.effective_device_label),
                final_label=opposite(item.effective_device_label),
                phase_offset=self.phase_offset,
                phase_epoch=self.phase_epoch,
                phase_action="auto_flip" if item.event_id == confirm_event_id else item.phase_action,
                suspect_start_event_id=start_id,
                first_mismatch_device_label=self._first_device,
                first_mismatch_visual_label=self._first_visual,
                pending_contact_count=count,
                suspect_unknown_count=self._unknown_count,
                phase_flip_reason="auto_opposite_label_pair",
                phase_flip_start_event_id=start_id,
                phase_flip_confirm_event_id=confirm_event_id,
            )
            for item in self._pending
        )
        self._clear_suspect()
        return updated

    def _expire_pending(self) -> tuple[PhaseEventResult, ...]:
        count = len(self._pending)
        values = tuple(
            replace(
                item,
                suspect_start_event_id=self._suspect_start_event_id,
                first_mismatch_device_label=self._first_device,
                first_mismatch_visual_label=self._first_visual,
                pending_contact_count=count,
                suspect_unknown_count=self._unknown_count,
            )
            for item in self._pending
        )
        self._clear_suspect()
        return values

    def _clear_suspect(self) -> None:
        self.state = PhaseState.NORMAL
        self._pending = []
        self._suspect_start_event_id = None
        self._first_device = None
        self._first_visual = None
        self._unknown_count = 0
        self._anomaly_only_unknown_count = 0


__all__ = [
    "DeviceAnomalyDetector",
    "DeviceLabelMapper",
    "DevicePhaseInput",
    "FootPhaseManager",
    "PhaseEventResult",
    "PhaseState",
    "opposite",
]
