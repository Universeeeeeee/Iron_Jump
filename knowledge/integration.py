"""Adapters between validated report analysis and the independent RAG subsystem."""

from __future__ import annotations

from reporting.presentation import evidence_claim_text
from reporting.metric_catalog import METRIC_CATALOG

from .models import FindingEvidence, RecommendationClaim, ReportRAGContext


def build_report_rag_context(package, validated, evidence_bundles) -> ReportRAGContext:
    evidence_items = {
        item.evidence_id: item
        for bundle in evidence_bundles
        for item in bundle.items
    }
    claims = []
    all_metrics = set()
    for claim in validated.claims:
        metric_codes = set()
        facts = []
        for fact_ref in claim.fact_refs:
            fact = package.resolve_ref(fact_ref)
            metric_code = getattr(fact, "metric_code", None)
            if metric_code:
                metric_codes.add(metric_code)
                facts.append(fact.model_dump(mode="json"))
        linked_evidence = []
        for evidence_ref in claim.evidence_refs:
            item = evidence_items.get(evidence_ref)
            if item is None:
                continue
            for predicate in item.predicates:
                if predicate.supported:
                    metric_codes.update(predicate.metric_codes)
            bound = {binding.predicate_evidence_ref for binding in claim.predicate_bindings}
            linked_evidence.append(FindingEvidence(
                evidence_id=item.evidence_id, analysis_method=item.analysis_method,
                metric_codes=tuple(dict.fromkeys(code for p in item.predicates for code in p.metric_codes)),
                numeric_values=item.numeric_values, numeric_units=item.numeric_units,
                sample_counts=item.sample_counts, record_groups=item.record_groups,
                predicates=tuple(p.model_dump(mode="json") for p in item.predicates
                                 if p.supported and p.predicate_evidence_id in bound),
                limitations=item.limitations,
                analysis_status=item.analysis_status, package_digest=package.metadata.package_digest,
                tool_run_id=item.tool_run_id,
            ))
        methods = {item.analysis_method for item in linked_evidence}
        supported = {p["predicate"] for item in linked_evidence for p in item.predicates}
        if "concentrated_on_side" in supported:
            finding_type = "side_temporal_change"
        elif (methods.intersection({"verify_temporal_change", "verify_cross_metric_cochange", "verify_exclusion_robustness"})
              and supported.intersection({"increase", "decrease", "persistent", "transient", "co_change", "remains_after_exclusion"})):
            finding_type = "temporal_change"
        elif "compare_session_records" in methods and any(
            abs(item.numeric_values.get(f"{metric}_difference", 0)) > METRIC_CATALOG[metric].numeric_tolerance
            for item in linked_evidence for metric in item.metric_codes
        ):
            finding_type = "verified_change"
        elif claim.limitations and any(code != "co_change_is_not_causation" for code in claim.limitations):
            finding_type = "measurement_limitation"
        else:
            finding_type = "descriptive"
        all_metrics.update(metric_codes)
        claims.append(
            RecommendationClaim(
                claim_id=claim.claim_id,
                text=evidence_claim_text(claim, package, evidence_bundles),
                metric_codes=tuple(sorted(metric_codes)),
                limitations=claim.limitations,
                finding_type=finding_type, evidence=tuple(linked_evidence), fact_values=tuple(facts),
                data_origin="validated_report",
            )
        )
    quality_codes = tuple(
        sorted(
            flag.code
            for flag in package.quality_flags
            if flag.severity in {"warning", "error"}
        )
    )
    return ReportRAGContext(
        package_digest=package.metadata.package_digest,
        test_type=package.context.test_type,
        metric_codes=tuple(sorted(all_metrics)),
        claims=tuple(claims),
        quality_codes=quality_codes,
        population="general",
        test_conditions=package.context.config_snapshot,
    )
