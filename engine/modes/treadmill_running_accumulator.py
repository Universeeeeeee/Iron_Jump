"""
treadmill_running_accumulator.py — running-specific treadmill row accumulator

Running rows are built around contact and airborne phases.  A short overlap is
allowed because low-speed running can briefly include double contact.  Longer
overlap and a small gap between feet are retained as quality diagnostics.
"""

from __future__ import annotations

from config.treadmill_config import FootSide, TreadmillRunningConfig
from config.treadmill_report import CorrectionSource, RowStatus, TreadmillStepResult
from engine.modes.treadmill_accumulator import (
    TreadmillAccumulator,
    _PartialRow,
    belt_speed_m_s,
    normalize_foot_side,
    step_length_from_time_cm,
    step_reference_cm,
)


RUNNING_OVERLAP_TOLERANCE_S = 0.05


class TreadmillRunningAccumulator(TreadmillAccumulator):
    """Accumulates treadmill running contacts with airborne phase detection."""

    def __init__(self, config: TreadmillRunningConfig) -> None:
        super().__init__(config)
        self._config: TreadmillRunningConfig = config
        self._active: dict[FootSide, _PartialRow] = {}
        self._completed_intervals: list[tuple[FootSide, float, float]] = []
        self._last_lift_time_s: float | None = None
        self._last_touch_toe_cm: float | None = None

    def pause_boundary(self, time_s: float) -> None:
        """Exclude interrupted contacts and avoid timing across a pause."""
        for partial in tuple(self._active.values()):
            self._finalize_partial(partial, time_s, "suspended")
        self._completed_intervals.clear()
        self._last_lift_time_s = None
        self._last_touch_time_s = None
        self._last_touch_toe_cm = None
        self._last_step_reference_cm = None
        self._last_step_side = None
        self._stagger_estimates.clear()

    def record_touch(
        self, time_s: float, side: str, heel_cm: float, toe_cm: float
    ) -> None:
        """Record a foot-down event and compute inter-touch running metrics."""
        if not self._first_contact_resolved:
            self._resolve_starting_foot_from_contact(side)
            self._first_contact_resolved = True

        foot_side = normalize_foot_side(side)
        if foot_side in self._active:
            self._finalize_partial(self._active[foot_side], time_s, "no_step")

        step_time_s: float | None = None
        if self._last_touch_time_s is not None:
            step_time_s = time_s - self._last_touch_time_s

        flight_time_s: float | None = None
        if self._last_lift_time_s is not None:
            gap_s = time_s - self._last_lift_time_s
            if gap_s > 0:
                flight_time_s = gap_s

        reference_cm = step_reference_cm(self._config, heel_cm, toe_cm)
        gap_between_feet_cm: float | None = None
        if (
            self._last_touch_toe_cm is not None
            and step_time_s is not None
            and step_time_s > 0
        ):
            belt_distance_cm = (
                belt_speed_m_s(self._config) * step_time_s * 100.0
            )
            if self._config.direction == "Opposite side":
                raw_gap_cm = (
                    belt_distance_cm + self._last_touch_toe_cm - heel_cm
                )
            else:
                raw_gap_cm = (
                    belt_distance_cm + heel_cm - self._last_touch_toe_cm
                )
            gap_between_feet_cm = max(raw_gap_cm, 0.0)

        partial = _PartialRow(
            side=foot_side,
            touch_time_s=time_s,
            heel_cm=heel_cm,
            toe_cm=toe_cm,
            step_time_s=step_time_s,
            flight_time_s=flight_time_s,
            step_length_cm=step_length_from_time_cm(self._config, step_time_s),
            step_reference_cm=reference_cm,
            gap_between_feet_cm=gap_between_feet_cm,
        )
        self._active[foot_side] = partial
        self._last_touch_time_s = time_s
        self._last_touch_toe_cm = toe_cm

    def record_lift(self, time_s: float, side: str) -> None:
        """Record a foot-up event and finalize that foot's running row."""
        foot_side = normalize_foot_side(side)
        partial = self._active.get(foot_side)
        if partial is None and foot_side == "unknown" and len(self._active) == 1:
            foot_side, partial = next(iter(self._active.items()))
        if partial is None:
            return

        partial.lift_time_s = time_s
        self._finalize_partial(partial, time_s, "valid")

    def _finalize_partial(
        self, partial: _PartialRow, time_s: float, row_status: RowStatus
    ) -> None:
        contact_time_s = (
            partial.lift_time_s - partial.touch_time_s
            if partial.lift_time_s is not None
            else None
        )

        is_event_valid = row_status == "valid"
        is_included_in_statistics = is_event_valid
        correction_source: CorrectionSource = "none"
        event_invalid_reason: str | None = None
        statistics_exclusion_reason: str | None = None
        quality_flags: list[str] = []

        if row_status == "suspended":
            event_invalid_reason = "Contact interrupted by pause"
            statistics_exclusion_reason = "Contact interrupted by pause"
        elif row_status == "no_step":
            is_event_valid = False
            is_included_in_statistics = False
            event_invalid_reason = "Touch was replaced before lift"
            statistics_exclusion_reason = "Touch was replaced before lift"
        elif (
            contact_time_s is not None
            and self._config.min_contact_time > 0
            and contact_time_s < self._config.min_contact_time / 1000.0
        ):
            row_status = "tc_not_valid"
            is_event_valid = False
            is_included_in_statistics = False
            correction_source = "threshold_filter"
            event_invalid_reason = "Contact time below minimum threshold"
            statistics_exclusion_reason = "Contact time below minimum threshold"

        if row_status == "valid" and partial.flight_time_s is not None:
            ft_ms = partial.flight_time_s * 1000.0
            min_ft = self._config.min_flight_time
            max_ft = self._config.max_flight_time
            if (min_ft > 0 and ft_ms < min_ft) or (max_ft > 0 and ft_ms > max_ft):
                row_status = "tf_not_valid"
                is_event_valid = False
                is_included_in_statistics = False
                correction_source = "threshold_filter"
                event_invalid_reason = "Flight time outside acceptable range"
                statistics_exclusion_reason = "Flight time outside acceptable range"

        overlap_s = self._prior_overlap_duration(partial, time_s)
        if row_status == "valid" and overlap_s > RUNNING_OVERLAP_TOLERANCE_S:
            quality_flags.append("running_overlap_above_tolerance")

        if (
            row_status == "valid"
            and partial.gap_between_feet_cm is not None
            and partial.gap_between_feet_cm < self._config.min_gap_between_feet
        ):
            quality_flags.append("gap_below_minimum")

        speed_m_s: float | None = None
        if row_status != "no_step":
            # Spatial correction: override step_length with belt_distance + drift
            spatial_cm = self._spatial_correction_cm(
                partial.step_reference_cm, partial.side
            )
            if (
                partial.step_time_s is not None
                and partial.step_time_s > 0
                and partial.step_length_cm is not None
            ):
                partial.step_length_cm = (
                    belt_speed_m_s(self._config) * partial.step_time_s * 100.0
                    + spatial_cm
                )
                speed_m_s = partial.step_length_cm / 100.0 / partial.step_time_s
            else:
                speed_m_s = belt_speed_m_s(self._config)

            # Update spatial tracking for next step (valid rows only)
            if row_status == "valid":
                self._last_step_reference_cm = partial.step_reference_cm
                self._last_step_side = partial.side

        distance_cm = (
            belt_speed_m_s(self._config) * time_s * 100.0
            if row_status != "no_step" else None
        )
        cadence_steps_per_s = (
            1.0 / partial.step_time_s
            if partial.step_time_s is not None and partial.step_time_s > 0
            else None
        )
        stride_length_cm = None

        result = TreadmillStepResult(
            index=self._next_index,
            side=partial.side,
            row_status=row_status,
            is_event_valid=is_event_valid,
            is_included_in_statistics=is_included_in_statistics,
            correction_source=correction_source,
            event_invalid_reason=event_invalid_reason,
            statistics_exclusion_reason=statistics_exclusion_reason,
            quality_flags=tuple(quality_flags),
            time_s=time_s,
            distance_cm=distance_cm,
            contact_time_s=contact_time_s,
            flight_time_s=partial.flight_time_s,
            step_time_s=partial.step_time_s,
            step_length_cm=partial.step_length_cm,
            step_reference_cm=partial.step_reference_cm,
            gap_between_feet_cm=partial.gap_between_feet_cm,
            stride_length_cm=stride_length_cm,
            speed_m_s=speed_m_s,
            cadence_steps_per_s=cadence_steps_per_s,
            double_support_s=overlap_s if overlap_s > 0 else None,
            stance_phase_s=contact_time_s,
        )
        self._rows.append(result)
        self._next_index += 1

        self._active.pop(partial.side, None)
        if partial.lift_time_s is not None:
            self._completed_intervals.append(
                (partial.side, partial.touch_time_s, partial.lift_time_s)
            )
            self._last_lift_time_s = partial.lift_time_s

    def _prior_overlap_duration(self, partial: _PartialRow, end_time_s: float) -> float:
        if partial.lift_time_s is None:
            return 0.0

        start = partial.touch_time_s
        end = partial.lift_time_s
        overlap_s = 0.0

        for side, other_start, other_end in self._completed_intervals:
            if side == partial.side or other_start >= start:
                continue
            overlap_s += _overlap_duration(start, end, other_start, other_end)

        for side, other in self._active.items():
            if side == partial.side or other.touch_time_s >= start:
                continue
            overlap_s += _overlap_duration(
                start,
                end,
                other.touch_time_s,
                other.lift_time_s if other.lift_time_s is not None else end_time_s,
            )

        return overlap_s


def _overlap_duration(
    start_a: float, end_a: float, start_b: float, end_b: float
) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


__all__ = ["RUNNING_OVERLAP_TOLERANCE_S", "TreadmillRunningAccumulator"]
