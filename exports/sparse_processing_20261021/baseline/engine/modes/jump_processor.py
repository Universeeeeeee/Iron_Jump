"""
jump_processor.py — Jump Test mode processor

Wraps SingleFootDetector and maintains jump statistics (air_times,
contact_times, cycle_times) used to build the final JumpTestReport.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from config.test_config import TestConfig
from config.test_report import (
    G,
    JumpQualityNoticeRecord,
    JumpResultRecord,
    JumpTestReport,
    _cadences,
    _jump_heights,
    _max_or_zero,
    _mean,
    _min_or_zero,
    _population_std,
    _positive_values,
)
from ..single_foot_tracker import SingleFootDetector, LedFrame, FootEvent

log = logging.getLogger(__name__)

FRAME_GAP_WARNING_S = 0.020
TOUCH_MIN_CLUSTER_LENGTH = 4
TOUCH_MAX_CLUSTER_LENGTH = 50


class JumpProcessor:
    """Mode processor for Jump Test (vertical jump analysis).

    Owns the SingleFootDetector and accumulates jump statistics.
    """

    name = "jump"
    display_mode = "纵跳"

    def __init__(self, config: TestConfig) -> None:
        self._config = config

        # ---- 检测器 ----
        self._detector = SingleFootDetector(
            touch_ratio_threshold=0.12,
            lift_ratio_threshold=0.05,
            confirm_samples=2,
            touch_min_cluster_length=TOUCH_MIN_CLUSTER_LENGTH,
            touch_max_cluster_length=TOUCH_MAX_CLUSTER_LENGTH,
        )

        # ---- 纵跳统计 ----
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time: Optional[float] = None
        self.last_lift_time: Optional[float] = None
        self.cycle_times: List[float] = []
        self.air_times: List[float] = []
        self.contact_times: List[float] = []
        self._jump_records: List[dict] = []
        self._quality_notices: List[JumpQualityNoticeRecord] = []
        self._pending_quality_notices: List[JumpQualityNoticeRecord] = []
        self._last_frame_time: Optional[float] = None
        self._current_flight_had_gap = False
        self._last_touch_included = False

    @property
    def completed_jumps(self) -> int:
        """已完成且纳入统计的跳跃数。"""
        return len(self.air_times)

    @property
    def quality_notices(self) -> tuple[JumpQualityNoticeRecord, ...]:
        return tuple(self._quality_notices)

    def pop_pending_quality_notices(self) -> tuple[JumpQualityNoticeRecord, ...]:
        notices = tuple(self._pending_quality_notices)
        self._pending_quality_notices.clear()
        return notices

    def pause_boundary(self) -> None:
        """作废跨暂停的未闭合配对，恢复后无事件重建基线。"""
        self.last_touch_time = None
        self.last_lift_time = None
        self._last_frame_time = None
        self._current_flight_had_gap = False
        self._last_touch_included = False
        self._detector.begin_resync()

    def reset(self) -> None:
        """Reset all jump statistics and detector."""
        self.touch_count = 0
        self.lift_count = 0
        self.last_touch_time = None
        self.last_lift_time = None
        self.cycle_times.clear()
        self.air_times.clear()
        self.contact_times.clear()
        self._jump_records.clear()
        self._quality_notices.clear()
        self._pending_quality_notices.clear()
        self._last_frame_time = None
        self._current_flight_had_gap = False
        self._last_touch_included = False
        self._detector = SingleFootDetector(
            touch_ratio_threshold=0.12,
            lift_ratio_threshold=0.05,
            confirm_samples=2,
            touch_min_cluster_length=TOUCH_MIN_CLUSTER_LENGTH,
            touch_max_cluster_length=TOUCH_MAX_CLUSTER_LENGTH,
        )

    def process_raw_frame(
        self, contact_bits: List[int], rel_time: float, abs_time: float
    ) -> List[object]:
        """Process one frame using SingleFootDetector.

        Returns list of FootEvent objects to be re-emitted by GaitEngine.
        """
        frame = LedFrame(timestamp=rel_time, bits=contact_bits)
        events: List[object] = []
        if (
            self._last_frame_time is not None
            and self.last_lift_time is not None
            and self._detector.state == "air"
            and rel_time - self._last_frame_time > FRAME_GAP_WARNING_S
        ):
            self._current_flight_had_gap = True
        self._last_frame_time = rel_time

        detector_events = self._detector.consume(frame)
        for notice in self._detector.pop_quality_notices():
            record = JumpQualityNoticeRecord(
                kind=notice.kind,
                time_s=notice.time,
                cluster_length=notice.cluster_length,
                ratio=notice.ratio,
            )
            self._quality_notices.append(record)
            self._pending_quality_notices.append(record)

        for ev in detector_events:
            self._accumulate_hop_stats(ev)
            events.append(ev)
        return events

    def _append_jump_record(
        self,
        *,
        lift_time_s: float | None,
        touch_time_s: float | None,
        air_time_s: float | None,
        contact_time_s: float | None,
        cycle_time_s: float | None,
        included: bool,
        exclusion_reason: str | None,
        quality_flags: List[str] | tuple[str, ...],
    ) -> None:
        height = (
            0.5 * G * (air_time_s / 2) ** 2
            if air_time_s is not None and air_time_s > 0
            else None
        )
        cadence = (
            60.0 / cycle_time_s
            if cycle_time_s is not None and cycle_time_s > 0
            else None
        )
        self._jump_records.append(
            {
                "index": len(self._jump_records) + 1,
                "lift_time_s": lift_time_s,
                "touch_time_s": touch_time_s,
                "air_time_s": air_time_s,
                "jump_height_m": height,
                "contact_time_s": contact_time_s,
                "cycle_time_s": cycle_time_s,
                "cadence_jumps_per_min": cadence,
                "is_included_in_statistics": included,
                "statistics_exclusion_reason": exclusion_reason,
                "quality_flags": tuple(dict.fromkeys(quality_flags)),
            }
        )

    def _accumulate_hop_stats(self, ev: FootEvent) -> None:
        """Accumulate jump statistics from a FootEvent.

        Filtering rules per OptoJump manual 4.2.2.2:
          - min_contact_time: contact below this threshold is merged into
            associated flight time.
          - min_flight_time: flight below this threshold is merged into
            associated contact time.
          - max_flight_time: flight above this threshold is discarded.
        """
        ev._air_time = None
        ev._contact_time = None
        ev._hop_height = None

        cfg = self._config

        if ev.kind.lower() == "touch":
            self.touch_count += 1
            touch_included = False
            previous_touch = self.last_touch_time
            cycle_time = None
            if previous_touch is not None and self._last_touch_included:
                candidate_cycle = ev.time - previous_touch
                if candidate_cycle > 0:
                    cycle_time = candidate_cycle
            if self.last_lift_time is not None:
                air_time = ev.time - self.last_lift_time
                if air_time > 0:
                    contact_time = self.contact_times[-1] if self.contact_times else None
                    flags = list(ev.quality_flags)
                    if self._current_flight_had_gap:
                        flags.append("frame_gap_during_flight")
                    review_ms = self._config.flight_time_review_threshold
                    if review_ms > 0 and air_time * 1000 > review_ms:
                        flags.append("flight_time_above_review_threshold")
                    if cfg.max_flight_time > 0 and air_time * 1000 > cfg.max_flight_time:
                        log.debug("air_time %.1fms > max_flight_time %dms, discarded",
                                  air_time * 1000, cfg.max_flight_time)
                        self._append_jump_record(
                            lift_time_s=self.last_lift_time,
                            touch_time_s=ev.time,
                            air_time_s=air_time,
                            contact_time_s=contact_time,
                            cycle_time_s=cycle_time,
                            included=False,
                            exclusion_reason="flight_above_configured_max",
                            quality_flags=flags,
                        )
                    elif cfg.min_flight_time > 0 and air_time * 1000 < cfg.min_flight_time:
                        log.debug("air_time %.1fms < min_flight_time %dms, merged to contact",
                                  air_time * 1000, cfg.min_flight_time)
                        if self.contact_times:
                            self.contact_times[-1] += air_time
                        self._append_jump_record(
                            lift_time_s=self.last_lift_time,
                            touch_time_s=ev.time,
                            air_time_s=air_time,
                            contact_time_s=contact_time,
                            cycle_time_s=cycle_time,
                            included=False,
                            exclusion_reason="flight_below_configured_min",
                            quality_flags=flags,
                        )
                    else:
                        self.air_times.append(air_time)
                        if cycle_time is not None:
                            self.cycle_times.append(cycle_time)
                        ev._air_time = air_time
                        ev._hop_height = 0.5 * G * (air_time / 2) ** 2
                        ev._contact_time = contact_time
                        self._append_jump_record(
                            lift_time_s=self.last_lift_time,
                            touch_time_s=ev.time,
                            air_time_s=air_time,
                            contact_time_s=contact_time,
                            cycle_time_s=cycle_time,
                            included=True,
                            exclusion_reason=None,
                            quality_flags=flags,
                        )
                        touch_included = True
            self.last_touch_time = ev.time
            self._last_touch_included = touch_included
            self._current_flight_had_gap = False

        elif ev.kind.lower() == "lift":
            self.lift_count += 1
            if self.last_touch_time is not None and self.lift_count > 1:
                contact_time = ev.time - self.last_touch_time
                if contact_time > 0:
                    if cfg.min_contact_time > 0 and contact_time * 1000 < cfg.min_contact_time:
                        log.debug("contact_time %.1fms < min_contact_time %dms, merged to flight",
                                  contact_time * 1000, cfg.min_contact_time)
                        if self.air_times and self._last_touch_included:
                            self.air_times[-1] += contact_time
                            for record in reversed(self._jump_records):
                                if record["is_included_in_statistics"]:
                                    record["air_time_s"] = self.air_times[-1]
                                    record["jump_height_m"] = (
                                        0.5 * G * (self.air_times[-1] / 2) ** 2
                                    )
                                    break
                    else:
                        self.contact_times.append(contact_time)
            self.last_lift_time = ev.time
            self._current_flight_had_gap = False

    def build_report(
        self, reason: str, export_frames: tuple, export_timestamps: tuple
    ) -> JumpTestReport:
        """Build the JumpTestReport from accumulated statistics."""
        air = _positive_values(self.air_times)
        contact = _positive_values(self.contact_times)
        cycle = _positive_values(self.cycle_times)

        heights = _jump_heights(air)
        cadence_values = _cadences(cycle)
        avg_air = _mean(air)
        avg_contact = _mean(contact)
        avg_cycle = _mean(cycle)

        return JumpTestReport(
            touch_count=self.touch_count,
            lift_count=self.lift_count,
            air_times=air,
            contact_times=contact,
            cycle_times=cycle,
            avg_jump_height=_mean(heights),
            max_jump_height=_max_or_zero(heights),
            avg_air_time=avg_air,
            max_air_time=_max_or_zero(air),
            avg_contact_time=avg_contact,
            avg_cadence=60.0 / avg_cycle if avg_cycle > 0 else None,
            finish_reason=reason,
            jump_heights=heights,
            cadences=cadence_values,
            min_jump_height=_min_or_zero(heights),
            std_jump_height=_population_std(heights),
            min_air_time=_min_or_zero(air),
            std_air_time=_population_std(air),
            min_contact_time=_min_or_zero(contact),
            max_contact_time=_max_or_zero(contact),
            std_contact_time=_population_std(contact),
            export_frames=export_frames,
            export_timestamps=export_timestamps,
            jump_results=tuple(
                JumpResultRecord(**record) for record in self._jump_records
            ),
            quality_notices=tuple(self._quality_notices),
            report_config_snapshot={
                **self._config.to_dict(),
                "touch_min_cluster_length": TOUCH_MIN_CLUSTER_LENGTH,
                "touch_max_cluster_length": TOUCH_MAX_CLUSTER_LENGTH,
                "frame_gap_warning_ms": int(FRAME_GAP_WARNING_S * 1000),
            },
        )
