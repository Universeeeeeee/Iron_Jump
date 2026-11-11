"""Resolve chart values from the exact groups emitted by the analysis kernel."""

from __future__ import annotations

import math

from .metric_catalog import METRIC_CATALOG
from .models import ChartGroup, ChartPoint, EvidenceChart


GROUP_LABELS = {
    "selected": "所选有效记录",
    "first_half": "前半有效记录", "second_half": "后半有效记录",
    "left_first": "左侧前半", "left_second": "左侧后半",
    "right_first": "右侧前半", "right_second": "右侧后半",
    "all_first": "排除前·前半", "all_second": "排除前·后半",
    "included_first": "排除后·前半", "included_second": "排除后·后半",
}


def build_evidence_charts(package, item, run, *, source_packages=None):
    """Build immutable, serializable plot data without asking the model for values."""
    if item.analysis_status != "conclusive" or not item.record_groups:
        return ()
    if item.longitudinal:
        return _longitudinal_charts(package, item, run, source_packages or {})
    record_set = next(r for r in package.record_sets if r.record_set_id == item.record_set_id)
    records = {r.record_id: r for r in record_set.records}
    if set(item.record_refs) != {ref for refs in item.record_groups.values() for ref in refs}:
        raise ValueError("Chart groups do not match evidence records")
    charts = []
    for metric in run.parameters["metric_codes"]:
        groups = []
        for name, refs in item.record_groups.items():
            if len(refs) != len(set(refs)) or len(refs) != item.sample_counts[name]:
                raise ValueError("Chart group count does not match evidence")
            points = []
            for ref in refs:
                record = records[ref]
                value = record.values[metric]
                if value.state != "present" or record.status.validity != "valid":
                    raise ValueError("Chart references an unavailable measurement")
                points.append(ChartPoint(
                    record_ref=ref, ordinal=record.ordinal, source_index=record.source_index,
                    timestamp_s=record.timestamp_s, side=record.side, value=value.value,
                ))
            mean = sum(p.value for p in points) / len(points)
            value_key = {"first_half": "first_mean", "second_half": "second_mean", "selected": "mean"}.get(name)
            if value_key:
                key = f"{metric}_{value_key}" if name == "selected" or len(run.parameters["metric_codes"]) > 1 else value_key
                expected = item.numeric_values[key]
                if not math.isclose(mean, expected, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("Chart mean does not match analysis")
            groups.append(ChartGroup(group_id=name, label=GROUP_LABELS[name], points=tuple(points), mean=mean))
        means = {group.group_id: group.mean for group in groups}
        comparisons = {
            "verify_side_segment_difference": (("left_first", "left_second", "left_change"), ("right_first", "right_second", "right_change")),
            "verify_exclusion_robustness": (("all_first", "all_second", "all_difference"), ("included_first", "included_second", "included_difference")),
        }.get(item.analysis_method, ())
        for first, second, key in comparisons:
            if not math.isclose(means[second] - means[first], item.numeric_values[key], rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Chart difference does not match analysis")
        definition = METRIC_CATALOG[metric]
        charts.append(EvidenceChart(
            chart_id=f"{item.evidence_id}/{metric}", evidence_ref=item.evidence_id,
            package_digest=package.metadata.package_digest, record_set_id=record_set.record_set_id,
            record_type=record_set.record_type, metric_code=metric, title=definition.label,
            unit=definition.unit,
            chart_type="side_distribution" if item.analysis_method == "verify_side_segment_difference" else "time_series",
            grouping="所选有效记录" if item.analysis_method == "summarize_records" else "按各组有效记录数量分半",
            groups=tuple(groups),
        ))
    return tuple(charts)


def _longitudinal_charts(package, item, run, source_packages):
    sources = {**source_packages, package.metadata.session_id: package}
    charts = []
    for metric in run.parameters["metric_codes"]:
        groups = []
        for name, title, source in (("previous", "上次", item.longitudinal.previous),
                                    ("current", "本次", item.longitudinal.current)):
            snapshot = sources[source.session_id]
            if snapshot.metadata.package_digest != source.package_digest:
                raise ValueError("Historical chart snapshot mismatch")
            record_set = next(r for r in snapshot.record_sets if r.record_set_id == source.selection.record_set_id)
            records = {r.record_id: r for r in record_set.records}
            points = tuple(ChartPoint(
                record_ref=ref, ordinal=records[ref].ordinal, source_index=records[ref].source_index,
                timestamp_s=records[ref].timestamp_s, side=records[ref].side,
                value=records[ref].values[metric].value,
                session_id=source.session_id, package_digest=source.package_digest,
            ) for ref in source.selection.record_refs)
            mean = sum(p.value for p in points) / len(points)
            if (item.record_groups[name] != source.selection.record_refs
                    or len(points) != item.sample_counts[name]
                    or not math.isclose(mean, item.numeric_values[f"{metric}_{name}_mean"], rel_tol=1e-12, abs_tol=1e-12)):
                raise ValueError("Historical chart values differ from evidence")
            groups.append(ChartGroup(group_id=name, label=f"{title} {source.started_at}", points=points, mean=mean))
        definition = METRIC_CATALOG[metric]
        charts.append(EvidenceChart(
            chart_id=f"{item.evidence_id}/{metric}", evidence_ref=item.evidence_id,
            package_digest=package.metadata.package_digest,
            record_set_id=item.record_set_id, record_type=record_set.record_type,
            metric_code=metric, title=definition.label, unit=definition.unit,
            chart_type="segment_comparison", grouping="两次测试对应范围的有效记录均值",
            groups=tuple(groups),
        ))
    return tuple(charts)
