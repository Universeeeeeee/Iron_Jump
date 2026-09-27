"""Single-shot recommendation generation and deterministic validation."""

from __future__ import annotations

import asyncio
import json
import re

from pydantic_ai import Agent

from agent.common.model_provider import build_chat_model, build_http_client, default_model_settings

from .catalog import load_catalog
from .citations import build_citations, render_references_markdown
from .models import (
    AuditValidation,
    DraftRecommendationPackage,
    LiteratureEvidence,
    Recommendation,
    ReportRAGContext,
    ValidatedRecommendationPackage,
)


RECOMMENDATION_PROMPT_VERSION = "sports-recommendation/1.0"
RECOMMENDATION_MODEL_NAME = "deepseek-v4-flash"
RECOMMENDATION_SYSTEM_PROMPT = (
    "你是运动表现报告的循证建议生成器。只能使用输入中的 Claim 和 Evidence。"
    "最多生成三条一般行动建议；不得给出个性化训练剂量、医疗诊断、"
    "治疗、康复或伤病风险判断。每条建议必须引用已有 claim_id 和 evidence_id。"
    "不得输出链接、DOI、Citation 或虚构标识。"
)

_DOMAIN_BY_TEST_TYPE = {
    "Jump Test": "jump",
    "Treadmill Gait Test": "walk",
    "Treadmill Running Test": "run",
}
_SUPPORT_BY_CATEGORY = {
    "measurement_review": {"method", "interpretation", "limitation"},
    "technique_focus": {"training_direction"},
    "general_training_focus": {"training_direction"},
    "retest": {"method", "limitation"},
    "coach_review": {"method", "interpretation", "limitation"},
}
_FORBIDDEN = re.compile(
    r"(?:\b(?:diagnos(?:e|is)|treat(?:ment)?|rehab(?:ilitation)?|injury risk|"
    r"sets?|reps?|kg|percent|%|times per week)\b|"
    r"诊断|治疗|康复|伤病风险|受伤风险|组数|每组|次/周|每周\s*\d|负荷|强度|"
    r"导致|造成|必然)",
    re.IGNORECASE,
)
_DOSAGE_NUMBER = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:组|次|kg|公斤|分钟|秒|%|RM)|"
    r"(?:每周|每天|每日)\s*\d+)",
    re.IGNORECASE,
)
_CITATION_SURFACE = re.compile(
    r"(?:https?://|www\.|\[[^\]]+\]\([^)]*\)|"
    r"\bdoi\s*:|\b10\.\d{4,9}/\S+|"
    r"\[\s*\d+(?:\s*[-,]\s*\d+)*\s*\]|"
    r"\bcitations?\b|参考文献|文献引用)",
    re.IGNORECASE,
)


class DeepSeekRecommendationGenerator:
    model_name = RECOMMENDATION_MODEL_NAME
    prompt_version = RECOMMENDATION_PROMPT_VERSION

    def generate(
        self,
        context: ReportRAGContext,
        evidence: tuple[LiteratureEvidence, ...],
    ) -> DraftRecommendationPackage:
        if not evidence:
            return DraftRecommendationPackage()
        prompt = self._prompt(context, evidence)

        async def flow():
            client = build_http_client()
            try:
                runtime_agent = Agent(
                    model=build_chat_model(client),
                    output_type=DraftRecommendationPackage,
                    instructions=RECOMMENDATION_SYSTEM_PROMPT,
                    retries=0,
                    model_settings=default_model_settings(),
                )
                result = await runtime_agent.run(prompt)
                return result.output
            finally:
                await client.aclose()

        return asyncio.run(flow())

    @staticmethod
    def _prompt(context, evidence) -> str:
        payload = {
            "test_type": context.test_type,
            "claims": [claim.model_dump(mode="json") for claim in context.claims],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "domain": item.domain,
                    "metric_codes": item.metric_codes,
                    "support_types": item.support_types,
                    "locator": item.locator,
                    "excerpt": item.excerpt,
                }
                for item in evidence
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


class RecommendationValidator:
    def __init__(self, sources=None):
        self._sources = tuple(sources or load_catalog())

    def validate(
        self,
        draft: DraftRecommendationPackage,
        context: ReportRAGContext,
        evidence: tuple[LiteratureEvidence, ...],
    ) -> tuple[ValidatedRecommendationPackage, tuple[AuditValidation, ...]]:
        claims = {claim.claim_id: claim for claim in context.claims}
        evidence_by_id = {item.evidence_id: item for item in evidence}
        expected_domain = _DOMAIN_BY_TEST_TYPE.get(context.test_type)
        accepted: list[Recommendation] = []
        validations = []
        seen_recommendation_ids = set()

        for item in draft.recommendations[:3]:
            reason = self._reject_reason(
                item,
                claims,
                evidence_by_id,
                expected_domain,
                context.population,
            )
            if item.recommendation_id in seen_recommendation_ids:
                reason = reason or "duplicate_recommendation_id"
            seen_recommendation_ids.add(item.recommendation_id)
            validations.append(
                AuditValidation(
                    recommendation_id=item.recommendation_id,
                    accepted=reason is None,
                    reason=reason or "",
                )
            )
            if reason is not None:
                continue
            accepted.append(
                Recommendation(
                    recommendation_id=item.recommendation_id,
                    category=item.category,
                    text=item.text.strip(),
                    claim_refs=item.claim_refs,
                    evidence_refs=item.evidence_refs,
                    limitations=item.limitations,
                )
            )

        used_evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for item in accepted
                for evidence_id in item.evidence_refs
            )
        )
        used_evidence = tuple(evidence_by_id[item] for item in used_evidence_ids)
        citations = build_citations(used_evidence, self._sources)
        citation_by_evidence = {
            citation.evidence_id: citation.citation_id for citation in citations
        }
        recommendations = tuple(
            item.model_copy(
                update={
                    "citation_refs": tuple(
                        citation_by_evidence[evidence_id]
                        for evidence_id in item.evidence_refs
                    )
                }
            )
            for item in accepted
        )
        return (
            ValidatedRecommendationPackage(
                recommendations=recommendations,
                citations=citations,
                references_markdown=render_references_markdown(citations),
            ),
            tuple(validations),
        )

    @staticmethod
    def _reject_reason(item, claims, evidence_by_id, expected_domain, population):
        if not item.claim_refs or any(ref not in claims for ref in item.claim_refs):
            return "invalid_claim_reference"
        if not item.evidence_refs or any(
            ref not in evidence_by_id for ref in item.evidence_refs
        ):
            return "invalid_evidence_reference"
        if _FORBIDDEN.search(item.text) or _DOSAGE_NUMBER.search(item.text):
            return "forbidden_recommendation_content"
        if _CITATION_SURFACE.search(item.text):
            return "forbidden_citation_surface"
        allowed_support = _SUPPORT_BY_CATEGORY[item.category]
        claim_metrics = {
            metric
            for ref in item.claim_refs
            for metric in claims[ref].metric_codes
        }
        for ref in item.evidence_refs:
            evidence = evidence_by_id[ref]
            if not evidence.recommendation_allowed:
                return "evidence_not_recommendation_allowed"
            if evidence.domain != expected_domain:
                return "evidence_domain_mismatch"
            if population not in evidence.populations:
                return "evidence_population_mismatch"
            if not allowed_support.intersection(evidence.support_types):
                return "evidence_support_type_mismatch"
            if claim_metrics and not claim_metrics.intersection(evidence.metric_codes):
                return "evidence_metric_mismatch"
        return None
