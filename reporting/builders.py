"""Deterministic adapters from immutable TestReport snapshots to evidence models."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import fields
from typing import Iterable

from config.test_report import GaitTestReport, JumpTestReport
from config.treadmill_report import (
    GaitCycleRecord,
    MetricSummary,
    TreadmillGaitReport,
    TreadmillReportBase,
    TreadmillRunningReport,
    TreadmillStepResult,
)

from .metric_catalog import METRIC_CATALOG, metrics_for_record_type
from .models import (
    JumpPayload,
    MetricValue,
    ProvenanceRecord,
    QualityFlag,
    RecordSet,
    RecordSetDescriptor,
    RecordStatus,
    ReportContextInput,
    ReportDataPackage,
    ReportManifest,
    ReportMetadata,
    ScalarFact,
    SemanticRecord,
    SeriesDescriptor,
    TreadmillGaitPayload,
    TreadmillRunningPayload,
)


SCHEMA_VERSION = "1.0"
BUILDER_VERSION = "report-package-builder/1.0"
MANIFEST_VERSION = "report-manifest/1.0"
_NAMESPACE = uuid.UUID("64a13ff4-b445-4b62-b145-df12fd40cc42")


class UnsupportedReportTypeError(TypeError):
    pass


def _stable_id(*parts: object) -> str:
    return str(uuid.uuid5(_NAMESPACE, ":".join(str(part) for part in parts)))


def _canonical_digest(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metric_value(metric_code: str, value: float | int | None) -> MetricValue:
    if value is None:
        return MetricValue(
            metric_code=metric_code,
            state="missing",
            reason="not_recorded",
        )
    return MetricValue(metric_code=metric_code, value=float(value))


def _normalize_side(side: str | None) -> str | None:
    if side is None:
        return None
    return side if side in {"left", "right"} else "unknown"


class ReportDataPackageBuilder:
    def build(
        self,
        report: JumpTestReport | TreadmillGaitReport | TreadmillRunningReport,
        context: ReportContextInput,
    ) -> ReportDataPackage:
        expected_type = getattr(report, "test_type", None)
        if isinstance(report, JumpTestReport):
            expected_type = "Jump Test"
        if isinstance(report, GaitTestReport) or expected_type is None:
            raise UnsupportedReportTypeError(type(report).__name__)
        if context.test_type != expected_type:
            raise ValueError(
                f"context test_type {context.test_type!r} does not match {expected_type!r}"
            )

        package_id = _stable_id("package", context.session_id, expected_type, SCHEMA_VERSION)
        if isinstance(report, JumpTestReport):
            record_sets, facts, quality_flags, payload = self._build_jump(
                package_id, report
            )
        else:
            record_sets, facts, quality_flags, payload = self._build_treadmill(
                package_id, report
            )

        beam_quality = report.report_config_snapshot.get("beam_quality")
        if beam_quality and (beam_quality.get("degraded") or beam_quality.get("events") or
                             beam_quality.get("preflight", {}).get("stability", {}).get("transient_beam_pulses")):
            quality_flags.append(QualityFlag(
                quality_flag_id=_stable_id(package_id, "beam_quality"), code="beam_quality",
                severity="warning", scope="report", source_ref="report_config_snapshot:beam_quality",
                details=beam_quality,
            ))

        used_metric_codes = {
            value.metric_code
            for record_set in record_sets
            for record in record_set.records
            for value in record.values.values()
        } | {fact.metric_code for fact in facts}
        definitions = tuple(
            METRIC_CATALOG[code]
            for code in sorted(used_metric_codes)
            if code in METRIC_CATALOG
        )
        provenance = (
            ProvenanceRecord(
                provenance_id=_stable_id(package_id, "provenance", "snapshot"),
                source_type="report_snapshot",
                source_ref=f"session:{context.session_id}:report_detail_json",
                operation="semantic_structure_conversion",
                implementation_version=BUILDER_VERSION,
            ),
        )
        package = ReportDataPackage(
            metadata=ReportMetadata(
                package_id=package_id,
                schema_version=SCHEMA_VERSION,
                builder_version=BUILDER_VERSION,
                session_id=context.session_id,
                test_type=context.test_type,
                started_at=context.started_at,
                finished_at=context.finished_at,
                subject_id=context.subject_id,
                team_id=context.team_id,
                is_temporary=context.is_temporary,
            ),
            context=context,
            metric_definitions=definitions,
            scalar_facts=tuple(facts),
            record_sets=tuple(record_sets),
            quality_flags=tuple(quality_flags),
            provenance=provenance,
            payload=payload,
        )
        digest = _canonical_digest(package)
        return package.model_copy(
            update={
                "metadata": package.metadata.model_copy(
                    update={"package_digest": digest}
                )
            }
        )

    def _build_jump(self, package_id: str, report: JumpTestReport):
        record_set_id = _stable_id(package_id, "record_set", "jump")
        quality_flags: list[QualityFlag] = []
        records: list[SemanticRecord] = []
        metric_codes = tuple(
            metric.metric_code for metric in metrics_for_record_type("jump")
        )
        for ordinal, row in enumerate(report.jump_results):
            record_id = _stable_id(record_set_id, "record", row.index, ordinal)
            row_flags = self._row_quality_flags(
                package_id, record_id, row.quality_flags
            )
            quality_flags.extend(row_flags)
            records.append(
                SemanticRecord(
                    record_id=record_id,
                    ordinal=ordinal,
                    source_index=row.index,
                    timestamp_s=row.lift_time_s,
                    status=RecordStatus(
                        validity="valid" if row.air_time_s is not None else "invalid",
                        inclusion=(
                            "included" if row.is_included_in_statistics else "excluded"
                        ),
                        exclusion_reason=row.statistics_exclusion_reason,
                    ),
                    quality_flag_ids=tuple(
                        flag.quality_flag_id for flag in row_flags
                    ),
                    values={
                        "air_time_s": _metric_value("air_time_s", row.air_time_s),
                        "jump_height_m": _metric_value(
                            "jump_height_m", row.jump_height_m
                        ),
                        "contact_time_s": _metric_value(
                            "contact_time_s", row.contact_time_s
                        ),
                        "cycle_time_s": _metric_value(
                            "cycle_time_s", row.cycle_time_s
                        ),
                        "cadence_jumps_per_min": _metric_value(
                            "cadence_jumps_per_min", row.cadence_jumps_per_min
                        ),
                    },
                )
            )
        notice_refs: list[str] = []
        for ordinal, notice in enumerate(report.quality_notices):
            flag_id = _stable_id(package_id, "quality_notice", ordinal, notice.kind)
            quality_flags.append(
                QualityFlag(
                    quality_flag_id=flag_id,
                    code=notice.kind,
                    severity="warning",
                    scope="report",
                    source_ref=f"quality_notices:{ordinal}",
                    details={
                        "time_s": notice.time_s,
                        "cluster_length": notice.cluster_length,
                        "ratio": notice.ratio,
                    },
                )
            )
            notice_refs.append(flag_id)

        facts = [
            self._fact(package_id, "touch_count", "count", report.touch_count, "count", 1),
            self._fact(package_id, "lift_count", "count", report.lift_count, "count", 1),
            self._fact(package_id, "jump_count", "count", len(report.jump_results), "count", 1),
        ]
        facts.extend(
            self._jump_summary_facts(package_id, report, len(records))
        )
        record_set = RecordSet(
            record_set_id=record_set_id,
            record_type="jump",
            metric_codes=metric_codes,
            records=tuple(records),
        )
        return (
            [record_set],
            facts,
            quality_flags,
            JumpPayload(
                record_set_ids=(record_set_id,),
                quality_notice_refs=tuple(notice_refs),
            ),
        )

    def _jump_summary_facts(
        self, package_id: str, report: JumpTestReport, sample_count: int
    ) -> list[ScalarFact]:
        mapping = (
            ("jump_height_m", "mean", report.avg_jump_height),
            ("jump_height_m", "min", report.min_jump_height),
            ("jump_height_m", "max", report.max_jump_height),
            ("jump_height_m", "std", report.std_jump_height),
            ("air_time_s", "mean", report.avg_air_time),
            ("air_time_s", "min", report.min_air_time),
            ("air_time_s", "max", report.max_air_time),
            ("air_time_s", "std", report.std_air_time),
            ("contact_time_s", "mean", report.avg_contact_time),
            ("contact_time_s", "min", report.min_contact_time),
            ("contact_time_s", "max", report.max_contact_time),
            ("contact_time_s", "std", report.std_contact_time),
            ("cadence_jumps_per_min", "mean", report.avg_cadence),
        )
        return [
            self._fact(
                package_id,
                metric_code,
                statistic,
                value if sample_count else None,
                METRIC_CATALOG[metric_code].unit,
                sample_count,
            )
            for metric_code, statistic, value in mapping
        ]

    def _build_treadmill(
        self,
        package_id: str,
        report: TreadmillReportBase,
    ):
        quality_flags: list[QualityFlag] = []
        step_set = self._build_treadmill_record_set(
            package_id,
            "step",
            report.per_step_results,
            quality_flags,
        )
        cycle_set = self._build_treadmill_record_set(
            package_id,
            "gait_cycle",
            report.gait_cycles,
            quality_flags,
        )
        facts = [
            self._fact(package_id, "touch_count", "count", report.touch_count, "count", 1),
            self._fact(package_id, "lift_count", "count", report.lift_count, "count", 1),
        ]
        facts.extend(
            self._summary_facts(package_id, report.metric_summaries, "step_summary")
        )
        facts.extend(
            self._summary_facts(
                package_id, report.cycle_metric_summaries, "cycle_summary"
            )
        )
        payload_class = (
            TreadmillGaitPayload
            if isinstance(report, TreadmillGaitReport)
            else TreadmillRunningPayload
        )
        payload = payload_class(
            step_record_set_id=step_set.record_set_id,
            gait_cycle_record_set_id=cycle_set.record_set_id,
        )
        return [step_set, cycle_set], facts, quality_flags, payload

    def _build_treadmill_record_set(
        self,
        package_id: str,
        record_type: str,
        source_rows: Iterable[TreadmillStepResult | GaitCycleRecord],
        quality_flags: list[QualityFlag],
    ) -> RecordSet:
        record_set_id = _stable_id(package_id, "record_set", record_type)
        definitions = metrics_for_record_type(record_type)
        source_field_names = {field.name for field in fields(next(iter(source_rows), None))} if source_rows else set()
        metric_codes = tuple(
            definition.metric_code
            for definition in definitions
            if definition.metric_code in source_field_names
        )
        records: list[SemanticRecord] = []
        for ordinal, row in enumerate(source_rows):
            source_index = getattr(row, "index", ordinal)
            record_id = _stable_id(record_set_id, "record", source_index, ordinal)
            row_flags = self._row_quality_flags(
                package_id, record_id, getattr(row, "quality_flags", ())
            )
            quality_flags.extend(row_flags)
            is_valid = getattr(row, "is_event_valid", True)
            included = getattr(row, "is_included_in_statistics", True)
            timestamp_s = getattr(row, "time_s", None)
            if timestamp_s is None:
                timestamp_s = getattr(row, "start_time_s", None)
            records.append(
                SemanticRecord(
                    record_id=record_id,
                    ordinal=ordinal,
                    source_index=source_index,
                    timestamp_s=timestamp_s,
                    side=_normalize_side(getattr(row, "side", None)),
                    status=RecordStatus(
                        validity="valid" if is_valid else "invalid",
                        inclusion="included" if included else "excluded",
                        event_status=getattr(row, "row_status", None),
                        exclusion_reason=(
                            getattr(row, "statistics_exclusion_reason", None)
                            or getattr(row, "event_invalid_reason", None)
                        ),
                    ),
                    quality_flag_ids=tuple(
                        flag.quality_flag_id for flag in row_flags
                    ),
                    values={
                        code: _metric_value(code, getattr(row, code, None))
                        for code in metric_codes
                    },
                )
            )
        return RecordSet(
            record_set_id=record_set_id,
            record_type=record_type,
            metric_codes=metric_codes,
            records=tuple(records),
        )

    def _summary_facts(
        self,
        package_id: str,
        summaries: dict[str, MetricSummary],
        source_name: str,
    ) -> list[ScalarFact]:
        facts: list[ScalarFact] = []
        for metric_code, summary in sorted(summaries.items()):
            definition = METRIC_CATALOG.get(metric_code)
            if definition is None:
                raise ValueError(f"Missing MetricDefinition for {metric_code}")
            for statistic in ("mean", "min", "max", "std", "cv_percent"):
                unit = "%" if statistic == "cv_percent" else definition.unit
                facts.append(
                    self._fact(
                        package_id,
                        metric_code,
                        statistic,
                        getattr(summary, statistic),
                        unit,
                        summary.count,
                        source_name=source_name,
                    )
                )
        return facts

    def _fact(
        self,
        package_id: str,
        metric_code: str,
        statistic: str,
        value: float | int | None,
        unit: str,
        sample_count: int,
        *,
        source_name: str = "report",
    ) -> ScalarFact:
        fact_id = _stable_id(package_id, "fact", source_name, metric_code, statistic)
        if value is None:
            return ScalarFact(
                fact_id=fact_id,
                metric_code=metric_code,
                statistic=statistic,
                unit=unit,
                sample_count=sample_count,
                state="missing",
                missing_reason="no_valid_observations",
                source_ref=f"{source_name}:{metric_code}:{statistic}",
            )
        return ScalarFact(
            fact_id=fact_id,
            metric_code=metric_code,
            statistic=statistic,
            value=float(value),
            unit=unit,
            sample_count=sample_count,
            source_ref=f"{source_name}:{metric_code}:{statistic}",
        )

    def _row_quality_flags(
        self,
        package_id: str,
        record_id: str,
        codes: Iterable[str],
    ) -> list[QualityFlag]:
        return [
            QualityFlag(
                quality_flag_id=_stable_id(package_id, "quality", record_id, code),
                code=code,
                severity="warning",
                scope="record",
                source_ref=record_id,
            )
            for code in codes
        ]


class ReportManifestBuilder:
    def build(self, package: ReportDataPackage) -> ReportManifest:
        descriptors: list[RecordSetDescriptor] = []
        series: list[SeriesDescriptor] = []
        dimensions = {"overall", "quality"}
        for record_set in package.record_sets:
            has_side = any(record.side in {"left", "right"} for record in record_set.records)
            has_sequence = len(record_set.records) > 1
            if has_side:
                dimensions.add("side")
            if has_sequence:
                dimensions.add("temporal")
            if len(record_set.metric_codes) > 1:
                dimensions.add("cross_metric")
            descriptors.append(
                RecordSetDescriptor(
                    record_set_id=record_set.record_set_id,
                    record_type=record_set.record_type,
                    record_count=len(record_set.records),
                    metric_codes=record_set.metric_codes,
                    has_sequence=has_sequence,
                    has_side=has_side,
                )
            )
            for metric_code in record_set.metric_codes:
                value_count = sum(
                    record.values[metric_code].state == "present"
                    for record in record_set.records
                    if metric_code in record.values
                )
                series.append(
                    SeriesDescriptor(
                        series_id=_stable_id(
                            package.metadata.package_id,
                            "series",
                            record_set.record_set_id,
                            metric_code,
                        ),
                        record_set_id=record_set.record_set_id,
                        metric_code=metric_code,
                        value_count=value_count,
                    )
                )
        return ReportManifest(
            package_id=package.metadata.package_id,
            package_digest=package.metadata.package_digest,
            test_type=package.metadata.test_type,
            record_sets=tuple(descriptors),
            series=tuple(series),
            fact_refs=tuple(fact.fact_id for fact in package.scalar_facts),
            quality_flag_refs=tuple(
                flag.quality_flag_id for flag in package.quality_flags
            ),
            available_dimensions=tuple(sorted(dimensions)),
            manifest_version=MANIFEST_VERSION,
        )
