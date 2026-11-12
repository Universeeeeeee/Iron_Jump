"""Explicit structured evidence and reviewed-support fixtures for boundary tests."""

from knowledge.models import FindingEvidence, RecommendationClaim, ReportRAGContext
from reporting.metric_catalog import METRIC_CATALOG


def verified_context(metric="jump_height_m", test_type="Jump Test"):
    evidence = FindingEvidence(
        evidence_id="data-1", analysis_method="summarize_records", metric_codes=(metric,),
        numeric_values={f"{metric}_mean": .3}, numeric_units={f"{metric}_mean": METRIC_CATALOG[metric].unit},
        sample_counts={"selected": 2}, record_groups={"selected": ("record-1", "record-2")},
        predicates=({"predicate":"comparison_supported", "predicate_evidence_id":"data-predicate-1",
                     "supported":True, "metric_codes":[metric]},),
        analysis_status="conclusive", package_digest="a"*64, tool_run_id="tool-1",
    )
    return ReportRAGContext(
        package_digest="a"*64, test_type=test_type, metric_codes=(metric,),
        claims=(RecommendationClaim(claim_id="claim-1", text="有效记录均值已计算。", metric_codes=(metric,),
            finding_type="conditions_review", evidence=(evidence,), data_origin="validated_report"),),
    )


def reviewed_support(metric, quote, protocol):
    return {"protocol": protocol, "reviewed_action_support": [{
        "review_status":"approved", "action_id":"check_conditions", "metric_codes":[metric],
        "relation":"direct_action_support", "quote":quote, "content_digest":"b"*64,
        "reason":"Synthetic reviewed-support fixture for validator tests; not a production approval.",
    }]}


def action_draft(context, evidence):
    from knowledge.recommendations import RecommendationAction, RecommendationActions, render_recommendation_actions
    return render_recommendation_actions(RecommendationActions(recommendations=(RecommendationAction(
        action_id="check_conditions", claim_id="claim-1", metric_code=context.metric_codes[0],
        evidence_refs=(evidence.evidence_id,),
    ),)), context, (evidence,))
