"""Adapters between validated report analysis and the independent RAG subsystem."""

from __future__ import annotations

from reporting.presentation import evidence_claim_text

from .models import RecommendationClaim, ReportRAGContext


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
        for fact_ref in claim.fact_refs:
            fact = package.resolve_ref(fact_ref)
            metric_code = getattr(fact, "metric_code", None)
            if metric_code:
                metric_codes.add(metric_code)
        for evidence_ref in claim.evidence_refs:
            item = evidence_items.get(evidence_ref)
            if item is None:
                continue
            for predicate in item.predicates:
                if predicate.supported:
                    metric_codes.update(predicate.metric_codes)
        all_metrics.update(metric_codes)
        claims.append(
            RecommendationClaim(
                claim_id=claim.claim_id,
                text=evidence_claim_text(claim, package, evidence_bundles),
                metric_codes=tuple(sorted(metric_codes)),
                limitations=claim.limitations,
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
    )
