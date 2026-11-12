"""Deterministic injection of validated numeric evidence into final claims."""

from __future__ import annotations

from .models import (
    AnalysisClaim,
    AnalysisPackage,
    AnalysisState,
    DataAccessScope,
    ReportDataPackage,
    ValidatedAnalysisPackage,
)
from .text import format_numeric_value, render_validated_claim_text
from .presentation import build_presentation, evidence_claim_text
from knowledge.citations import render_references_markdown


def _select_recommendations(candidates, claims, package, evidence):
    """Arbitrate once across data and literature actions, with one action per finding/metric."""
    items = {item.evidence_id: item for bundle in evidence or () for item in bundle.items}
    claim_metrics = {}
    for claim in claims:
        metrics = {package.resolve_ref(ref).metric_code for ref in claim.fact_refs}
        for ref in claim.evidence_refs:
            item = items.get(ref)
            if item is not None:
                metrics.update(metric for predicate in item.predicates for metric in predicate.metric_codes)
        claim_metrics[claim.claim_id] = metrics

    def priority(item):
        if item.action_id == "explain_limitation" and item.basis == "data" and item.data_evidence_refs:
            return 0
        if item.basis == "literature" and item.citation_refs and item.evidence_matches and all(
            match.get("applicability") == "reviewed_direct_action_support" for match in item.evidence_matches
        ):
            return 1
        return 2 if item.basis == "data" else 3

    selected, reserved, ids = [], set(), set()
    for item in sorted(candidates, key=priority):
        if not item.claim_refs or any(ref not in claim_metrics for ref in item.claim_refs):
            continue
        if item.metric_code and any(item.metric_code not in claim_metrics[ref] for ref in item.claim_refs):
            continue
        keys = {(ref, metric) for ref in item.claim_refs
                for metric in ((item.metric_code,) if item.metric_code else claim_metrics[ref])}
        if not keys or keys.intersection(reserved) or item.recommendation_id in ids:
            continue
        selected.append(item)
        reserved.update(keys)
        ids.add(item.recommendation_id)
        if len(selected) == 3:
            break
    return tuple(selected)


class AnalysisRenderer:
    def render(
        self,
        validated: ValidatedAnalysisPackage,
        *,
        analysis_run_id: str,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        state: AnalysisState,
        model_name: str,
        prompt_version: str,
        prompt_content_digest: str | None = None,
        rag_result=None,
        evidence=None,
        request_digest="",
        question_context=None,
        source_packages=None,
        data_followups=(),
    ) -> AnalysisPackage:
        claims = []
        for claim in validated.claims:
            text = (
                evidence_claim_text(claim, package, evidence)
                if evidence is not None else render_validated_claim_text(claim)
            )
            claims.append(
                AnalysisClaim(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    text=text,
                    fact_refs=claim.fact_refs,
                    evidence_refs=claim.evidence_refs,
                    tool_run_ids=claim.tool_run_ids,
                    predicate_bindings=claim.predicate_bindings,
                    limitations=claim.limitations,
                    citation_refs=(),
                )
            )
        recommendations = _select_recommendations(
            (*data_followups, *(rag_result.package.recommendations if rag_result else ())),
            claims, package, evidence,
        )
        citation_ids = {ref for item in recommendations for ref in item.citation_refs}
        references = tuple(citation for citation in (rag_result.package.citations if rag_result else ())
                           if citation.citation_id in citation_ids)
        presentation = (
            build_presentation(claims, package, evidence, recommendations, source_packages=source_packages)
            if evidence is not None else None
        )
        if presentation and question_context:
            charts = tuple(chart.model_copy(update={
                "chart_type": question_context.chart_type or chart.chart_type,
                "grouping": question_context.selection_label + " · " + chart.grouping,
            }) for chart in presentation.charts)
            presentation = presentation.model_copy(update={"charts": charts})
        summary = "；".join(card.title for card in presentation.insight_cards) + "。" if presentation and presentation.insight_cards else ""
        return AnalysisPackage(
            analysis_schema_version="analysis-schema/5.0" if presentation else "analysis-schema/4.0",
            analysis_run_id=analysis_run_id,
            session_id=package.metadata.session_id,
            package_id=package.metadata.package_id,
            package_digest=package.metadata.package_digest,
            data_access_scope=access_scope,
            summary=summary or validated.summary,
            claims=tuple(claims),
            evidence=tuple(evidence or ()),
            presentation=presentation,
            request_digest=request_digest,
            question_context=question_context,
            scope_expansion_suggestions=validated.scope_expansion_suggestions,
            overall_limitations=tuple(dict.fromkeys((
                *validated.overall_limitations, *state.limitations,
            ))),
            literature_evidence=rag_result.evidence if rag_result else (),
            recommendations=recommendations,
            references=references,
            references_markdown=render_references_markdown(references),
            rag_audit=rag_result.audit if rag_result else None,
            cycle_count=getattr(
                state, "cycle_count", getattr(state, "tool_call_count", 0)
            ),
            replan_count=getattr(state, "replan_count", 0),
            model_name=model_name,
            prompt_version=prompt_version,
            prompt_content_digest=prompt_content_digest,
        )

    def _format_value(self, value: float, unit: str) -> str:
        return format_numeric_value(value, unit)
