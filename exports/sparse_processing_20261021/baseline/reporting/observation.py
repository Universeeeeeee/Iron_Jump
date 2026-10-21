"""Build deterministic, model-readable observations from complete report packages."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Sequence

from .metric_catalog import METRIC_CATALOG
from .models import (
    AgentObservation,
    AnalysisToolCapability,
    AnalysisSketch,
    CompactSeriesRow,
    CompactSessionSeries,
    CrossMetricAlignedView,
    DataAccessScope,
    DataScopeAvailability,
    QualitySummary,
    RecordSet,
    ReportDataPackage,
    ReportManifest,
    ScreeningCue,
    SegmentSummary,
    SemanticRecord,
    SummaryValue,
)


OBSERVATION_BUILDER_VERSION = "agent-observation/1.0"
OBSERVATION_TOKEN_BUDGET = 12_000
DEFAULT_MAX_SERIES_ROWS = 80


class ObservationBuilder:
    def __init__(
        self,
        *,
        include_analysis_sketch: bool = True,
        include_compact_series: bool = True,
        include_screening_cues: bool = True,
    ):
        self._include_analysis_sketch = include_analysis_sketch
        self._include_compact_series = include_compact_series
        self._include_screening_cues = include_screening_cues

    def build(
        self,
        package: ReportDataPackage,
        manifest: ReportManifest,
        availability: DataScopeAvailability,
        access_scope: DataAccessScope,
        capabilities: Sequence[AnalysisToolCapability],
    ) -> AgentObservation:
        if manifest.package_id != package.metadata.package_id:
            raise ValueError("manifest and package do not reference the same snapshot")
        if manifest.package_digest != package.metadata.package_digest:
            raise ValueError("manifest digest does not match package digest")
        sketch = (
            build_analysis_sketch(package)
            if self._include_analysis_sketch
            else AnalysisSketch(
                overall=(),
                temporal_segments=(),
                side_segments=(),
                cross_metric_aligned=(),
            )
        )
        max_series_rows = DEFAULT_MAX_SERIES_ROWS
        compact = (
            tuple(build_compact_session_series(package, max_rows=max_series_rows))
            if self._include_compact_series
            else ()
        )
        quality = build_quality_summary(package)
        cues = (
            build_screening_cues(package, sketch, quality)
            if self._include_screening_cues
            else ()
        )
        source_refs = (
            package.metadata.package_id,
            *(fact.fact_id for fact in package.scalar_facts),
            *(record_set.record_set_id for record_set in package.record_sets),
            *(flag.quality_flag_id for flag in package.quality_flags),
        )
        observation = AgentObservation(
            report_context=package.context,
            report_manifest=manifest,
            authoritative_facts=package.scalar_facts,
            analysis_sketch=sketch,
            compact_session_series=compact,
            quality_summary=quality,
            screening_cues=cues,
            data_scope_availability=availability,
            authorized_data_scopes=access_scope,
            available_analysis_capabilities=tuple(capabilities),
            source_refs=tuple(source_refs),
            builder_version=OBSERVATION_BUILDER_VERSION,
        )
        while (
            estimate_observation_tokens(serialize_observation(observation))
            > OBSERVATION_TOKEN_BUDGET
            and max_series_rows > 20
            and self._include_compact_series
        ):
            max_series_rows = max(20, max_series_rows - 10)
            observation = observation.model_copy(
                update={
                    "compact_session_series": tuple(
                        build_compact_session_series(
                            package, max_rows=max_series_rows
                        )
                    )
                }
            )
        return observation


def _included_records(record_set: RecordSet) -> tuple[SemanticRecord, ...]:
    return tuple(
        record
        for record in record_set.records
        if record.status.validity == "valid"
        and record.status.inclusion == "included"
    )


def _summary(
    metric_code: str,
    records: Sequence[SemanticRecord],
) -> SummaryValue:
    values = [
        item.value
        for record in records
        if (item := record.values.get(metric_code)) is not None
        and item.state == "present"
        and item.value is not None
    ]
    definition = METRIC_CATALOG[metric_code]
    if not values:
        return SummaryValue(
            metric_code=metric_code,
            count=0,
            unit=definition.unit,
        )
    mean = sum(values) / len(values)
    std = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
    return SummaryValue(
        metric_code=metric_code,
        count=len(values),
        mean=mean,
        std=std,
        min=min(values),
        max=max(values),
        unit=definition.unit,
    )


def _segment_records(
    records: Sequence[SemanticRecord],
) -> tuple[tuple[int, tuple[SemanticRecord, ...]], ...]:
    if not records:
        return ()
    segments: list[list[SemanticRecord]] = [[], [], [], []]
    total = len(records)
    for position, record in enumerate(records):
        segment_index = min(3, position * 4 // total)
        segments[segment_index].append(record)
    return tuple(
        (segment_index, tuple(segment))
        for segment_index, segment in enumerate(segments)
        if segment
    )


def build_analysis_sketch(package: ReportDataPackage) -> AnalysisSketch:
    overall: list[SummaryValue] = []
    temporal: list[SegmentSummary] = []
    side_segments: list[SegmentSummary] = []
    cross_metric: list[CrossMetricAlignedView] = []
    for record_set in package.record_sets:
        included = _included_records(record_set)
        overall.extend(
            _summary(metric_code, included)
            for metric_code in record_set.metric_codes
        )
        for segment_index, segment in _segment_records(included):
            summaries = tuple(
                _summary(metric_code, segment)
                for metric_code in record_set.metric_codes
            )
            temporal.append(
                SegmentSummary(
                    record_set_id=record_set.record_set_id,
                    segment_index=segment_index,
                    start_ordinal=segment[0].ordinal,
                    end_ordinal=segment[-1].ordinal,
                    metrics=summaries,
                )
            )
            cross_metric.append(
                CrossMetricAlignedView(
                    record_set_id=record_set.record_set_id,
                    segment_index=segment_index,
                    record_refs=tuple(record.record_id for record in segment),
                    metric_summaries=summaries,
                )
            )
            for side in ("left", "right"):
                side_records = tuple(record for record in segment if record.side == side)
                if not side_records:
                    continue
                side_segments.append(
                    SegmentSummary(
                        record_set_id=record_set.record_set_id,
                        segment_index=segment_index,
                        start_ordinal=side_records[0].ordinal,
                        end_ordinal=side_records[-1].ordinal,
                        side=side,
                        metrics=tuple(
                            _summary(metric_code, side_records)
                            for metric_code in record_set.metric_codes
                        ),
                    )
                )
    return AnalysisSketch(
        overall=tuple(overall),
        temporal_segments=tuple(temporal),
        side_segments=tuple(side_segments),
        cross_metric_aligned=tuple(cross_metric),
    )


def _sample_indices(total: int, max_rows: int) -> tuple[int, ...]:
    if total <= max_rows:
        return tuple(range(total))
    if max_rows < 20:
        raise ValueError("max_rows must be at least 20")
    first = list(range(10))
    last = list(range(total - 10, total))
    remaining = max_rows - 20
    middle_start = 10
    middle_end = total - 10
    if remaining == 0:
        return tuple(first + last)
    middle = [
        middle_start + (index * (middle_end - middle_start - 1) // max(1, remaining - 1))
        for index in range(remaining)
    ]
    return tuple(sorted(set(first + middle + last)))


def build_compact_session_series(
    package: ReportDataPackage,
    max_rows: int = DEFAULT_MAX_SERIES_ROWS,
) -> list[CompactSessionSeries]:
    result: list[CompactSessionSeries] = []
    for record_set in package.record_sets:
        indices = _sample_indices(len(record_set.records), max_rows)
        rows = tuple(
            CompactSeriesRow(
                record_ref=record.record_id,
                ordinal=record.ordinal,
                timestamp_s=record.timestamp_s,
                side=record.side,
                inclusion=record.status.inclusion,
                validity=record.status.validity,
                quality_flag_refs=record.quality_flag_ids,
                values={
                    metric_code: (
                        record.values[metric_code].value
                        if record.values[metric_code].state == "present"
                        else None
                    )
                    for metric_code in record_set.metric_codes
                },
            )
            for index in indices
            for record in (record_set.records[index],)
        )
        result.append(
            CompactSessionSeries(
                record_set_id=record_set.record_set_id,
                metric_codes=record_set.metric_codes,
                rows=rows,
                total_rows=len(record_set.records),
                returned_rows=len(rows),
                sampling_policy=(
                    "all_rows" if len(record_set.records) <= max_rows
                    else f"first_10_last_10_deterministic_even_to_{max_rows}"
                ),
            )
        )
    return result


def build_quality_summary(package: ReportDataPackage) -> QualitySummary:
    records = [record for record_set in package.record_sets for record in record_set.records]
    missing_values = sum(
        value.state != "present"
        for record in records
        for value in record.values.values()
    )
    flag_counts = Counter(flag.code for flag in package.quality_flags)
    return QualitySummary(
        total_flags=len(package.quality_flags),
        flags_by_code=dict(sorted(flag_counts.items())),
        excluded_records=sum(record.status.inclusion == "excluded" for record in records),
        invalid_records=sum(record.status.validity == "invalid" for record in records),
        missing_values=missing_values,
        invalidates_report=any(flag.invalidates_report for flag in package.quality_flags),
    )


def build_screening_cues(
    package: ReportDataPackage,
    sketch: AnalysisSketch,
    quality: QualitySummary,
) -> tuple[ScreeningCue, ...]:
    cues: list[ScreeningCue] = []
    if quality.total_flags:
        cues.append(
            ScreeningCue(
                cue_code="quality_flag_present",
                source_refs=tuple(
                    flag.quality_flag_id for flag in package.quality_flags
                ),
            )
        )
    if quality.excluded_records:
        refs = tuple(
            record.record_id
            for record_set in package.record_sets
            for record in record_set.records
            if record.status.inclusion == "excluded"
        )
        cues.append(
            ScreeningCue(cue_code="excluded_records_present", source_refs=refs)
        )
    if quality.missing_values:
        cues.append(
            ScreeningCue(
                cue_code="missing_values_present",
                source_refs=tuple(
                    record_set.record_set_id for record_set in package.record_sets
                ),
            )
        )
    if sketch.temporal_segments:
        cues.append(
            ScreeningCue(
                cue_code="segment_summary_available",
                source_refs=tuple(
                    sorted({item.record_set_id for item in sketch.temporal_segments})
                ),
            )
        )
    if sketch.side_segments:
        cues.append(
            ScreeningCue(
                cue_code="side_summary_available",
                source_refs=tuple(
                    sorted({item.record_set_id for item in sketch.side_segments})
                ),
            )
        )
    return tuple(cues)


def serialize_observation(observation: AgentObservation) -> str:
    return json.dumps(
        observation.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def estimate_observation_tokens(serialized: str) -> int:
    return math.ceil(len(serialized.encode("utf-8")) / 4)
