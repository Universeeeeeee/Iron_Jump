"""Resolve a report question to exact, snapshot-bound measurement records."""

from __future__ import annotations

import hashlib
import json

from .models import (
    HypothesisTarget,
    NextAnalysisAction,
    ReportQuestionContext,
    ReportSelection,
)


class ReportQuestionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parent_question_context(parent, claim_id):
    context = {"selected_claim_text": "", "selection": None, "prior_turns": []}
    if parent is None:
        return context
    prior = parent.question_context
    if prior is not None:
        context["selection"] = prior.selection.model_dump(mode="json")
        context["prior_turns"] = [
            *prior.prior_turns,
            {"question": prior.question, "answer": parent.summary},
        ][-4:]
    if claim_id is None:
        return context
    claim = next((c for c in parent.claims if c.claim_id == claim_id), None)
    if claim is None:
        raise ReportQuestionError("unknown_claim", "所选发现已无法定位，请重新选择。")
    context["selected_claim_text"] = claim.text
    evidence = {item.evidence_id: item for bundle in parent.evidence for item in bundle.items}
    if not claim.evidence_refs or any(ref not in evidence for ref in claim.evidence_refs):
        raise ReportQuestionError("legacy_evidence_unavailable", "这条已保存发现缺少逐条证据，请选择整体报告提问或重新分析。")
    items = [evidence[ref] for ref in claim.evidence_refs]
    record_sets = {item.record_set_id for item in items}
    if len(record_sets) != 1 or None in record_sets:
        raise ReportQuestionError("ambiguous_selection", "这项发现涉及多个数据范围，请选择整体报告并指定指标。")
    metrics = tuple(dict.fromkeys(metric for item in items for p in item.predicates for metric in p.metric_codes))
    context["selection"] = ReportSelection(
        record_set_id=items[0].record_set_id,
        metric_codes=metrics,
        record_refs=tuple(dict.fromkeys(ref for item in items for ref in item.record_refs)),
        label=prior.selection_label if prior else "所选发现记录",
    ).model_dump(mode="json")
    return context


def resolve_question_selection(package, plan, parent_context):
    if plan.intent == "clarify":
        raise ReportQuestionError("question_needs_clarification", plan.clarification or "请补充要分析的指标和范围。")
    previous = parent_context.get("selection")
    if plan.intent == "chart" and previous:
        plan = plan.model_copy(update={
            "record_set_id": previous["record_set_id"],
            "metric_codes": tuple(previous["metric_codes"]),
            "scope_basis": "previous", "segment": "all", "side": "all",
            "start_record": None, "end_record": None,
            "start_time_s": None, "end_time_s": None,
        })
    record_set = next((r for r in package.record_sets if r.record_set_id == plan.record_set_id), None)
    if record_set is None or not set(plan.metric_codes).issubset(record_set.metric_codes):
        raise ReportQuestionError("invalid_question_selection", "问题对应的记录或指标无法匹配当前报告。")
    inherited = parent_context.get("selection") if plan.scope_basis == "previous" else None
    if inherited and inherited["record_set_id"] != record_set.record_set_id:
        raise ReportQuestionError("invalid_question_selection", "当前选择属于另一类记录，请重新指定范围。")
    records = [
        record for record in record_set.records
        if record.status.validity == "valid" and record.status.inclusion == "included"
        and all(
            metric in record.values and record.values[metric].state == "present"
            for metric in plan.metric_codes
        )
    ]
    labels = []
    if inherited:
        refs = set(inherited["record_refs"])
        records = [record for record in records if record.record_id in refs]
        labels.append(inherited["label"])
    if plan.start_record is not None or plan.end_record is not None:
        start = plan.start_record or 1
        end = plan.end_record or len(record_set.records)
        if start > len(record_set.records) or end > len(record_set.records):
            raise ReportQuestionError("invalid_question_selection", "所选记录序号超出本次报告范围。")
        records = [record for record in records if start <= record.ordinal + 1 <= end]
        labels.append(f"第 {start}–{end} 条记录")
    if plan.start_time_s is not None or plan.end_time_s is not None:
        records = [
            record for record in records if record.timestamp_s is not None
            and (plan.start_time_s is None or record.timestamp_s >= plan.start_time_s)
            and (plan.end_time_s is None or record.timestamp_s <= plan.end_time_s)
        ]
        start = f"{plan.start_time_s:g} 秒" if plan.start_time_s is not None else "起点"
        end = f"{plan.end_time_s:g} 秒" if plan.end_time_s is not None else "终点"
        labels.append(f"{start}至{end}")
    if plan.segment != "all":
        midpoint = len(records) // 2
        records = records[:midpoint] if plan.segment == "first_half" else records[midpoint:]
        labels.append("前半有效记录" if plan.segment == "first_half" else "后半有效记录")
    if plan.side != "all":
        records = [record for record in records if record.side == plan.side]
        labels.append("左侧" if plan.side == "left" else "右侧")
    if not records:
        raise ReportQuestionError("empty_selection", "所选范围没有该指标的有效记录。")
    label = " · ".join(dict.fromkeys(labels)) or "完整有效记录"
    return ReportSelection(
        record_set_id=record_set.record_set_id, metric_codes=plan.metric_codes,
        record_refs=tuple(record.record_id for record in records), label=label,
    )


def question_context(request, selection, plan, parent_context):
    return ReportQuestionContext(
        question=request.question, intent=plan.intent,
        parent_analysis_run_id=request.parent_analysis_run_id,
        selected_claim_id=request.selected_claim_id,
        selected_claim_text=parent_context["selected_claim_text"],
        selection=selection, selection_label=selection.label, chart_type=plan.chart_type,
        prior_turns=tuple(parent_context["prior_turns"]),
    )


def chart_source_action(parent, context):
    """Recompute a selected chart with its original method and grouping."""
    if parent is None or context.intent != "chart":
        return None
    selection = context.selection
    claims = [
        claim for claim in parent.claims
        if context.selected_claim_id is None or claim.claim_id == context.selected_claim_id
    ]
    referenced = {ref for claim in claims for ref in claim.evidence_refs}
    bindings = {
        binding.predicate_evidence_ref
        for claim in claims for binding in claim.predicate_bindings
        if hasattr(binding, "predicate_evidence_ref")
    }
    candidates = []
    for bundle in parent.evidence:
        runs = {run.tool_run_id: run for run in bundle.tool_runs}
        for item in bundle.items:
            run = runs.get(item.tool_run_id)
            if (
                item.evidence_id not in referenced
                or not item.record_groups
                or item.record_set_id != selection.record_set_id
                or set(item.record_refs) != set(selection.record_refs)
                or run is None
                or set(run.parameters.get("metric_codes", ())) != set(selection.metric_codes)
                or item.analysis_method in {"verify_exclusion_robustness", "quality_scope_check"}
            ):
                continue
            predicate = next((
                predicate for predicate in item.predicates
                if predicate.supported and predicate.predicate_evidence_id in bindings
            ), None)
            if predicate is not None:
                candidates.append((item, run, predicate))
    if len(candidates) > 1:
        raise ReportQuestionError("ambiguous_selection", "当前范围有多项证据图，请选择要更换图形的发现。")
    if not candidates:
        return None
    item, run, predicate = candidates[0]
    return NextAnalysisAction(
        action_id="question_chart",
        tool_name=item.tool_name,
        analysis_method=item.analysis_method,
        inputs=dict(run.parameters, record_refs=list(selection.record_refs)),
        purpose="保留原证据分组并更换图形",
        hypothesis=HypothesisTarget(
            hypothesis_id="question_chart", statement=context.question,
            dimensions=("descriptive",), metric_codes=selection.metric_codes,
            target_predicate=predicate.predicate,
            reason="用户请求更换已有证据图形", success_condition="复现原始记录分组",
        ),
    )


def question_digest(context):
    serialized = json.dumps(
        context.model_dump(mode="json"), ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
