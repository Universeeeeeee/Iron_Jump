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
    ) -> AnalysisPackage:
        claims = []
        evidence_limitations = {
            item.evidence_id: item.limitations
            for bundle in evidence or () for item in bundle.items
        }
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
                    limitations=tuple(dict.fromkeys(
                        limitation for ref in claim.evidence_refs
                        for limitation in evidence_limitations.get(ref, ())
                    )) if question_context else claim.limitations,
                    citation_refs=(),
                )
            )
        recommendations = rag_result.package.recommendations if rag_result else ()
        presentation = (
            build_presentation(claims, package, evidence, recommendations)
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
            overall_limitations=state.limitations if question_context else validated.overall_limitations,
            literature_evidence=rag_result.evidence if rag_result else (),
            recommendations=recommendations,
            references=rag_result.package.citations if rag_result else (),
            references_markdown=(
                rag_result.package.references_markdown if rag_result else ""
            ),
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
