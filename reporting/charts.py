"""Resolve chart values from the exact groups emitted by the analysis kernel."""

from __future__ import annotations

import math

from .metric_catalog import METRIC_CATALOG
from .models import ChartGroup, ChartPoint, EvidenceChart


GROUP_LABELS = {
    "first_half": "前半有效记录", "second_half": "后半有效记录",
    "left_first": "左侧前半", "left_second": "左侧后半",
    "right_first": "右侧前半", "right_second": "右侧后半",
    "all_first": "排除前·前半", "all_second": "排除前·后半",
    "included_first": "排除后·前半", "included_second": "排除后·后半",
}


def build_evidence_charts(package, item, run):
    """Build immutable, serializable plot data without asking the model for values."""
    if item.analysis_status != "conclusive" or not item.record_groups:
        return ()
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
            value_key = {"first_half": "first_mean", "second_half": "second_mean"}.get(name)
            if value_key:
                key = f"{metric}_{value_key}" if len(run.parameters["metric_codes"]) > 1 else value_key
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
            grouping="按各组有效记录数量分半", groups=tuple(groups),
        ))
    return tuple(charts)
