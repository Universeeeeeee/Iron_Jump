"""
treadmill_processor.py — Treadmill-mode processor (gait / running)

Pipeline per process_raw_frame call:
  1. extract_clusters(bits) -> List[Cluster]
  2. ClusterTracker.update() / get_active_tracks_view()
  3. ContactBasedGaitTracker.process_frame() -> List[GaitStepEvent]
  4. Delegate touch/lift events to TreadmillAccumulator
  5. Return event list for Qt signal emission

Step and stride distances combine treadmill travel with tracked contact
placement. LED clusters provide both event timing and spatial references.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any, Final, List

from config.treadmill_config import (
    Direction,
    TreadmillBaseConfig,
    TreadmillGaitConfig,
    TreadmillRunningConfig,
)
from config.treadmill_report import (
    GaitCycleRecord,
    MetricSummary,
    TreadmillGaitReport,
    TreadmillRunningReport,
    TreadmillStepResult,
    summarize,
)
from engine.contact_tracker import ContactBasedGaitTracker, GaitStepEvent
from engine.gait_cycle import GaitCycleBuilder
from engine.footprint_visualization import FootprintTimelineRecorder
from engine.modes.base import ModeProcessor
from engine.modes.treadmill_accumulator import TreadmillAccumulator
from engine.modes.treadmill_accumulator import belt_speed_m_s
from engine.modes.treadmill_accumulator import step_reference_cm
from engine.modes.treadmill_gait_accumulator import TreadmillGaitAccumulator
from engine.modes.treadmill_running_accumulator import TreadmillRunningAccumulator
from engine.spatial_clusterer import ClusterTracker, extract_clusters

log = logging.getLogger(__name__)

_CYCLE_SUMMARY_FIELDS: Final[tuple[str, ...]] = (
    "gait_cycle_s",
    "stride_length_cm",
    "stance_phase_s",
    "stance_phase_percent",
    "swing_phase_s",
    "swing_phase_percent",
    "step_time_s",
    "single_support_s",
    "single_support_percent",
    "total_double_support_s",
    "total_double_support_percent",
    "load_response_s",
    "load_response_percent",
    "pre_swing_s",
    "pre_swing_percent",
    "total_flight_time_s",
)


# Heel/toe reference offsets in cm from observed centroid.
# These are rough defaults used when we do not have an accurate foot-length
# snapshot.  The processor will prefer config.foot_length_cm_snapshot when set.
_DEFAULT_HEEL_OFFSET_CM: Final[float] = 15.0
_DEFAULT_TOE_OFFSET_CM: Final[float] = 15.0


class TreadmillProcessor:
    """
    ModeProcessor for treadmill gait and treadmill running modes.

    Converts raw contact-bit frames into touch/lift events via cluster
    extraction + cluster tracking + contact-based gait tracking, then
    delegates step accumulation to TreadmillAccumulator.
    """

    _DISPLAY_MODES: Final[dict[str, str]] = {
        "treadmill_gait": "跑步机步态",
        "treadmill_running": "跑步机跑步",
    }

    # ---- Protocol attributes ----

    name: str
    display_mode: str
    lift_count: int  # exposed for GaitEngine._check_stop_condition

    # ---- Internal components ----

    _config: TreadmillBaseConfig
    _direction: Direction
    _cluster_tracker: ClusterTracker
    _contact_tracker: ContactBasedGaitTracker
    _accumulator: TreadmillAccumulator
    _heel_offset_cm: float
    _toe_offset_cm: float

    def __init__(self, config: TreadmillBaseConfig, mode_name: str) -> None:
        self.name = mode_name
        self.display_mode = self._DISPLAY_MODES.get(mode_name, mode_name)
        self._config = config
        self._direction = config.direction
        self.lift_count = 0

        # Derive heel/toe offsets from foot-length snapshot if available.
        self._heel_offset_cm = _DEFAULT_HEEL_OFFSET_CM
        self._toe_offset_cm = _DEFAULT_TOE_OFFSET_CM
        fl = self._config.foot_length_cm_snapshot
        if fl is not None and fl > 0:
            # Approximate: heel and toe each occupy half the foot length
            self._heel_offset_cm = fl * 0.5
            self._toe_offset_cm = fl * 0.5

        self._cluster_tracker = ClusterTracker()
        self._contact_tracker = ContactBasedGaitTracker(
            min_step_interval=0.05,
            ignore_initial_contacts=True,
        )
        self._accumulator = self._make_accumulator()
        self._cycle_builder = GaitCycleBuilder()
        self._label_to_side: dict[str, str] = {}
        self._contact_side: dict[int, str] = {}
        self._last_assigned_side: str | None = None
        self._last_rel_time = 0.0
        self._live_cycle_cursor = 0
        self._visual_recorder = FootprintTimelineRecorder()
        self._last_clusters = []
        self._touch_reference_cm: dict[tuple[str, float], float | None] = {}
        self._pause_boundaries: list[float] = []

    # ---- ModeProcessor interface ----

    def reset(self) -> None:
        """Reset all internal state."""
        self.lift_count = 0
        self._pause_boundaries.clear()
        self._cluster_tracker = ClusterTracker()
        self._contact_tracker.reset()
        self._accumulator = self._make_accumulator()
        self._cycle_builder = GaitCycleBuilder()
        self._label_to_side = {}
        self._contact_side = {}
        self._last_assigned_side = None
        self._last_rel_time = 0.0
        self._live_cycle_cursor = 0
        self._visual_recorder.reset()
        self._last_clusters = []
        self._touch_reference_cm = {}

    def pause_boundary(self) -> None:
        self._pause_boundaries.append(self._last_rel_time)
        self._accumulator.pause_boundary(self._last_rel_time)
        self._cycle_builder.pause_boundary(self._last_rel_time)

    def process_raw_frame(
        self, contact_bits: List[int], rel_time: float, abs_time: float
    ) -> List[object]:
        """
        Process one frame of raw contact data.

        Pipeline:
          1. Extract spatial clusters from contact bits.
          2. Update cluster tracker with the new clusters.
          3. Get active track view and feed into contact-based gait tracker.
          4. Process touch/lift events -> emit to accumulator.

        Returns a list of event objects (currently GaitStepEvent) for
        the caller to re-emit via Qt signals.
        """
        # 1. Extract clusters
        self._last_rel_time = rel_time
        clusters = extract_clusters(contact_bits)
        self._last_clusters = clusters

        # 2. Update cluster tracker
        self._cluster_tracker.update(rel_time, clusters)

        # 3. Feed active tracks into contact-based gait tracker
        active_tracks = self._cluster_tracker.get_active_tracks_view()
        events = self._contact_tracker.process_frame(rel_time, active_tracks)
        self._visual_recorder.record_if_due(
            rel_time,
            contact_bits,
            self._contact_tracker,
        )

        # 4. Delegate touch/lift events to accumulator
        for ev in events:
            self._handle_step_event(ev, rel_time)

        return events

    def pop_visual_frames(self):
        return self._visual_recorder.pop_pending()

    def make_status_snapshot(self, rel_time: float) -> dict:
        ct = self._contact_tracker
        active_count = len(ct.foot_contact_queue)
        if active_count == 0:
            status = "腾空 / 离地"
        elif active_count == 1:
            status = "单脚支撑"
        else:
            status = f"多支撑 ({active_count}脚)"

        active_centroids = []
        for cid in ct.foot_contact_queue:
            if cid in ct.active_contacts:
                centroid = ct.active_contacts[cid].latest_centroid
                if centroid is not None:
                    active_centroids.append(centroid)

        valid_rows = [
            row
            for row in self._accumulator.rows
            if row.is_event_valid and row.is_included_in_statistics
        ]
        step_lengths = [
            row.step_length_cm
            for row in valid_rows
            if row.step_length_cm is not None
        ]
        speed_cm_s = [
            row.speed_m_s * 100.0
            for row in valid_rows
            if row.speed_m_s is not None
        ]
        if not speed_cm_s:
            speed_cm_s = [belt_speed_m_s(self._config) * 100.0]

        support_by_side: dict[str, list[float]] = {"left": [], "right": []}
        for row in valid_rows:
            if row.side in support_by_side and row.contact_time_s is not None:
                support_by_side[row.side].append(row.contact_time_s)

        latest_extra_metrics = {}
        left_support = support_by_side["left"]
        right_support = support_by_side["right"]
        if left_support and right_support:
            left_avg = sum(left_support) / len(left_support)
            right_avg = sum(right_support) / len(right_support)
            denom = max((left_avg + right_avg) / 2.0, 1e-6)
            latest_extra_metrics["imbalance_index"] = (
                abs(left_avg - right_avg) / denom * 100.0
            )

        gait_cycle_state = self._cycle_builder.make_live_snapshot(
            rel_time, completed_from_index=self._live_cycle_cursor
        )
        self._live_cycle_cursor = gait_cycle_state["completed_cycle_count"]

        return {
            "timestamp": rel_time,
            "status": status,
            "cluster_count": len(self._last_clusters),
            "active_centroids": active_centroids,
            "touch_count": ct.touch_count,
            "lift_count": self.lift_count,
            "stride_count": len(step_lengths),
            "stride_sum": sum(step_lengths),
            "latest_stride": step_lengths[-1] if step_lengths else None,
            "velocity_count": len(speed_cm_s),
            "velocity_sum": sum(speed_cm_s),
            "latest_velocity": speed_cm_s[-1] if speed_cm_s else None,
            "foot_a_support_times": list(support_by_side["left"]),
            "foot_b_support_times": list(support_by_side["right"]),
            "latest_extra_metrics": latest_extra_metrics,
            "gait_cycle_state": gait_cycle_state,
            "gait_cycle_asymmetry_percent": self._live_cycle_asymmetry(),
        }

    def build_report(
        self, reason: str, export_frames: tuple, export_timestamps: tuple
    ):
        """
        Build the final test report.

        Delegates to TreadmillAccumulator for per-step data and metric
        summaries, then wraps everything in the appropriate report type.
        """
        self._accumulator.apply_automatic_data_filter()
        rows = self._accumulator.rows
        gait_cycles = self._cycles_with_stride(
            self._cycles_with_row_inclusion(rows)
        )
        rows = self._rows_with_cycle_stride(rows, gait_cycles)
        config_snapshot = self._config.to_dict()
        config_snapshot["pause_boundaries_s"] = list(self._pause_boundaries)

        # Build metric summaries from valid, included rows
        valid_included = [
            r
            for r in rows
            if r.is_event_valid and r.is_included_in_statistics
        ]

        metric_summaries: dict[str, MetricSummary] = {}
        step_metric_values = {
            "contact_time_s": lambda row: row.contact_time_s,
            "step_length_cm": lambda row: row.step_length_cm,
            "flight_time_s": lambda row: row.flight_time_s,
            "cadence_steps_per_min": lambda row: (
                60.0 / row.step_time_s
                if row.step_time_s is not None and row.step_time_s > 0
                else None
            ),
        }
        for metric_name, value_getter in step_metric_values.items():
            values = tuple(
                value
                for row in valid_included
                if (value := value_getter(row)) is not None
            )
            if values:
                metric_summaries[metric_name] = summarize(values)

        # Build left/right breakdowns
        left_rows = [
            r for r in rows
            if r.side == "left" and r.is_event_valid and r.is_included_in_statistics
        ]
        right_rows = [
            r for r in rows
            if r.side == "right" and r.is_event_valid and r.is_included_in_statistics
        ]

        left_right: dict[str, MetricSummary] = {}
        for side_name, side_rows in [("left", left_rows), ("right", right_rows)]:
            for metric_name, value_getter in step_metric_values.items():
                side_values = tuple(
                    value
                    for row in side_rows
                    if (value := value_getter(row)) is not None
                )
                if side_values:
                    left_right[f"{side_name}_{metric_name}"] = summarize(
                        side_values
                    )

        # Asymmetry metrics
        asymmetry: dict[str, float] = {}
        for metric_name in step_metric_values:
            left_summary = left_right.get(f"left_{metric_name}")
            right_summary = left_right.get(f"right_{metric_name}")
            if (
                left_summary is None
                or right_summary is None
                or left_summary.count < 3
                or right_summary.count < 3
                or left_summary.mean is None
                or right_summary.mean is None
            ):
                continue
            denominator = (left_summary.mean + right_summary.mean) / 2.0
            if denominator:
                asymmetry[f"{metric_name}_percent"] = (
                    abs(left_summary.mean - right_summary.mean)
                    / denominator
                    * 100.0
                )

        cycle_metric_summaries, cycle_side_summaries, cycle_asymmetry = (
            self._build_cycle_summaries(gait_cycles)
        )

        base_kwargs: dict[str, Any] = dict(
            finish_reason=reason,
            touch_count=self._contact_tracker.touch_count,
            lift_count=self.lift_count,
            resolved_starting_foot=self._accumulator.resolved_starting_foot,
            starting_foot_source=self._accumulator.starting_foot_source,
            foot_length_cm_snapshot=self._config.foot_length_cm_snapshot,
            foot_length_source=self._config.foot_length_source,
            per_step_results=rows,
            metric_summaries=metric_summaries,
            left_right_results=left_right,
            asymmetry_metrics=asymmetry,
            report_config_snapshot=config_snapshot,
            export_frames=export_frames,
            export_timestamps=export_timestamps,
            visual_timeline=self._visual_recorder.frames,
            raw_gait_events=self._cycle_builder.raw_events,
            gait_cycles=gait_cycles,
            boundary_partials=self._cycle_builder.build_boundary_partials(
                self._last_rel_time
            ),
            cycle_metric_summaries=cycle_metric_summaries,
            cycle_side_summaries=cycle_side_summaries,
            cycle_asymmetry_percent=cycle_asymmetry,
        )

        if isinstance(self._config, TreadmillRunningConfig):
            return TreadmillRunningReport(**base_kwargs)
        return TreadmillGaitReport(**base_kwargs)

    # ---- Internal helpers ----

    def _make_accumulator(self) -> TreadmillAccumulator:
        if isinstance(self._config, TreadmillGaitConfig):
            return TreadmillGaitAccumulator(self._config)
        if isinstance(self._config, TreadmillRunningConfig):
            return TreadmillRunningAccumulator(self._config)
        raise TypeError(f"Unsupported treadmill config: {type(self._config).__name__}")

    def _handle_step_event(self, ev: object, rel_time: float) -> None:
        """
        Route a GaitStepEvent (touch/lift) to the TreadmillAccumulator.

        Converts cluster centroid position to heel/toe positions based on
        running direction.
        """
        if not isinstance(ev, GaitStepEvent):
            return

        side = self._resolve_event_side(ev)
        event_time = rel_time
        if ev.kind == "touch" and ev.contact.touch_time is not None:
            event_time = ev.contact.touch_time
        elif ev.kind == "lift" and ev.contact.lift_time is not None:
            event_time = ev.contact.lift_time

        centroid_cm = ev.contact.centroid_at_touch
        if centroid_cm is None:
            centroid_cm = ev.contact.latest_centroid
        has_spatial_reference = centroid_cm is not None
        geometry_centroid_cm = centroid_cm if centroid_cm is not None else 0.0

        # Heel/toe derived from centroid + foot-length offset.
        # For "Interface side", heel is left of centroid, toe is right.
        # (LED index increases left-to-right at the interface.)
        if self._direction == "Interface side":
            heel_cm = geometry_centroid_cm - self._heel_offset_cm
            toe_cm = geometry_centroid_cm + self._toe_offset_cm
        else:
            # Opposite side: reversed perspective
            heel_cm = geometry_centroid_cm + self._heel_offset_cm
            toe_cm = geometry_centroid_cm - self._toe_offset_cm

        if ev.kind == "touch":
            reference_cm = (
                step_reference_cm(
                    self._config, heel_cm=heel_cm, toe_cm=toe_cm
                )
                if has_spatial_reference
                else None
            )
            self._touch_reference_cm[(side, round(event_time, 9))] = (
                reference_cm
            )
            self._cycle_builder.record_touch(event_time, side)
            self._accumulator.record_touch(
                time_s=event_time, side=side, heel_cm=heel_cm, toe_cm=toe_cm
            )
        elif ev.kind == "lift":
            self.lift_count += 1
            row_count = len(self._accumulator.rows)
            self._accumulator.record_lift(time_s=event_time, side=side)
            included = None
            statistics_exclusion_reason = None
            quality_flags: tuple[str, ...] = ()
            if len(self._accumulator.rows) > row_count:
                row = self._accumulator.rows[-1]
                included = row.is_included_in_statistics
                statistics_exclusion_reason = row.statistics_exclusion_reason
                quality_flags = row.quality_flags
            self._cycle_builder.record_lift(
                event_time,
                side,
                is_included_in_statistics=included,
                statistics_exclusion_reason=statistics_exclusion_reason,
                quality_flags=quality_flags,
            )

    def _resolve_event_side(self, ev: GaitStepEvent) -> str:
        contact_id = ev.contact.contact_id
        known = self._contact_side.get(contact_id)
        if known is not None:
            return known

        label = ev.contact.foot_label
        side = self._label_to_side.get(label or "")
        if side is None and label in ("A", "B"):
            if not self._label_to_side and self._config.starting_foot_override:
                side = self._config.starting_foot_override
                opposite = "left" if side == "right" else "right"
                self._label_to_side[label] = side
                self._label_to_side["B" if label == "A" else "A"] = opposite
            else:
                side = "left" if label == "A" else "right"
                self._label_to_side[label] = side

        if side is None:
            if self._last_assigned_side is None:
                side = self._config.starting_foot_override or "unknown"
            elif self._last_assigned_side == "left":
                side = "right"
            elif self._last_assigned_side == "right":
                side = "left"
            else:
                side = "unknown"

        if ev.kind == "touch":
            self._contact_side[contact_id] = side
            if side in ("left", "right"):
                self._last_assigned_side = side
        return side

    def _cycles_with_row_inclusion(
        self, rows: tuple[TreadmillStepResult, ...]
    ) -> tuple[GaitCycleRecord, ...]:
        row_metadata = {}
        for row in rows:
            if row.time_s is None or row.contact_time_s is None:
                continue
            touch_time_s = row.time_s - row.contact_time_s
            row_metadata[(row.side, round(touch_time_s, 9))] = (
                row.is_included_in_statistics,
                row.statistics_exclusion_reason,
                row.quality_flags,
            )

        enriched_cycles = []
        for cycle in self._cycle_builder.completed_cycles:
            metadata = row_metadata.get(
                (cycle.side, round(cycle.start_time_s, 9))
            )
            if metadata is None:
                enriched_cycles.append(cycle)
                continue
            row_included, row_reason, row_quality_flags = metadata
            enriched_cycles.append(
                replace(
                    cycle,
                    is_included_in_statistics=(
                        cycle.is_included_in_statistics and row_included
                    ),
                    statistics_exclusion_reason=(
                        cycle.statistics_exclusion_reason
                        or (row_reason if not row_included else None)
                    ),
                    quality_flags=tuple(
                        dict.fromkeys(
                            (*cycle.quality_flags, *row_quality_flags)
                        )
                    ),
                )
            )
        return tuple(enriched_cycles)

    def _cycles_with_stride(
        self, cycles: tuple[GaitCycleRecord, ...]
    ) -> tuple[GaitCycleRecord, ...]:
        direction_sign = (
            -1 if self._config.direction == "Opposite side" else 1
        )
        speed_cm_s = belt_speed_m_s(self._config) * 100.0
        enriched = []
        for cycle in cycles:
            start_ref = self._touch_reference_cm.get(
                (cycle.side, round(cycle.start_time_s, 9))
            )
            end_ref = self._touch_reference_cm.get(
                (cycle.side, round(cycle.end_time_s, 9))
            )
            stride_cm = None
            quality_flags = cycle.quality_flags
            if (
                cycle.side in ("left", "right")
                and cycle.gait_cycle_s > 0
                and start_ref is not None
                and end_ref is not None
            ):
                candidate = (
                    speed_cm_s * cycle.gait_cycle_s
                    + direction_sign * (end_ref - start_ref)
                )
                if candidate > 0:
                    stride_cm = candidate
                else:
                    quality_flags = tuple(
                        dict.fromkeys(
                            (*quality_flags, "non_positive_stride_length")
                        )
                    )
            enriched.append(
                replace(
                    cycle,
                    stride_length_cm=stride_cm,
                    quality_flags=quality_flags,
                )
            )
        return tuple(enriched)

    @staticmethod
    def _rows_with_cycle_stride(
        rows: tuple[TreadmillStepResult, ...],
        cycles: tuple[GaitCycleRecord, ...],
    ) -> tuple[TreadmillStepResult, ...]:
        stride_by_endpoint = {
            (cycle.side, round(cycle.end_time_s, 9)): cycle.stride_length_cm
            for cycle in cycles
            if cycle.stride_length_cm is not None
        }
        enriched = []
        for row in rows:
            if row.time_s is None or row.contact_time_s is None:
                enriched.append(row)
                continue
            touch_time_s = row.time_s - row.contact_time_s
            stride_cm = stride_by_endpoint.get(
                (row.side, round(touch_time_s, 9))
            )
            enriched.append(
                replace(row, stride_length_cm=stride_cm)
                if stride_cm is not None
                else row
            )
        return tuple(enriched)

    def _build_cycle_summaries(
        self, source_cycles: tuple[GaitCycleRecord, ...] | None = None
    ):
        cycles = [
            cycle for cycle in (
                source_cycles
                if source_cycles is not None
                else self._cycle_builder.completed_cycles
            )
            if cycle.is_included_in_statistics
        ]
        overall: dict[str, MetricSummary] = {}
        by_side: dict[str, dict[str, MetricSummary]] = {
            "left": {},
            "right": {},
        }
        asymmetry: dict[str, float] = {}

        for field_name in _CYCLE_SUMMARY_FIELDS:
            all_values = tuple(
                value for cycle in cycles
                if (value := getattr(cycle, field_name)) is not None
            )
            overall[field_name] = summarize(all_values)
            for side in ("left", "right"):
                side_values = tuple(
                    value for cycle in cycles
                    if cycle.side == side
                    and (value := getattr(cycle, field_name)) is not None
                )
                by_side[side][field_name] = summarize(side_values)

            left_mean = by_side["left"][field_name].mean
            right_mean = by_side["right"][field_name].mean
            if (
                by_side["left"][field_name].count < 3
                or by_side["right"][field_name].count < 3
                or left_mean is None
                or right_mean is None
            ):
                continue
            denominator = (left_mean + right_mean) / 2.0
            if denominator:
                asymmetry[field_name] = (
                    abs(left_mean - right_mean) / denominator * 100.0
                )

        return overall, by_side, asymmetry

    def _live_cycle_asymmetry(self) -> dict[str, float]:
        side_values = {
            side: [
                cycle.gait_cycle_s
                for cycle in self._cycle_builder.completed_cycles
                if cycle.side == side and cycle.is_included_in_statistics
            ]
            for side in ("left", "right")
        }
        if not side_values["left"] or not side_values["right"]:
            return {}
        left_mean = sum(side_values["left"]) / len(side_values["left"])
        right_mean = sum(side_values["right"]) / len(side_values["right"])
        denominator = (left_mean + right_mean) / 2.0
        if not denominator:
            return {}
        return {
            "gait_cycle_s": abs(left_mean - right_mean) / denominator * 100.0
        }


__all__ = ["TreadmillProcessor"]
