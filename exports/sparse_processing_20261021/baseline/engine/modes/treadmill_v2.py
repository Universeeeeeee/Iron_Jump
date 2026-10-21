"""Pure helpers for treadmill V2 foot-reference length calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from config.treadmill_config import Direction, FootSide, FootSideOverride


FootReferenceSource = Literal[
    "touch_boundary",
    "stable_touch_window",
    "confirmed_frame",
    "fallback_centroid",
]
LengthMethod = Literal["belt_plus_device_delta", "speed_only"]
LengthQuality = Literal[
    "ok",
    "missing_prev_ref",
    "unknown_side",
    "fallback_speed_only",
    "track_conflict",
    "unsafe_reference",
]


@dataclass(frozen=True)
class FootReference:
    heel_cm: float
    toe_cm: float
    source: FootReferenceSource


@dataclass(frozen=True)
class TreadmillContactSnapshot:
    contact_id: int
    foot_side: FootSide
    time_s: float
    reference_x_cm: float | None
    heel_cm: float
    toe_cm: float
    source: FootReferenceSource
    length_quality: LengthQuality = "ok"
    reference_projected_to_event: bool = False

    def is_semantically_safe_for_device_delta(self) -> bool:
        if self.source == "touch_boundary":
            return True
        if self.source == "stable_touch_window":
            return self.reference_projected_to_event
        return False


@dataclass(frozen=True)
class LengthResult:
    length_cm: float | None
    belt_distance_cm: float | None
    device_delta_cm: float | None
    direction_sign: int
    method: LengthMethod
    quality: LengthQuality


class TreadmillCoordinateSystem:
    @staticmethod
    def belt_speed_cm_s(config_speed_kmh: float) -> float:
        return config_speed_kmh / 3.6 * 100.0

    @staticmethod
    def direction_sign(direction: Direction) -> int:
        if direction == "Opposite side":
            return 1
        return -1

    @staticmethod
    def heel_toe_from_cluster(
        direction: Direction,
        cluster_start_cm: float | None,
        cluster_end_cm: float | None,
        centroid_cm: float,
        foot_length_cm: float | None,
    ) -> FootReference:
        if cluster_start_cm is not None and cluster_end_cm is not None:
            start = min(cluster_start_cm, cluster_end_cm)
            end = max(cluster_start_cm, cluster_end_cm)
            if direction == "Interface side":
                return FootReference(
                    heel_cm=start,
                    toe_cm=end,
                    source="touch_boundary",
                )
            return FootReference(
                heel_cm=end,
                toe_cm=start,
                source="touch_boundary",
            )

        half_length = foot_length_cm * 0.5 if foot_length_cm and foot_length_cm > 0 else 0.0
        if direction == "Interface side":
            heel_cm = centroid_cm - half_length
            toe_cm = centroid_cm + half_length
        else:
            heel_cm = centroid_cm + half_length
            toe_cm = centroid_cm - half_length
        return FootReference(
            heel_cm=heel_cm,
            toe_cm=toe_cm,
            source="fallback_centroid",
        )


class TreadmillLengthCalculator:
    @staticmethod
    def step_length(
        prev_ref_x_cm: float | None,
        curr_ref_x_cm: float | None,
        step_time_s: float | None,
        belt_speed_cm_s: float,
        direction: Direction,
    ) -> LengthResult:
        return TreadmillLengthCalculator._length(
            prev_ref_x_cm=prev_ref_x_cm,
            curr_ref_x_cm=curr_ref_x_cm,
            delta_time_s=step_time_s,
            belt_speed_cm_s=belt_speed_cm_s,
            direction=direction,
            missing_quality="missing_prev_ref",
        )

    @staticmethod
    def stride_length(
        prev_same_side_ref_x_cm: float | None,
        curr_ref_x_cm: float | None,
        stride_time_s: float | None,
        belt_speed_cm_s: float,
        direction: Direction,
    ) -> LengthResult:
        return TreadmillLengthCalculator._length(
            prev_ref_x_cm=prev_same_side_ref_x_cm,
            curr_ref_x_cm=curr_ref_x_cm,
            delta_time_s=stride_time_s,
            belt_speed_cm_s=belt_speed_cm_s,
            direction=direction,
            missing_quality="missing_prev_ref",
        )

    @staticmethod
    def step_length_from_snapshots(
        previous: TreadmillContactSnapshot | None,
        current: TreadmillContactSnapshot,
        step_time_s: float | None,
        belt_speed_cm_s: float,
        direction: Direction,
    ) -> LengthResult:
        quality = TreadmillLengthCalculator._snapshot_quality(previous, current)
        if quality != "ok":
            return TreadmillLengthCalculator.speed_only(
                delta_time_s=step_time_s,
                belt_speed_cm_s=belt_speed_cm_s,
                direction=direction,
                quality=quality,
            )
        return TreadmillLengthCalculator.step_length(
            prev_ref_x_cm=previous.reference_x_cm if previous else None,
            curr_ref_x_cm=current.reference_x_cm,
            step_time_s=step_time_s,
            belt_speed_cm_s=belt_speed_cm_s,
            direction=direction,
        )

    @staticmethod
    def stride_length_from_snapshots(
        previous_same_side: TreadmillContactSnapshot | None,
        current: TreadmillContactSnapshot,
        stride_time_s: float | None,
        belt_speed_cm_s: float,
        direction: Direction,
    ) -> LengthResult:
        quality = TreadmillLengthCalculator._snapshot_quality(
            previous_same_side, current
        )
        if quality != "ok":
            return TreadmillLengthCalculator.speed_only(
                delta_time_s=stride_time_s,
                belt_speed_cm_s=belt_speed_cm_s,
                direction=direction,
                quality=quality,
            )
        return TreadmillLengthCalculator.stride_length(
            prev_same_side_ref_x_cm=(
                previous_same_side.reference_x_cm if previous_same_side else None
            ),
            curr_ref_x_cm=current.reference_x_cm,
            stride_time_s=stride_time_s,
            belt_speed_cm_s=belt_speed_cm_s,
            direction=direction,
        )

    @staticmethod
    def speed_only(
        delta_time_s: float | None,
        belt_speed_cm_s: float,
        direction: Direction,
        quality: LengthQuality,
    ) -> LengthResult:
        direction_sign = TreadmillCoordinateSystem.direction_sign(direction)
        if delta_time_s is None or delta_time_s <= 0:
            return LengthResult(
                length_cm=None,
                belt_distance_cm=None,
                device_delta_cm=None,
                direction_sign=direction_sign,
                method="speed_only",
                quality=quality,
            )
        belt_distance_cm = belt_speed_cm_s * delta_time_s
        return LengthResult(
            length_cm=belt_distance_cm,
            belt_distance_cm=belt_distance_cm,
            device_delta_cm=None,
            direction_sign=direction_sign,
            method="speed_only",
            quality=quality,
        )

    @staticmethod
    def _length(
        prev_ref_x_cm: float | None,
        curr_ref_x_cm: float | None,
        delta_time_s: float | None,
        belt_speed_cm_s: float,
        direction: Direction,
        missing_quality: LengthQuality,
    ) -> LengthResult:
        direction_sign = TreadmillCoordinateSystem.direction_sign(direction)
        if delta_time_s is None or delta_time_s <= 0:
            return LengthResult(
                length_cm=None,
                belt_distance_cm=None,
                device_delta_cm=None,
                direction_sign=direction_sign,
                method="speed_only",
                quality=missing_quality,
            )
        belt_distance_cm = belt_speed_cm_s * delta_time_s
        if prev_ref_x_cm is None or curr_ref_x_cm is None:
            return LengthResult(
                length_cm=belt_distance_cm,
                belt_distance_cm=belt_distance_cm,
                device_delta_cm=None,
                direction_sign=direction_sign,
                method="speed_only",
                quality=missing_quality,
            )

        device_delta_cm = curr_ref_x_cm - prev_ref_x_cm
        return LengthResult(
            length_cm=belt_distance_cm + direction_sign * device_delta_cm,
            belt_distance_cm=belt_distance_cm,
            device_delta_cm=device_delta_cm,
            direction_sign=direction_sign,
            method="belt_plus_device_delta",
            quality="ok",
        )

    @staticmethod
    def _snapshot_quality(
        previous: TreadmillContactSnapshot | None,
        current: TreadmillContactSnapshot,
    ) -> LengthQuality:
        if previous is None:
            return "missing_prev_ref"
        if previous.foot_side == "unknown" or current.foot_side == "unknown":
            return "unknown_side"
        if previous.source == "confirmed_frame" or current.source == "confirmed_frame":
            return "fallback_speed_only"
        if (
            previous.reference_x_cm is None
            or current.reference_x_cm is None
        ):
            return "missing_prev_ref"
        if (
            not previous.is_semantically_safe_for_device_delta()
            or not current.is_semantically_safe_for_device_delta()
        ):
            return "unsafe_reference"
        return "ok"


class TreadmillFootResolver:
    def resolve_touch(
        self,
        contact_id: int,
        active_sides_by_contact_id: Mapping[int, FootSide],
        previous_touch_side: FootSide | None,
        manual_starting_foot: FootSideOverride | None,
        diagnostics: dict[str, object] | None = None,
    ) -> FootSide:
        if diagnostics is None:
            diagnostics = {}

        if manual_starting_foot in ("left", "right"):
            diagnostics["foot_resolution_source"] = "manual_override"
            return manual_starting_foot

        active_sides = {
            side
            for cid, side in active_sides_by_contact_id.items()
            if cid != contact_id and side in ("left", "right")
        }
        if len(active_sides) == 1:
            active_side = next(iter(active_sides))
            diagnostics["foot_resolution_source"] = "active_opposite"
            return "right" if active_side == "left" else "left"
        if len(active_sides) > 1:
            diagnostics["foot_resolution_source"] = "track_conflict"
            return "unknown"

        if previous_touch_side in ("left", "right"):
            diagnostics["foot_resolution_source"] = "alternating"
            return "right" if previous_touch_side == "left" else "left"

        diagnostics["foot_resolution_source"] = "bootstrap_first_contact"
        return "left"


__all__ = [
    "FootReference",
    "FootReferenceSource",
    "LengthMethod",
    "LengthQuality",
    "LengthResult",
    "TreadmillContactSnapshot",
    "TreadmillCoordinateSystem",
    "TreadmillFootResolver",
    "TreadmillLengthCalculator",
]
