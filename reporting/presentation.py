"""Evidence-derived claim wording and compact report organization."""

from __future__ import annotations

from .charts import build_evidence_charts
from .metric_catalog import METRIC_CATALOG
from .models import InsightCard, ReportPresentation
from .text import format_numeric_value


_STATISTICS = {"value": "", "count": "数量", "mean": "均值", "min": "最小值", "max": "最大值", "std": "标准差", "cv_percent": "变异系数"}
_SIDES = {"left": "左侧", "right": "右侧", None: ""}
_PREDICATE_PRIORITY = {"co_change": 0, "concentrated_on_side": 1, "persistent": 2, "remains_after_exclusion": 3, "increase": 4, "decrease": 4, "transient": 5, "comparison_supported": 6}
_METRIC_PRIORITY = {
    "Jump Test": ("jump_height_m", "contact_time_s", "air_time_s"),
    "Treadmill Gait Test": ("gait_cycle_s", "stance_phase_percent", "contact_time_s", "step_length_cm"),
    "Treadmill Running Test": ("contact_time_s", "flight_time_s", "step_length_cm"),
    "Sprint and Gait Test": ("step_time_s", "stride_length_m", "step_length_m"),
    "Overground Running Test": ("contact_time_s", "flight_time_s", "step_length_m"),
}


def _change(value, metric):
    tolerance = METRIC_CATALOG[metric].numeric_tolerance
    if abs(value) <= tolerance:
        return "差值在计算容差内"
    return "增加" if value > 0 else "减少"


def _difference(value, unit):
    return format_numeric_value(value, "个百分点" if unit == "%" else unit)


def _evidence_sentence(item, run, predicates):
    metrics = run.parameters.get("metric_codes", ())
    side = _SIDES.get(run.parameters.get("side"), "")
    values = item.numeric_values
    if not metrics:
        return "本次记录未出现使整份报告分析失效的质量标记。"
    metric = metrics[0]
    label = side + METRIC_CATALOG[metric].label
    unit = METRIC_CATALOG[metric].unit
    fmt = lambda value: format_numeric_value(value, unit)
    if item.analysis_method == "compare_session_records":
        parts = []
        for code in metrics:
            definition = METRIC_CATALOG[code]
            before = format_numeric_value(values[f"{code}_previous_mean"], definition.unit)
            after = format_numeric_value(values[f"{code}_current_mean"], definition.unit)
            delta = _difference(values[f"{code}_difference"], definition.unit)
            parts.append(f"{definition.label}有效记录均值，上次 {before}，本次 {after}，本次减上次 {delta}。")
        return f"上次纳入 {item.sample_counts['previous']} 条，本次纳入 {item.sample_counts['current']} 条。" + "".join(parts)
    if item.analysis_method == "summarize_records":
        parts = []
        for code in metrics:
            definition = METRIC_CATALOG[code]
            mean = format_numeric_value(values[f"{code}_mean"], definition.unit)
            minimum = format_numeric_value(values[f"{code}_min"], definition.unit)
            maximum = format_numeric_value(values[f"{code}_max"], definition.unit)
            deviation = format_numeric_value(values[f"{code}_std"], definition.unit)
            parts.append(f"{side}{definition.label}均值 {mean}，范围 {minimum} 至 {maximum}，总体标准差 {deviation}。")
        return f"所选有效样本 {item.sample_counts['selected']} 条。" + "".join(parts)
    if item.analysis_method == "verify_temporal_change":
        text = (f"按有效记录数量分半，{label}{_change(values['difference'], metric)}，"
                f"前半均值 {fmt(values['first_mean'])}，后半均值 {fmt(values['second_mean'])}，"
                f"后减前 {_difference(values['difference'], unit)}。")
        if "persistent" in predicates:
            text += "四段均值的相邻变化方向一致。"
        return text
    if item.analysis_method == "verify_side_segment_difference":
        text = (f"{label}按各侧有效记录数量分半，左侧后减前 {_difference(values['left_change'], unit)}，"
                f"右侧后减前 {_difference(values['right_change'], unit)}。")
        if "concentrated_on_side" in predicates:
            predicate = next(p for p in item.predicates if p.predicate == "concentrated_on_side")
            text += f"变化幅度主要集中在{_SIDES[predicate.details['target_side']]}。"
        return text
    if item.analysis_method == "verify_cross_metric_cochange":
        parts = []
        for code in metrics:
            definition = METRIC_CATALOG[code]
            delta = values[f"{code}_difference"]
            parts.append(f"{side}{definition.label}{_change(delta, code)}，后减前 {_difference(delta, definition.unit)}")
        return "同组有效记录按数量分半，" + "；".join(parts) + "。"
    if item.analysis_method == "verify_exclusion_robustness":
        return (f"{label}在排除前、排除后各自按有效记录数量分半，"
                f"后减前分别为 {_difference(values['all_difference'], unit)}、{_difference(values['included_difference'], unit)}。"
                + ("排除后变化方向仍成立。" if "remains_after_exclusion" in predicates else ""))
    raise ValueError(f"Unsupported presentation method: {item.analysis_method}")


def evidence_claim_text(claim, package, evidence):
    """Render only facts and conclusions whose bindings passed ClaimValidator."""
    items = {i.evidence_id: i for b in evidence for i in b.items}
    runs = {r.tool_run_id: r for b in evidence for r in b.tool_runs}
    parts = []
    for ref in claim.fact_refs:
        fact = package.resolve_ref(ref)
        label = METRIC_CATALOG[fact.metric_code].label + _STATISTICS[fact.statistic]
        count = f"（样本 {fact.sample_count} 条）" if fact.sample_count is not None else ""
        parts.append(f"{label}为 {format_numeric_value(fact.value, fact.unit)}{count}。")
    for ref in claim.evidence_refs:
        item = items[ref]
        bindings = {b.predicate_evidence_ref for b in claim.predicate_bindings}
        predicates = {p.predicate for p in item.predicates if p.predicate_evidence_id in bindings and p.supported}
        # A quality-only or inconclusive item must not turn into a directional claim.
        if item.analysis_status == "conclusive" and predicates:
            parts.append(_evidence_sentence(item, runs[item.tool_run_id], predicates))
    return "".join(dict.fromkeys(parts))


def build_presentation(claims, package, evidence, recommendations, source_packages=None):
    if any(b.package_digest != package.metadata.package_digest or b.package_id != package.metadata.package_id for b in evidence):
        raise ValueError("Presentation evidence belongs to another snapshot")
    items = {i.evidence_id: i for b in evidence for i in b.items}
    runs = {r.tool_run_id: r for b in evidence for r in b.tool_runs}
    metric_order = _METRIC_PRIORITY.get(package.context.test_type, ())

    def title(claim):
        titles = []
        for ref in claim.evidence_refs:
            item = items[ref]
            run = runs[item.tool_run_id]
            side = _SIDES.get(run.parameters.get("side"), "")
            for metric in run.parameters.get("metric_codes", ()):
                label = side + METRIC_CATALOG[metric].label
                if item.analysis_method == "compare_session_records":
                    titles.append(label + "与上次同协议测试的比较")
                elif item.analysis_method == "summarize_records":
                    titles.append(label + "的所选记录统计")
                elif item.analysis_method == "verify_side_segment_difference":
                    titles.append(label + "的左右变化比较")
                elif item.analysis_method == "verify_exclusion_robustness":
                    titles.append(label + "的排除稳健性")
                else:
                    key = "difference" if len(run.parameters["metric_codes"]) == 1 else f"{metric}_difference"
                    if key in item.numeric_values:
                        titles.append(label + _change(item.numeric_values[key], metric))
        for ref in claim.fact_refs:
            fact = package.resolve_ref(ref)
            titles.append(METRIC_CATALOG[fact.metric_code].label + _STATISTICS[fact.statistic])
        return "、".join(dict.fromkeys(titles)) or "本次分析范围"

    def rank(claim):
        referenced = [items[ref] for ref in claim.evidence_refs]
        metrics = {m for item in referenced for p in item.predicates for m in p.metric_codes}
        metrics.update(package.resolve_ref(ref).metric_code for ref in claim.fact_refs)
        priority = min((_PREDICATE_PRIORITY.get(b.predicate, 7) for b in claim.predicate_bindings), default=7)
        metric_priority = min((metric_order.index(m) for m in metrics if m in metric_order), default=len(metric_order))
        coverage = len({ref for item in referenced for ref in item.record_refs})
        return priority, metric_priority, -coverage, claim.claim_id

    selected = []
    card_sources = []
    charts = {}
    for claim in sorted(claims, key=rank):
        refs = {("fact", ref) for ref in claim.fact_refs}
        for ref in claim.evidence_refs:
            item = items[ref]
            groups = tuple((name, members) for name, members in sorted(item.record_groups.items()))
            for metric in runs[item.tool_run_id].parameters.get("metric_codes", ()):
                refs.add((metric, groups or ref))
        if not claim.text or not refs:
            continue
        duplicate = next((i for i, sources in enumerate(card_sources) if refs <= sources), None)
        if duplicate is not None:
            card = selected[duplicate]
            related = (*card.related_claim_ids, claim.claim_id)
            recommendation_ids = tuple(r.recommendation_id for r in recommendations if set(r.claim_refs).intersection((card.claim_id, *related)))
            selected[duplicate] = card.model_copy(update={"related_claim_ids": related, "recommendation_ids": recommendation_ids})
            continue
        only_comparison = claim.predicate_bindings and all(b.predicate == "comparison_supported" for b in claim.predicate_bindings)
        has_summary = any(items[ref].analysis_method in {"summarize_records", "compare_session_records"} for ref in claim.evidence_refs)
        if len(selected) == 3 or (only_comparison and not has_summary):
            continue
        chart_ids = []
        for ref in claim.evidence_refs:
            item = items[ref]
            for chart in build_evidence_charts(package, item, runs[item.tool_run_id], source_packages=source_packages):
                charts[chart.chart_id] = chart
                chart_ids.append(chart.chart_id)
        selected.append(InsightCard(
            claim_id=claim.claim_id, title=title(claim), chart_ids=tuple(dict.fromkeys(chart_ids)),
            recommendation_ids=tuple(r.recommendation_id for r in recommendations if claim.claim_id in r.claim_refs),
        ))
        card_sources.append(refs)
    return ReportPresentation(
        headline_claim_ids=tuple(card.claim_id for card in selected),
        insight_cards=tuple(selected), charts=tuple(charts.values()),
    )
