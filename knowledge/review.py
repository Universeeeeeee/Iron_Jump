"""Separate execution, action applicability and citation checks for human review."""

import json
from collections import Counter
from html import escape

from .models import LiteratureEvidence, ReportRAGContext
from .recommendations import eligible_actions
from .action_matching import (ACTION_SPECS, action_candidates, evidence_action_match, render_action,
                              verified_finding_evidence, UNSUPPORTED_FINDINGS)


# These expectations describe the original scenario meanings, independently of model output.
EXPECTED_ACTIONS = {
    "temporal_change": {"track_change"},
    "side_difference": set(),
    "side_temporal_change": {"track_side_changes"},
    "variability": set(),
    "measurement_limitation": {"explain_limitation"},
    "verified_change": {"track_change"},
    "conditions_review": {"check_conditions"},
}


def replay_review(source_path, output_path, *, before_path=None):
    payload = json.loads(source_path.read_text())
    evaluate_review(payload)
    payload["review_status"] = "pending"
    for row in payload["rows"]:
        row["groundedness_review"] = "pending"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_review_html(payload, output_path.with_suffix(".html"), before_path=before_path)
    return payload


def evaluate_review(payload):
    for row in payload["rows"]:
        context = ReportRAGContext.model_validate(row["context"])
        evidence = tuple(LiteratureEvidence.model_validate(value) for value in row["evidence"])
        evidence_map = {item.evidence_id: item for item in evidence}
        claims = {claim.claim_id: claim for claim in context.claims}
        candidates = eligible_actions(context, evidence)
        row["eligible_actions"] = candidates
        text_only = all(claim.data_origin == "synthetic_text_only" for claim in context.claims)
        row["scenario_candidates"] = [
            {"claim_id": claim.claim_id, "action_id": action_id, "basis": ACTION_SPECS[action_id]["basis"],
             "status": "hypothetical_not_production_eligible"}
            for claim in context.claims for action_id in action_candidates(context, claim)
        ] if text_only else []
        row["unsupported_findings"] = [UNSUPPORTED_FINDINGS[claim.finding_type] for claim in context.claims
                                       if claim.finding_type in UNSUPPORTED_FINDINGS]
        execution = row["audit"]["status"] != "degraded"
        reasons = []
        action_ok, citations_ok, numbers_ok = True, True, True
        for rec in row["recommendations"]:
            claim = claims.get(rec["claim_refs"][0]) if len(rec["claim_refs"]) == 1 else None
            action_id, metric = rec.get("action_id"), rec.get("metric_code")
            if claim is None or action_id not in EXPECTED_ACTIONS.get(claim.finding_type, set()) or metric not in claim.metric_codes:
                action_ok = False
                reasons.append("action_not_suited_to_finding")
                continue
            if rec["text"] != render_action(context, claim, metric, action_id):
                numbers_ok = False
                reasons.append("rendered_text_differs_from_verified_input")
            verified = verified_finding_evidence(context, claim, metric)
            if not verified:
                numbers_ok = False
                reasons.append("missing_verified_production_evidence")
            if rec.get("basis") == "data":
                if (rec.get("evidence_refs") or rec.get("citation_refs")
                        or set(rec.get("data_evidence_refs", ())) != {item.evidence_id for item in verified}):
                    citations_ok = False
                    reasons.append("invalid_data_action_binding")
            elif not rec["evidence_refs"]:
                citations_ok = False
            for ref in rec["evidence_refs"]:
                source = evidence_map.get(ref)
                match = evidence_action_match(context, claim, metric, action_id, source) if source else None
                if match is None or match["excerpt"] not in source.excerpt:
                    citations_ok = False
                    reasons.append("paragraph_action_mismatch")
                if not any(cite["evidence_id"] == ref and source and cite["chunk_id"] == source.chunk_id for cite in row["citations"]):
                    citations_ok = False
                    reasons.append("citation_not_bound_to_candidate")
        if not row["recommendations"]:
            if text_only:
                reasons.append("text_only_scenario_has_no_verified_test_evidence")
                if any(claim.finding_type == "measurement_limitation" and not claim.limitations for claim in context.claims):
                    reasons.append("missing_concrete_limitation")
                quality_status = "scenario_only_not_production_validated"
            elif not candidates:
                reasons.append("missing_concrete_limitation" if any(
                    claim.finding_type == "measurement_limitation" and not claim.limitations for claim in context.claims
                ) else "no_applicable_paragraph_or_protocol")
                quality_status = "supported_abstention"
            else:
                quality_status = "no_action_with_available_candidates"
                action_ok = False
                reasons.append("model_selected_no_usable_action")
        else:
            quality_status = "automated_checks_passed" if action_ok and citations_ok and numbers_ok else "failed"
        row["quality_checks"] = {
            "execution_passed": execution, "action_fit_passed": action_ok if not text_only else None,
            "citation_match_passed": citations_ok if any(rec.get("basis", "literature") == "literature" for rec in row["recommendations"]) else None,
            "data_traceability_passed": numbers_ok if row["recommendations"] and not text_only else None,
            "status": quality_status if execution else "execution_failed", "reasons": reasons,
            "test_value_coverage": "text_only_no_measured_values" if all(
                claim.data_origin == "synthetic_text_only" for claim in context.claims
            ) else "structured_report_values",
            "human_review": "pending",
        }
    rows = payload["rows"]
    from .live_benchmark import benchmark_contexts
    expected = {case_id for case_id, _ in benchmark_contexts()}
    received = [row["case_id"] for row in rows]
    payload["quality_summary"] = {
        "cases": len(rows), "execution_passed": sum(row["quality_checks"]["execution_passed"] for row in rows),
        "complete_30_case_coverage": (set(received) == expected and len(received) == len(expected)) if payload.get("benchmark_version") else None,
        "action_fit_passed": sum(row["quality_checks"]["action_fit_passed"] is True for row in rows),
        "cases_with_recommendations": sum(bool(row["recommendations"]) for row in rows),
        "generated_action_fit_passed": sum(bool(row["recommendations"]) and row["quality_checks"]["action_fit_passed"] is True for row in rows),
        "citation_checks_passed": sum(row["quality_checks"]["citation_match_passed"] is True for row in rows),
        "data_actions": sum(rec.get("basis") == "data" for row in rows for rec in row["recommendations"]),
        "literature_actions": sum(rec.get("basis", "literature") == "literature" for row in rows for rec in row["recommendations"]),
        "scenario_only_cases": sum(row["quality_checks"]["status"] == "scenario_only_not_production_validated" for row in rows),
        "quality_statuses": dict(Counter(row["quality_checks"]["status"] for row in rows)),
        "human_review": "pending",
        "interpretation": "Automatic rule checks are separate from independent human judgment of semantic support.",
    }


def write_review_html(payload, output_path, *, before_path=None):
    before = {}
    if before_path:
        before = {row["case_id"]: row for row in json.loads(before_path.read_text())["rows"]}
    def code(value):
        return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"
    parts = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>文献建议质量审查</title>",
             "<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1140px;margin:32px auto;padding:0 24px;color:#182532;background:#f4f7fa}section{background:white;padding:24px;margin:24px 0;border:1px solid #d4dfeb;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3f8;padding:12px;font-size:13px}blockquote{border-left:3px solid #287c99;margin:12px 0;padding:10px 16px}h1{font-size:28px}h2{font-size:22px}h3{font-size:18px}small{color:#4f6070}table{border-collapse:collapse}td,th{border:1px solid #d4dfeb;padding:8px}</style>",
             "<h1>Report Agent 行动依据审查</h1><p>数据驱动行动核对本次结构化证据；文献驱动行动核对逐段直接行动支持。纯文字场景的数据追溯结果为未评估。人工审核状态均为 pending。</p>",
             code(payload["quality_summary"])]
    if payload.get("data_source"):
        parts.append("<p>数据来源　" + escape(payload["data_source"]) + "</p>")
    parts.append("<table><tr><th>场景</th><th>执行</th><th>行动</th><th>自动质量检查</th><th>未输出原因</th><th>人工审核</th></tr>")
    for row in payload["rows"]:
        checks = row["quality_checks"]
        cells = (row["case_id"], "通过" if checks["execution_passed"] else "失败",
                 ", ".join(rec["action_id"] for rec in row["recommendations"]) or "未输出",
                 checks["status"], ", ".join(checks["reasons"]), row.get("groundedness_review", "pending"))
        parts.append("<tr>" + "".join("<td>" + escape(value) + "</td>" for value in cells) + "</tr>")
    parts.append("</table>")
    for row in payload["rows"]:
        parts.append("<section><h2>" + escape(row["case_id"]) + "</h2><p>" + escape(row["claim"]["text"]) + "</p>")
        parts.append("<h3>结构化发现</h3>" + code({"test_type": row["test_type"],
                     "test_conditions": row["context"].get("test_conditions", {}), **row["claim"]}))
        for reason in row.get("unsupported_findings", []):
            parts.append("<p><b>尚未支持</b>　" + escape(reason) + "</p>")
        if row["claim"].get("data_origin") == "synthetic_text_only":
            parts.append("<p><b>原合成场景仅含发现语义，无实际测试数值、比较方向幅度或样本数。</b></p>")
        if row["case_id"] in before:
            parts.append("<h3>修改前实际结果</h3>")
            parts.extend("<p>" + escape(rec["text"]) + "</p>" for rec in before[row["case_id"]]["recommendations"])
        if row.get("scenario_candidates"):
            parts.append("<h3>场景演练候选（未通过生产事实验证）</h3>" + code(row["scenario_candidates"]))
        parts.append("<h3>本次实际结果</h3>")
        citations = {item["evidence_id"]: item for item in row["citations"]}
        if not row["recommendations"]:
            parts.append("<p>本场景未输出建议。</p>")
        for rec in row["recommendations"]:
            parts.append("<p><b>" + escape(rec["text"]) + "</b></p>" + code({
                key: rec.get(key) for key in ("basis", "action_id", "metric_code", "claim_refs", "data_evidence_refs", "matching_basis")}))
            if rec.get("basis") == "data":
                parts.append("<p>依据为本次结构化测试 Evidence；未附文献引用。</p>")
            for match in rec.get("evidence_matches", []):
                citation = citations[match["evidence_id"]]
                parts.append("<p><a href='" + escape(citation["url"], quote=True) + "'>" + escape(citation["title"]) + "</a> · "
                             + escape(citation["locator"]) + "</p><blockquote>" + escape(match["excerpt"]) + "</blockquote>"
                             + "<p>" + escape(match["reason"]) + "</p>" + code(match))
        parts.append("<h3>自动检查与人工状态</h3>" + code(row["quality_checks"]))
        parts.append("<details><summary>候选行动与证据</summary>" + code(row["eligible_actions"]) + code(row["evidence"]) + "</details></section>")
    output_path.write_text("".join(parts) + "</html>", encoding="utf-8")
