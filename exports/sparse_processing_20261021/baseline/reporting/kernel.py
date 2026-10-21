"""Registered deterministic analysis methods and shared calculation kernel."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

from .metric_catalog import METRIC_CATALOG
from .models import (
    AnalysisNode,
    DataScope,
    EvidenceItem,
    PredicateEvidence,
    ProvenanceRecord,
    RecordSet,
    ReportDataPackage,
    SemanticRecord,
    ToolRunRecord,
)


ANALYSIS_METHOD_REGISTRY_VERSION = "analysis-method-registry/1.0"
KERNEL_VERSION = "analysis-kernel/1.0"
MIN_COMPARISON_GROUP_SIZE = 3
_NAMESPACE = uuid.UUID("9ba0dc8f-5b90-4899-905c-5fc67083e4a7")


@dataclass(frozen=True)
class AnalysisMethodSpec:
    name: str
    version: str
    tool_name: str
    cost: int
    dimensions: tuple[str, ...]
    min_metrics: int
    max_metrics: int
    requires_record_set: bool = True
    requires_side: bool = False
    predicate_names: tuple[str, ...] = ()


class AnalysisMethodRegistry:
    def __init__(self):
        specs = (
            AnalysisMethodSpec("verify_temporal_change", "temporal-change-method/1.0", "analyze_current_session", 2, ("temporal",), 1, 1, predicate_names=("comparison_supported", "increase", "decrease", "persistent", "transient")),
            AnalysisMethodSpec("verify_side_segment_difference", "side-segment-difference-method/1.0", "analyze_current_session", 3, ("temporal", "side"), 1, 1, requires_side=True, predicate_names=("comparison_supported", "concentrated_on_side")),
            AnalysisMethodSpec("verify_cross_metric_cochange", "cross-metric-cochange-method/1.0", "analyze_current_session", 3, ("temporal", "cross_metric"), 2, 2, predicate_names=("comparison_supported", "co_change")),
            AnalysisMethodSpec("verify_exclusion_robustness", "exclusion-robustness-method/1.0", "analyze_current_session", 3, ("temporal", "quality"), 1, 1, predicate_names=("comparison_supported", "remains_after_exclusion")),
            AnalysisMethodSpec("quality_scope_check", "quality-scope-check-method/1.0", "analyze_current_session", 1, ("quality",), 0, 0, requires_record_set=False, predicate_names=("comparison_supported",)),
        )
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> AnalysisMethodSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"Unknown analysis method: {name}") from exc

    def all(self) -> tuple[AnalysisMethodSpec, ...]:
        return tuple(self._specs.values())


class AnalysisKernel:
    def __init__(self, method_registry: AnalysisMethodRegistry | None = None):
        self.method_registry = method_registry or AnalysisMethodRegistry()

    def execute_method(
        self,
        package: ReportDataPackage,
        node: AnalysisNode,
        *,
        tool_version: str,
        data_scope: DataScope,
        dependency_evidence: tuple[EvidenceItem, ...] = (),
    ):
        spec = self.method_registry.get(node.analysis_method)
        dispatch = {
            "verify_temporal_change": self._temporal_change,
            "verify_side_segment_difference": self._side_segment_difference,
            "verify_cross_metric_cochange": self._cross_metric_cochange,
            "verify_exclusion_robustness": self._exclusion_robustness,
            "quality_scope_check": self._quality_scope,
        }
        predicates, values, counts, refs, quality_refs, limitations, record_set_id = dispatch[node.analysis_method](
            package, node
        )
        tool_run_id = self._stable_id(
            package, node, spec, dependency_evidence, "tool_run"
        )
        provenance_id = self._stable_id(
            package, node, spec, dependency_evidence, "provenance"
        )
        evidence_id = self._stable_id(
            package, node, spec, dependency_evidence, "evidence"
        )
        output_payload = {
            # Keep the pre-schema-v3 semantic projection byte-identical. Stable
            # PredicateEvidence IDs are audit references, not deterministic results.
            "predicates": [
                self._predicate_output_payload(predicate)
                for predicate in predicates
            ],
            "values": values,
            "counts": counts,
            "refs": refs,
            "quality_refs": quality_refs,
            "limitations": limitations,
        }
        output_digest = self._digest(output_payload)
        analysis_status = self._analysis_status(node.analysis_method, predicates)
        predicates = tuple(
            predicate.model_copy(
                update={
                    "predicate_evidence_id": self._predicate_id(
                        evidence_id,
                        index,
                        predicate,
                    )
                }
            )
            for index, predicate in enumerate(predicates)
        )
        numeric_units = self._numeric_units(node, values)
        dependency_refs = tuple(item.evidence_id for item in dependency_evidence)
        input_refs = tuple(dict.fromkeys((*dependency_refs, *refs)))
        input_digest = self._digest(
            {
                "tool": node.tool_name,
                "method": node.analysis_method,
                "parameters": node.inputs,
                "input_refs": input_refs,
                "method_version": spec.version,
                "kernel_version": KERNEL_VERSION,
            }
        )
        run = ToolRunRecord(
            tool_run_id=tool_run_id,
            tool_name=node.tool_name,
            tool_version=tool_version,
            analysis_method=node.analysis_method,
            analysis_method_version=spec.version,
            kernel_version=KERNEL_VERSION,
            data_scope=data_scope,
            input_refs=input_refs,
            output_refs=(evidence_id,),
            parameters=node.inputs,
            input_digest=input_digest,
            output_digest=output_digest,
        )
        provenance_record = ProvenanceRecord(
            provenance_id=provenance_id,
            source_type="analysis_kernel",
            source_ref=tool_run_id,
            operation=node.analysis_method,
            implementation_version=KERNEL_VERSION,
            input_refs=input_refs,
        )
        item = EvidenceItem(
            evidence_id=evidence_id,
            node_id=node.node_id,
            question_id=node.question_id,
            tool_name=node.tool_name,
            analysis_method=node.analysis_method,
            analysis_status=analysis_status,
            record_set_id=record_set_id,
            predicates=predicates,
            numeric_values=values,
            numeric_units=numeric_units,
            sample_counts=counts,
            record_refs=tuple(refs),
            quality_flag_refs=tuple(quality_refs),
            limitations=tuple(limitations),
            tool_run_id=tool_run_id,
            provenance_id=provenance_id,
        )
        return item, run, provenance_record

    def _temporal_change(self, package, node):
        record_set = self._record_set(package, node.inputs["record_set_id"])
        metric = node.inputs["metric_codes"][0]
        records = self._selected(record_set, metric, node.inputs.get("side"), included_only=True)
        first, second = self._halves(records)
        supported, limitations = self._comparison_supported(package, metric, first, second)
        first_mean = self._mean(first, metric) if first else None
        second_mean = self._mean(second, metric) if second else None
        tolerance = METRIC_CATALOG[metric].numeric_tolerance
        direction = (
            self._direction(first_mean, second_mean, tolerance)
            if supported and first_mean is not None and second_mean is not None
            else "none"
        )
        quartiles = self._quartiles(records)
        transition_directions = []
        quartile_supported = len(quartiles) == 4 and all(len(group) >= MIN_COMPARISON_GROUP_SIZE for group in quartiles)
        if quartile_supported:
            for left, right in zip(quartiles, quartiles[1:]):
                transition_directions.append(
                    self._direction(self._mean(left, metric), self._mean(right, metric), tolerance)
                )
        persistent = direction in {"increase", "decrease"} and transition_directions.count(direction) == 3
        transient = direction in {"increase", "decrease"} and not persistent and transition_directions.count(direction) in {1, 2}
        predicates = [
            PredicateEvidence(predicate="comparison_supported", supported=supported, metric_codes=(metric,)),
            PredicateEvidence(predicate="increase", supported=direction == "increase", metric_codes=(metric,)),
            PredicateEvidence(predicate="decrease", supported=direction == "decrease", metric_codes=(metric,)),
            PredicateEvidence(predicate="persistent", supported=persistent, metric_codes=(metric,), details={"transition_directions": transition_directions}),
            PredicateEvidence(predicate="transient", supported=transient, metric_codes=(metric,), details={"transition_directions": transition_directions}),
        ]
        values = (
            self._comparison_values(first_mean, second_mean)
            if first_mean is not None and second_mean is not None
            else {}
        )
        counts = {"first_half": len(first), "second_half": len(second)}
        return predicates, values, counts, self._refs(records), self._quality_refs(package, records), limitations, record_set.record_set_id

    def _side_segment_difference(self, package, node):
        record_set = self._record_set(package, node.inputs["record_set_id"])
        metric = node.inputs["metric_codes"][0]
        side_changes: dict[str, float] = {}
        side_counts: dict[str, int] = {}
        limitations: list[str] = []
        selected_records: list[SemanticRecord] = []
        supported = True
        for side in ("left", "right"):
            records = self._selected(record_set, metric, side, included_only=True)
            selected_records.extend(records)
            first, second = self._halves(records)
            group_supported, group_limitations = self._comparison_supported(package, metric, first, second)
            supported = supported and group_supported
            limitations.extend(f"{side}:{item}" for item in group_limitations)
            side_counts[f"{side}_first"] = len(first)
            side_counts[f"{side}_second"] = len(second)
            if group_supported:
                side_changes[side] = self._mean(second, metric) - self._mean(first, metric)
        target_side = node.inputs.get("target_side")
        if target_side not in {"left", "right"} and len(side_changes) == 2:
            target_side = max(side_changes, key=lambda side: abs(side_changes[side]))
        other_side = "right" if target_side == "left" else "left"
        tolerance = METRIC_CATALOG[metric].numeric_tolerance
        concentrated = (
            supported
            and target_side in side_changes
            and other_side in side_changes
            and abs(side_changes[target_side]) > tolerance
            and abs(side_changes[target_side]) >= 2 * abs(side_changes[other_side])
        )
        predicates = [
            PredicateEvidence(predicate="comparison_supported", supported=supported, metric_codes=(metric,)),
            PredicateEvidence(predicate="concentrated_on_side", supported=concentrated, metric_codes=(metric,), details={"target_side": target_side}),
        ]
        values = {f"{side}_change": value for side, value in side_changes.items()}
        return predicates, values, side_counts, self._refs(selected_records), self._quality_refs(package, selected_records), tuple(dict.fromkeys(limitations)), record_set.record_set_id

    def _cross_metric_cochange(self, package, node):
        record_set = self._record_set(package, node.inputs["record_set_id"])
        metric_a, metric_b = node.inputs["metric_codes"]
        side = node.inputs.get("side")
        records = [
            record
            for record in record_set.records
            if record.status.validity == "valid"
            and record.status.inclusion == "included"
            and (side is None or record.side == side)
            and all(record.values[metric].state == "present" for metric in (metric_a, metric_b))
        ]
        first, second = self._halves(records)
        supported_a, limitations_a = self._comparison_supported(package, metric_a, first, second)
        supported_b, limitations_b = self._comparison_supported(package, metric_b, first, second)
        supported = supported_a and supported_b
        directions: dict[str, str] = {}
        values: dict[str, float] = {}
        if supported:
            for metric in (metric_a, metric_b):
                first_mean = self._mean(first, metric)
                second_mean = self._mean(second, metric)
                directions[metric] = self._direction(first_mean, second_mean, METRIC_CATALOG[metric].numeric_tolerance)
                values.update({f"{metric}_first_mean": first_mean, f"{metric}_second_mean": second_mean, f"{metric}_difference": second_mean - first_mean})
        co_change = supported and all(direction in {"increase", "decrease"} for direction in directions.values())
        predicates = [
            PredicateEvidence(predicate="comparison_supported", supported=supported, metric_codes=(metric_a, metric_b)),
            PredicateEvidence(predicate="co_change", supported=co_change, metric_codes=(metric_a, metric_b), details={"directions": directions, "causal_interpretation_allowed": False}),
        ]
        limitations = tuple(dict.fromkeys((*limitations_a, *limitations_b, "co_change_is_not_causation")))
        return predicates, values, {"first_half": len(first), "second_half": len(second)}, self._refs(records), self._quality_refs(package, records), limitations, record_set.record_set_id

    def _exclusion_robustness(self, package, node):
        record_set = self._record_set(package, node.inputs["record_set_id"])
        metric = node.inputs["metric_codes"][0]
        side = node.inputs.get("side")
        all_records = self._selected(record_set, metric, side, included_only=False)
        included = self._selected(record_set, metric, side, included_only=True)
        all_first, all_second = self._halves(all_records)
        included_first, included_second = self._halves(included)
        all_supported, all_limits = self._comparison_supported(package, metric, all_first, all_second)
        included_supported, included_limits = self._comparison_supported(package, metric, included_first, included_second)
        supported = all_supported and included_supported
        tolerance = METRIC_CATALOG[metric].numeric_tolerance
        all_direction = self._direction(self._mean(all_first, metric), self._mean(all_second, metric), tolerance) if all_supported else "none"
        included_direction = self._direction(self._mean(included_first, metric), self._mean(included_second, metric), tolerance) if included_supported else "none"
        remains = supported and all_direction == included_direction and included_direction in {"increase", "decrease"}
        predicates = [
            PredicateEvidence(predicate="comparison_supported", supported=supported, metric_codes=(metric,)),
            PredicateEvidence(predicate="remains_after_exclusion", supported=remains, metric_codes=(metric,), details={"all_direction": all_direction, "included_direction": included_direction}),
        ]
        values: dict[str, float] = {}
        if all_supported:
            values["all_difference"] = self._mean(all_second, metric) - self._mean(all_first, metric)
        if included_supported:
            values["included_difference"] = self._mean(included_second, metric) - self._mean(included_first, metric)
        counts = {"all_first": len(all_first), "all_second": len(all_second), "included_first": len(included_first), "included_second": len(included_second)}
        limitations = tuple(dict.fromkeys((*all_limits, *included_limits)))
        return predicates, values, counts, self._refs(all_records), self._quality_refs(package, all_records), limitations, record_set.record_set_id

    def _quality_scope(self, package, node):
        invalidates = any(flag.invalidates_report for flag in package.quality_flags)
        supported = not invalidates
        predicates = [PredicateEvidence(predicate="comparison_supported", supported=supported, metric_codes=())]
        limitations = ("report_quality_invalidates_analysis",) if invalidates else ()
        return predicates, {}, {"quality_flag_count": len(package.quality_flags)}, [package.metadata.package_id], [flag.quality_flag_id for flag in package.quality_flags], limitations, None

    def _record_set(self, package: ReportDataPackage, record_set_id: str) -> RecordSet:
        for record_set in package.record_sets:
            if record_set.record_set_id == record_set_id:
                return record_set
        raise KeyError(f"Unknown RecordSet: {record_set_id}")

    def _selected(self, record_set, metric, side, *, included_only):
        return [
            record
            for record in record_set.records
            if record.status.validity == "valid"
            and (not included_only or record.status.inclusion == "included")
            and (side is None or record.side == side)
            and metric in record.values
            and record.values[metric].state == "present"
        ]

    def _comparison_supported(self, package, metric, first, second):
        limitations = []
        if len(first) < MIN_COMPARISON_GROUP_SIZE or len(second) < MIN_COMPARISON_GROUP_SIZE:
            limitations.append("insufficient_sample_size")
        if any(flag.invalidates_report or metric in flag.invalidates_metric_codes for flag in package.quality_flags):
            limitations.append("quality_invalidation")
        return not limitations, tuple(limitations)

    def _halves(self, records):
        midpoint = len(records) // 2
        return records[:midpoint], records[midpoint:]

    def _quartiles(self, records):
        groups = [[], [], [], []]
        for position, record in enumerate(records):
            groups[min(3, position * 4 // len(records))].append(record)
        return groups if records else []

    def _mean(self, records, metric):
        return sum(record.values[metric].value for record in records) / len(records)

    def _direction(self, first, second, tolerance):
        difference = second - first
        if difference > tolerance:
            return "increase"
        if difference < -tolerance:
            return "decrease"
        return "none"

    def _comparison_values(self, first, second):
        return {"first_mean": first, "second_mean": second, "difference": second - first}

    def _refs(self, records):
        return list(dict.fromkeys(record.record_id for record in records))

    def _quality_refs(self, package, records):
        record_ids = {record.record_id for record in records}
        return [flag.quality_flag_id for flag in package.quality_flags if flag.source_ref in record_ids or flag.scope == "report"]

    def _numeric_units(self, node: AnalysisNode, values: dict[str, float]):
        metric_codes = tuple(node.inputs.get("metric_codes", ()))
        if not metric_codes:
            return {}
        if len(metric_codes) == 1:
            unit = METRIC_CATALOG[metric_codes[0]].unit
            return {key: unit for key in values}
        units: dict[str, str] = {}
        for key in values:
            for metric_code in metric_codes:
                if key.startswith(f"{metric_code}_"):
                    units[key] = METRIC_CATALOG[metric_code].unit
                    break
        return units

    def _analysis_status(self, analysis_method: str, predicates):
        if analysis_method == "quality_scope_check":
            return "conclusive"
        comparison = next(
            (
                predicate
                for predicate in predicates
                if predicate.predicate == "comparison_supported"
            ),
            None,
        )
        if comparison is None:
            raise RuntimeError(
                f"analysis method {analysis_method} did not return comparison_supported"
            )
        return "conclusive" if comparison.supported else "inconclusive"

    def _predicate_output_payload(self, predicate: PredicateEvidence):
        return {
            "predicate": predicate.predicate,
            "supported": predicate.supported,
            "metric_codes": list(predicate.metric_codes),
            "details": predicate.details,
        }

    def _predicate_id(
        self,
        evidence_id: str,
        index: int,
        predicate: PredicateEvidence,
    ) -> str:
        semantic_digest = self._digest(
            self._predicate_output_payload(predicate)
        )
        return str(
            uuid.uuid5(
                _NAMESPACE,
                f"{evidence_id}:predicate:{index}:{semantic_digest}",
            )
        )

    def _stable_id(
        self,
        package: ReportDataPackage,
        node: AnalysisNode,
        spec: AnalysisMethodSpec,
        dependency_evidence: tuple[EvidenceItem, ...],
        kind: str,
    ) -> str:
        identity = {
            "package_id": package.metadata.package_id,
            "package_digest": package.metadata.package_digest,
            "tool_name": node.tool_name,
            "analysis_method": node.analysis_method,
            "analysis_method_version": spec.version,
            "kernel_version": KERNEL_VERSION,
            "inputs": node.inputs,
            "dependency_evidence_ids": sorted(
                {item.evidence_id for item in dependency_evidence}
            ),
            "id_kind": kind,
        }
        canonical = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return str(uuid.uuid5(_NAMESPACE, canonical))

    def _digest(self, value: Any):
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
