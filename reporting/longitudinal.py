"""Two-snapshot, record-scoped comparison through the existing evidence contracts."""

import hashlib
import json

from .kernel import AnalysisKernel, KERNEL_VERSION
from .models import (
    AnalysisNode, EvidenceItem, HypothesisTarget, LongitudinalContext,
    NextAnalysisAction, PredicateEvidence, ProvenanceRecord, SessionEvidenceSource,
    ToolRunRecord,
)
from .questions import ReportQuestionError, resolve_question_selection


def build_longitudinal_context(current, previous, plan, selection, protocol_digest, parent=None):
    current_set = next(r for r in current.record_sets if r.record_set_id == selection.record_set_id)
    previous_set = next((r for r in previous.record_sets if r.record_type == current_set.record_type), None)
    if previous_set is None:
        raise ReportQuestionError("invalid_question_selection", "上次同协议测试缺少对应的记录类型。")
    previous_parent = {}
    if parent and parent.question_context and parent.question_context.longitudinal:
        prior = parent.question_context.longitudinal.previous
        if prior.package_digest != previous.metadata.package_digest:
            raise ReportQuestionError("stale_history", "上次测试已更新，请从完整报告重新提问。")
        previous_parent["selection"] = prior.selection.model_dump(mode="json")
    elif plan.scope_basis == "previous":
        report_selection = resolve_question_selection(current, plan.model_copy(update={"scope_basis": "report"}), {})
        if selection.record_refs != report_selection.record_refs:
            raise ReportQuestionError("question_needs_clarification", "请说明要比较两次完整记录，还是各自的前半程、后半程或指定时间段。")
    previous_plan = plan.model_copy(update={"record_set_id": previous_set.record_set_id})
    previous_selection = resolve_question_selection(previous, previous_plan, previous_parent)

    def source(package, selected):
        return SessionEvidenceSource(
            session_id=package.metadata.session_id, package_id=package.metadata.package_id,
            package_digest=package.metadata.package_digest,
            started_at=package.context.started_at, selection=selected,
        )

    return LongitudinalContext(
        current=source(current, selection), previous=source(previous, previous_selection),
        protocol_digest=protocol_digest,
    )


def comparison_action(context):
    selection = context.selection
    return NextAnalysisAction(
        action_id="question_comparison", tool_name="compare_longitudinal",
        analysis_method="compare_session_records",
        inputs={"record_set_id": selection.record_set_id, "metric_codes": list(selection.metric_codes)},
        purpose="比较最近一次同协议测试的对应有效记录",
        hypothesis=HypothesisTarget(
            hypothesis_id="question_comparison", statement=context.question,
            dimensions=("longitudinal",), metric_codes=selection.metric_codes,
            target_predicate="comparison_supported", reason="用户请求个人历史对比",
            success_condition="取得两次测试对应范围的统计和差值",
        ),
    )


def execute_comparison(current, previous, context, node, tool_version):
    if (current.context.subject_id is None or current.context.is_temporary
            or previous.context.is_temporary
            or current.context.subject_id != previous.context.subject_id
            or current.context.team_id != previous.context.team_id
            or current.context.test_type != previous.context.test_type
            or _protocol_config(current) != _protocol_config(previous)
            or (previous.context.started_at, previous.metadata.session_id)
            >= (current.context.started_at, current.metadata.session_id)):
        raise ValueError("Historical comparison session identity or protocol mismatch")
    metrics = tuple(node.inputs["metric_codes"])
    if not metrics or not set(metrics).issubset(context.current.selection.metric_codes):
        raise ValueError("Historical comparison metrics exceed the question selection")
    if node.inputs["record_set_id"] != context.current.selection.record_set_id:
        raise ValueError("Historical comparison record set mismatch")
    if tuple(node.inputs.get("record_refs", ())) != context.current.selection.record_refs:
        raise ValueError("Historical comparison record selection mismatch")
    values, units, counts, groups, limitations = {}, {}, {}, {}, []
    for name, package, source in (("previous", previous, context.previous), ("current", current, context.current)):
        if (package.metadata.session_id != source.session_id
                or package.metadata.package_id != source.package_id
                or package.metadata.package_digest != source.package_digest):
            raise ValueError("Historical comparison snapshot mismatch")
        summary_node = AnalysisNode(
            node_id=node.node_id, question_id=node.question_id, purpose=node.purpose,
            tool_name="analyze_current_session", analysis_method="summarize_records",
            inputs={"record_set_id": source.selection.record_set_id,
                    "metric_codes": list(metrics), "record_refs": list(source.selection.record_refs)},
        )
        summary, _, _ = AnalysisKernel().execute_method(
            package, summary_node, tool_version=tool_version, data_scope="current_session",
        )
        if summary.record_refs != source.selection.record_refs:
            raise ValueError("Historical comparison records are unavailable")
        counts[name] = summary.sample_counts["selected"]
        groups[name] = source.selection.record_refs
        limitations.extend(f"{name}:{value}" for value in summary.limitations)
        for metric in metrics:
            key = f"{metric}_{name}_mean"
            values[key] = summary.numeric_values[f"{metric}_mean"]
            units[key] = summary.numeric_units[f"{metric}_mean"]
    for metric in metrics:
        key = f"{metric}_difference"
        if units[f"{metric}_current_mean"] != units[f"{metric}_previous_mean"]:
            raise ValueError("Historical comparison units mismatch")
        values[key] = values[f"{metric}_current_mean"] - values[f"{metric}_previous_mean"]
        units[key] = units[f"{metric}_current_mean"]
    identity = json.dumps({"context": context.model_dump(mode="json"),
                           "node": node.model_dump(mode="json", exclude={"purpose"}), "tool_version": tool_version,
                           "method_version": "session-record-comparison/1.0",
                           "kernel_version": KERNEL_VERSION}, sort_keys=True)
    digest = hashlib.sha256(identity.encode()).hexdigest()
    evidence_id, run_id, provenance_id = (f"{kind}_{digest}" for kind in ("evidence", "tool_run", "provenance"))
    refs = (*context.previous.selection.record_refs, *context.current.selection.record_refs)
    item = EvidenceItem(
        evidence_id=evidence_id, node_id=node.node_id, question_id=node.question_id,
        tool_name="compare_longitudinal", analysis_method="compare_session_records",
        analysis_status="inconclusive" if limitations else "conclusive",
        record_set_id=context.current.selection.record_set_id,
        predicates=(PredicateEvidence(predicate_evidence_id=f"predicate_{digest}",
            predicate="comparison_supported", supported=not limitations, metric_codes=metrics),),
        numeric_values=values, numeric_units=units, sample_counts=counts,
        record_refs=refs, record_groups=groups, limitations=tuple(dict.fromkeys(limitations)),
        tool_run_id=run_id, provenance_id=provenance_id, longitudinal=context,
    )
    output_digest = hashlib.sha256(item.model_dump_json().encode()).hexdigest()
    run = ToolRunRecord(
        tool_run_id=run_id, tool_name="compare_longitudinal", tool_version=tool_version,
        analysis_method="compare_session_records", analysis_method_version="session-record-comparison/1.0",
        kernel_version=KERNEL_VERSION,
        data_scope="longitudinal", input_refs=refs, output_refs=(evidence_id,),
        parameters=node.inputs, input_digest=digest, output_digest=output_digest,
    )
    provenance = ProvenanceRecord(
        provenance_id=provenance_id, source_type="analysis_kernel",
        source_ref=evidence_id, operation="compare_session_records",
        implementation_version="session-record-comparison/1.0", input_refs=refs,
    )
    return item, run, provenance


def _protocol_config(package):
    return {key: value for key, value in package.context.config_snapshot.items()
            if key not in {"beam_quality", "raw_buffer", "payload_mirror_guard"}}


class LongitudinalAnalysisTool:
    def __init__(self, previous, context):
        self.previous = previous
        self.context = context

    def execute(self, package, node, spec, dependency_evidence):
        if dependency_evidence:
            raise ValueError("Historical comparison uses the two bound snapshots directly")
        return execute_comparison(package, self.previous, self.context, node, spec.version)
