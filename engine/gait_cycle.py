"""Pure same-side gait-cycle construction from side-resolved events."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from config.treadmill_config import FootSide
from config.treadmill_report import (
    GaitBoundaryPartial,
    GaitCycleRecord,
    GaitEventKind,
    GaitEventRecord,
)


@dataclass(frozen=True)
class _ContactInterval:
    side: FootSide
    start_s: float
    end_s: float


class GaitCycleBuilder:
    """Build immutable cycles only when the next same-side touch arrives."""

    def __init__(self) -> None:
        self._raw_events: list[GaitEventRecord] = []
        self._completed_cycles: list[GaitCycleRecord] = []
        self._active_touch: dict[FootSide, float] = {}
        self._last_touch: dict[FootSide, float] = {}
        self._last_lift_after_touch: dict[FootSide, float] = {}
        self._last_contact_included: dict[FootSide, bool] = {}
        self._last_contact_exclusion_reason: dict[FootSide, str] = {}
        self._last_contact_quality_flags: dict[FootSide, tuple[str, ...]] = {}
        self._contact_intervals: list[_ContactInterval] = []
        self._initial_boundary_partials: list[GaitBoundaryPartial] = []
        self._observed_sides: set[FootSide] = set()
        self._known_from: dict[FootSide, float] = {}
        self._unknown_active = 0

    def record_clear(self, time_s: float) -> None:
        """Both feet are observed absent; unlike missing data this is evidence."""
        for side in ("left", "right"):
            self._known_from.setdefault(side, time_s)

    def record_baseline(self, time_s: float, side: FootSide) -> None:
        """Known ongoing support, but no invented initial-contact boundary."""
        if side in ("left", "right"):
            self._active_touch[side] = time_s
            self._known_from.setdefault(side, time_s)
        else:
            self._unknown_active += 1

    @property
    def raw_events(self) -> tuple[GaitEventRecord, ...]:
        return tuple(self._raw_events)

    @property
    def completed_cycles(self) -> tuple[GaitCycleRecord, ...]:
        return tuple(self._completed_cycles)

    def record_touch(
        self, time_s: float, side: FootSide, *, contact_id: int | None = None,
        confirmed_time_s: float | None = None, foot_label: str | None = None,
    ) -> GaitCycleRecord | None:
        self._append_event(time_s, side, "touch", contact_id, confirmed_time_s, foot_label)
        self._record_initial_boundary(time_s, side)
        if side not in ("left", "right"):
            self._unknown_active += 1
            return None
        self._known_from.setdefault(side, time_s)
        previous_touch = self._last_touch.get(side)
        if previous_touch is not None and time_s <= previous_touch:
            return None
        if side in self._active_touch:
            self._last_contact_included[side] = False
            self._last_contact_exclusion_reason[side] = (
                "Touch was replaced before lift"
            )
        completed = (
            self._close_cycle(time_s, side)
            if side in ("left", "right")
            else None
        )
        self._last_touch[side] = time_s
        self._active_touch[side] = time_s
        self._last_lift_after_touch.pop(side, None)
        self._last_contact_included.pop(side, None)
        self._last_contact_exclusion_reason.pop(side, None)
        self._last_contact_quality_flags.pop(side, None)
        return completed

    def record_lift(
        self,
        time_s: float,
        side: FootSide,
        is_included_in_statistics: bool | None = None,
        statistics_exclusion_reason: str | None = None,
        quality_flags: tuple[str, ...] = (),
        contact_id: int | None = None,
        confirmed_time_s: float | None = None,
        foot_label: str | None = None,
    ) -> None:
        self._append_event(time_s, side, "lift", contact_id, confirmed_time_s, foot_label)
        self._record_initial_boundary(time_s, side)
        if side not in ("left", "right"):
            self._unknown_active = max(self._unknown_active - 1, 0)
            return
        self._known_from.setdefault(side, time_s)
        start_s = self._active_touch.get(side)
        if start_s is None or time_s < start_s:
            return
        self._active_touch.pop(side)
        self._last_lift_after_touch[side] = time_s
        if is_included_in_statistics is not None:
            self._last_contact_included[side] = is_included_in_statistics
        if statistics_exclusion_reason is not None:
            self._last_contact_exclusion_reason[side] = (
                statistics_exclusion_reason
            )
        if quality_flags:
            self._last_contact_quality_flags[side] = quality_flags
        self._contact_intervals.append(_ContactInterval(side, start_s, time_s))

    def make_live_snapshot(
        self, time_s: float, completed_from_index: int = 0
    ) -> dict:
        active = set(self._active_touch)
        if self._unknown_active:
            support_state = "侧别未知接触"
        elif active == {"left", "right"}:
            support_state = "双支撑"
        elif active == {"left"}:
            support_state = "左脚单支撑"
        elif active == {"right"}:
            support_state = "右脚单支撑"
        elif active:
            support_state = "侧别未知接触"
        else:
            support_state = "腾空"

        current_cycles = self._current_cycle_states(time_s, active)
        start_index = min(max(completed_from_index, 0), len(self._completed_cycles))

        return {
            "support_state": support_state,
            "current_cycles": current_cycles,
            "completed_cycle_count": len(self._completed_cycles),
            "completed_cycle_start_index": start_index,
            "completed_cycles": [
                asdict(cycle) for cycle in self._completed_cycles[start_index:]
            ],
        }

    def pause_boundary(self, time_s: float) -> None:
        """Retain incomplete evidence but never pair touches across a pause."""
        self._initial_boundary_partials = list(self.build_boundary_partials(time_s))
        self._active_touch.clear()
        self._last_touch.clear()
        self._last_lift_after_touch.clear()
        self._last_contact_included.clear()
        self._last_contact_exclusion_reason.clear()
        self._last_contact_quality_flags.clear()
        self._contact_intervals.clear()
        self._known_from.clear()
        self._unknown_active = 0

    def build_boundary_partials(
        self, time_s: float
    ) -> tuple[GaitBoundaryPartial, ...]:
        active = set(self._active_touch)
        current_cycles = self._current_cycle_states(time_s, active)
        final_partials = tuple(
            GaitBoundaryPartial(
                side=state["side"],
                start_time_s=state["start_time_s"],
                snapshot_time_s=time_s,
                elapsed_s=state["elapsed_s"],
                phase=state["phase"],
            )
            for state in current_cycles.values()
        )
        return tuple(self._initial_boundary_partials) + final_partials

    def _record_initial_boundary(self, time_s: float, side: FootSide) -> None:
        if side in self._observed_sides:
            return
        self._observed_sides.add(side)
        if time_s <= 0:
            return
        self._initial_boundary_partials.append(
            GaitBoundaryPartial(
                side=side,
                start_time_s=0.0,
                snapshot_time_s=time_s,
                elapsed_s=time_s,
                phase="起始边界不完整",
            )
        )

    def _current_cycle_states(
        self, time_s: float, active: set[FootSide]
    ) -> dict[FootSide, dict]:
        return {
            side: {
                "side": side,
                "start_time_s": start_s,
                "elapsed_s": max(time_s - start_s, 0.0),
                "phase": "支撑相" if side in active else "摆动相",
            }
            for side, start_s in self._last_touch.items()
        }

    def _append_event(
        self, time_s: float, side: FootSide, kind: GaitEventKind,
        contact_id: int | None = None, confirmed_time_s: float | None = None,
        foot_label: str | None = None,
    ) -> None:
        self._raw_events.append(
            GaitEventRecord(
                index=len(self._raw_events),
                time_s=time_s,
                side=side,
                kind=kind,
                contact_id=contact_id,
                confirmed_time_s=confirmed_time_s,
                foot_label=foot_label,
            )
        )

    def _close_cycle(
        self, end_s: float, side: FootSide
    ) -> GaitCycleRecord | None:
        start_s = self._last_touch.get(side)
        if start_s is None or end_s <= start_s:
            return None

        cycle_s = end_s - start_s
        lift_s = self._last_lift_after_touch.get(side)
        stance_s = None
        swing_s = None
        if lift_s is not None and start_s <= lift_s <= end_s:
            stance_s = lift_s - start_s
            swing_s = end_s - lift_s

        opposite = "right" if side == "left" else "left"
        step_time_s = self._first_opposite_touch_after(start_s, end_s, opposite)
        opposite_complete = self._known_from.get(opposite, float("inf")) <= start_s + 1e-9
        if not opposite_complete:
            step_time_s = None

        load_response_s = None
        pre_swing_s = None
        total_double_support_s = None
        single_support_s = None
        if (
            stance_s is not None
            and lift_s is not None
            and opposite_complete
        ):
            overlaps = self._overlap_intervals(
                start_s, lift_s, opposite, end_s
            )
            total_double_support_s = sum(e - s for s, e in overlaps)
            spans_full_stance = (
                len(overlaps) == 1
                and overlaps[0][0] <= start_s + 1e-9
                and overlaps[0][1] >= lift_s - 1e-9
            )
            if not spans_full_stance:
                load_response_s = (
                    overlaps[0][1] - overlaps[0][0]
                    if overlaps and overlaps[0][0] <= start_s + 1e-9
                    else 0.0
                )
                pre_swing_s = (
                    overlaps[-1][1] - overlaps[-1][0]
                    if overlaps and overlaps[-1][1] >= lift_s - 1e-9
                    else 0.0
                )
            single_support_s = max(stance_s - total_double_support_s, 0.0)

        total_flight_time_s = (
            self._total_flight_time(start_s, end_s)
            if stance_s is not None and opposite_complete
            else None
        )
        percent = lambda value: value / cycle_s * 100.0 if value is not None else None

        is_included_in_statistics = self._last_contact_included.get(
            side, stance_s is not None
        )
        statistics_exclusion_reason = self._last_contact_exclusion_reason.get(
            side
        )
        if not is_included_in_statistics and statistics_exclusion_reason is None:
            statistics_exclusion_reason = "Missing same-side lift event"

        cycle = GaitCycleRecord(
            index=len(self._completed_cycles),
            side=side,
            start_time_s=start_s,
            end_time_s=end_s,
            gait_cycle_s=cycle_s,
            stance_phase_s=stance_s,
            stance_phase_percent=percent(stance_s),
            swing_phase_s=swing_s,
            swing_phase_percent=percent(swing_s),
            step_time_s=step_time_s,
            single_support_s=single_support_s,
            single_support_percent=percent(single_support_s),
            total_double_support_s=total_double_support_s,
            total_double_support_percent=percent(total_double_support_s),
            load_response_s=load_response_s,
            load_response_percent=percent(load_response_s),
            pre_swing_s=pre_swing_s,
            pre_swing_percent=percent(pre_swing_s),
            total_flight_time_s=total_flight_time_s,
            is_included_in_statistics=is_included_in_statistics,
            statistics_exclusion_reason=statistics_exclusion_reason,
            quality_flags=tuple(dict.fromkeys((
                *self._last_contact_quality_flags.get(side, ()),
                *(("opposite_contact_incomplete",) if not opposite_complete else ()),
            ))),
        )
        self._completed_cycles.append(cycle)
        return cycle

    def _first_opposite_touch_after(
        self, start_s: float, end_s: float, opposite: FootSide
    ) -> float | None:
        for event in self._raw_events:
            if (
                event.kind == "touch"
                and event.side == opposite
                and start_s < event.time_s <= end_s
            ):
                return event.time_s - start_s
        return None

    def _overlap_intervals(
        self,
        start_s: float,
        end_s: float,
        opposite: FootSide,
        snapshot_s: float,
    ) -> list[tuple[float, float]]:
        intervals = [
            (max(start_s, interval.start_s), min(end_s, interval.end_s))
            for interval in self._contact_intervals
            if interval.side == opposite
            and interval.end_s > start_s
            and interval.start_s < end_s
        ]
        active_start = self._active_touch.get(opposite)
        if active_start is not None and active_start < end_s:
            intervals.append((max(start_s, active_start), min(end_s, snapshot_s)))
        return _merge_intervals(intervals)

    def support_durations(self, start_s: float, end_s: float, side: FootSide):
        opposite = "right" if side == "left" else "left"
        if self._known_from.get(opposite, float("inf")) > start_s + 1e-9:
            return None, None
        double = sum(e - s for s, e in self._overlap_intervals(start_s, end_s, opposite, end_s))
        return double, max(end_s - start_s - double, 0.0)

    def _total_flight_time(self, start_s: float, end_s: float) -> float:
        contacts = [
            (max(start_s, interval.start_s), min(end_s, interval.end_s))
            for interval in self._contact_intervals
            if interval.end_s > start_s and interval.start_s < end_s
        ]
        for active_start in self._active_touch.values():
            if active_start < end_s:
                contacts.append((max(start_s, active_start), end_s))
        covered = sum(e - s for s, e in _merge_intervals(contacts))
        return max((end_s - start_s) - covered, 0.0)


def _merge_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    valid = sorted((s, e) for s, e in intervals if e > s)
    merged: list[tuple[float, float]] = []
    for start_s, end_s in valid:
        if not merged or start_s > merged[-1][1]:
            merged.append((start_s, end_s))
        else:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end_s))
    return merged


__all__ = ["GaitCycleBuilder"]
