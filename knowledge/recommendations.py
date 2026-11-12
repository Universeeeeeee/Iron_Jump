"""Single-shot recommendation generation and deterministic validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Literal

from pydantic import Field
from pydantic_ai import Agent
from reporting.metric_catalog import METRIC_CATALOG

from agent.common.model_provider import build_chat_model, build_http_client, default_model_settings

from .catalog import load_catalog
from .citations import build_citations, render_references_markdown
from .models import (
    AuditValidation,
    DraftRecommendationPackage,
    DraftRecommendation,
    FrozenModel,
    LiteratureEvidence,
    Recommendation,
    ReportRAGContext,
    ValidatedRecommendationPackage,
)


RECOMMENDATION_PROMPT_VERSION = "sports-recommendation/1.1"
RECOMMENDATION_MODEL_NAME = "deepseek-v4-flash"
RECOMMENDATION_SYSTEM_PROMPT = (
    "根据 Iron_Jump 已验证的 Claim 和文献 Evidence，选择最多三项直接相关的后续行动。"
    "每项填写 category、已有 claim_refs 和 evidence_refs。"
    "retest 表示同设备同协议复测，要求所引文献的方法或重复测量依据适用；"
    "coach_review 表示复核该发现对应的记录和分组，要求所引文献支持相关指标的记录或解释；"
    "measurement_review 表示补充记录本次测试条件，要求所引文献提供相关测试方法。"
    "仅有研究目的或训练效果概述的片段不足以支持这些行动。没有适用依据时返回空列表。"
    "当前指标来自权威光电测量结果。论文中的设备品牌、帧率和实验分组属于论文情境。"
    "相同发现与行动只选择一次。系统将按已验证指标和行动类型生成正文及引用。"
)

_ACTION_TEXT = {
    "retest": "围绕{metrics}，按本次相同设备与测试协议复测，并使用相同分组口径比较两次记录。",
    "coach_review": "复核{metrics}对应的逐条记录和分组，结合本次测试背景记录后续关注点。",
    "measurement_review": "将本次{metrics}的测试条件与结果一并记录，供后续同协议比较使用。",
}


class RecommendationAction(FrozenModel):
    category: Literal["retest", "coach_review", "measurement_review"]
    claim_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class RecommendationActions(FrozenModel):
    recommendations: tuple[RecommendationAction, ...] = Field(default=(), max_length=3)


def recommendation_content_digest(prompt):
    content = {"prompt": prompt.strip(), "templates": _ACTION_TEXT,
               "schema": RecommendationActions.model_json_schema()}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def render_recommendation_actions(actions, context):
    claims = {claim.claim_id: claim for claim in context.claims}
    recommendations = []
    seen = set()
    for action in actions.recommendations:
        if any(ref not in claims for ref in action.claim_refs):
            continue
        metrics = tuple(dict.fromkeys(code for ref in action.claim_refs for code in claims[ref].metric_codes))
        if not metrics or any(code not in METRIC_CATALOG for code in metrics):
            continue
        identity = (action.category, tuple(sorted(action.claim_refs)))
        if identity in seen:
            continue
        seen.add(identity)
        recommendations.append(DraftRecommendation(
            recommendation_id=f"rec-{len(recommendations) + 1}", category=action.category,
            text=_ACTION_TEXT[action.category].format(metrics="、".join(METRIC_CATALOG[code].label for code in metrics)),
            claim_refs=action.claim_refs, evidence_refs=action.evidence_refs,
        ))
    return DraftRecommendationPackage(recommendations=tuple(recommendations))

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
_QUALITY_INFERENCE = re.compile(r"测量误差|测量不确定性|系统性(?:偏差|高估|低估)|精度|帧率|\b(?:MDC|SEM|ICC)", re.IGNORECASE)
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
                    output_type=RecommendationActions,
                    instructions=RECOMMENDATION_SYSTEM_PROMPT,
                    retries=0,
                    model_settings=default_model_settings(),
                )
                result = await runtime_agent.run(prompt)
                return render_recommendation_actions(result.output, context)
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
            if re.search(r"\d", item.text):
                reason = reason or "unsupported_numeric_recommendation"
            if not context.quality_codes and _QUALITY_INFERENCE.search(item.text):
                reason = reason or "unobserved_measurement_limitation"
            if any(ref in item.text for ref in (*item.claim_refs, *item.evidence_refs)):
                reason = reason or "internal_reference_in_recommendation"
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
