"""Single-shot recommendation generation and deterministic validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re

from pydantic import Field
from pydantic_ai import Agent

from agent.common.model_provider import build_chat_model, build_http_client, default_model_settings

from .catalog import load_catalog
from .action_matching import (ACTION_SPECS, MATCHING_VERSION, PROTOCOLS, METRIC_TERMS,
                              action_candidates, evidence_action_match, render_action, literature_metrics, verified_finding_evidence)
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


RECOMMENDATION_PROMPT_VERSION = "sports-recommendation/2.0"
RECOMMENDATION_MODEL_NAME = "deepseek-v4-flash"
RECOMMENDATION_SYSTEM_PROMPT = (
    "从 eligible_actions 中选择对当前发现最有价值的行动。每个发现每个指标最多一项，总计最多三项。"
    "填写 action_id、claim_id、metric_code 和真实候选 evidence_refs。只可选择提供的行动和匹配证据。"
    "优先 priority 较小的行动；如果不能增加信息或依据不足则不选择，返回空列表。"
    "test_type、finding_type、分组和数值由上游验证提供。synthetic_text_only 场景没有实测数值。"
    "每项文献行动必须已有逐段审核的 direct_action_support。指标相关或跨设备测量一致性不能作为行动支持。"
    "本次个体发现是否成立由结构化测试证据校验；数据驱动的后续观察由系统独立生成。"
    "不得将其他设备误差、群体差异、论文阈值作为本次被试的结论或校正系数。"
    "系统将从已验证数据生成正文、匹配理由和引用。"
)


class RecommendationAction(FrozenModel):
    action_id: str
    claim_id: str
    metric_code: str
    evidence_refs: tuple[str, ...] = ()
    data_evidence_refs: tuple[str, ...] = ()


class RecommendationActions(FrozenModel):
    recommendations: tuple[RecommendationAction, ...] = Field(default=(), max_length=3)


def recommendation_content_digest(prompt):
    content = {"prompt": prompt.strip(), "actions": ACTION_SPECS, "matching_version": MATCHING_VERSION,
               "protocols": PROTOCOLS, "metric_terms": METRIC_TERMS,
               "schema": RecommendationActions.model_json_schema()}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def eligible_actions(context, evidence):
    candidates = []
    for claim in context.claims:
        for metric in claim.metric_codes:
            verified = verified_finding_evidence(context, claim, metric)
            if not verified:
                continue
            for action_id in action_candidates(context, claim):
                spec = ACTION_SPECS[action_id]
                matches = [match for item in evidence
                           if (match := evidence_action_match(context, claim, metric, action_id, item))]
                if spec["basis"] == "data" or matches:
                    candidates.append({"action_id": action_id, "claim_id": claim.claim_id,
                        "metric_code": metric, "priority": spec["priority"], "basis": spec["basis"],
                        "data_evidence_refs": tuple(item.evidence_id for item in verified),
                        "focus": spec["focus"], "matches": matches})
    return candidates


def render_recommendation_actions(actions, context, evidence=()):
    claims = {claim.claim_id: claim for claim in context.claims}
    candidates = {(item["action_id"], item["claim_id"], item["metric_code"]): item
                  for item in eligible_actions(context, evidence)}
    recommendations = []
    seen = set()
    ordered = sorted(actions.recommendations, key=lambda action: ACTION_SPECS.get(action.action_id, {}).get("priority", 99))
    for action in ordered:
        candidate = candidates.get((action.action_id, action.claim_id, action.metric_code))
        if candidate is None or (action.claim_id, action.metric_code) in seen:
            continue
        matches = {match["evidence_id"]: match for match in candidate["matches"]}
        if candidate["basis"] == "data":
            if action.evidence_refs or (action.data_evidence_refs and tuple(action.data_evidence_refs) != candidate["data_evidence_refs"]):
                continue
        elif not action.evidence_refs or any(ref not in matches for ref in action.evidence_refs):
            continue
        seen.add((action.claim_id, action.metric_code))
        claim = claims[action.claim_id]
        unique_matches = {}
        for ref in action.evidence_refs:
            match = matches[ref]
            unique_matches.setdefault((match["excerpt"], match["protocol"]), match)
        selected_matches = tuple(unique_matches.values())
        recommendations.append(DraftRecommendation(
            recommendation_id=f"{candidate['basis']}-rec-{len(recommendations) + 1}", category=ACTION_SPECS[action.action_id]["category"],
            text=render_action(context, claim, action.metric_code, action.action_id),
            claim_refs=(action.claim_id,), evidence_refs=tuple(match["evidence_id"] for match in selected_matches),
            action_id=action.action_id, metric_code=action.metric_code,
            matching_basis=(f"test_type={context.test_type}", f"finding_type={claim.finding_type}",
                            f"priority={candidate['priority']}", candidate["focus"]),
            evidence_matches=selected_matches, basis=candidate["basis"],
            data_evidence_refs=candidate["data_evidence_refs"],
        ))
    return DraftRecommendationPackage(recommendations=tuple(recommendations))

_DOMAIN_BY_TEST_TYPE = {
    "Jump Test": "jump",
    "Treadmill Gait Test": "walk",
    "Treadmill Running Test": "run",
    "Sprint and Gait Test": "walk",
    "Overground Running Test": "run",
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
        if not any(action["basis"] == "literature" for action in eligible_actions(context, evidence)):
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
                return render_recommendation_actions(result.output, context, evidence)
            finally:
                await client.aclose()

        return asyncio.run(flow())

    @staticmethod
    def _prompt(context, evidence) -> str:
        payload = {
            "test_type": context.test_type,
            "test_conditions": context.test_conditions,
            "eligible_actions": [action for action in eligible_actions(context, evidence) if action["basis"] == "literature"],
            "claims": [claim.model_dump(mode="json", exclude={"evidence": {"__all__": {"record_groups"}}})
                       for claim in context.claims],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "domain": item.domain,
                    "metric_codes": item.metric_codes,
                    "support_types": item.support_types,
                    "locator": item.locator,
                    "protocol": item.metadata.get("protocol"),
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
            if any(not any(verified_finding_evidence(context, claims[ref], metric)
                           for metric in claims[ref].metric_codes)
                   for ref in item.claim_refs if ref in claims):
                reason = reason or "unverified_finding"
            if not item.action_id:
                reason = reason or "structured_action_required"
            if item.action_id and reason is None:
                expected = render_recommendation_actions(RecommendationActions(recommendations=(
                    RecommendationAction(action_id=item.action_id, claim_id=item.claim_refs[0] if item.claim_refs else "",
                                         metric_code=item.metric_code or "", evidence_refs=item.evidence_refs,
                                         data_evidence_refs=item.data_evidence_refs),
                )), context, evidence)
                if (len(expected.recommendations) != 1 or len(item.claim_refs) != 1
                        or expected.recommendations[0].model_dump(exclude={"recommendation_id"})
                        != item.model_dump(exclude={"recommendation_id"})):
                    reason = reason or "action_evidence_mismatch"
            if not item.action_id and re.search(r"\d", item.text):
                reason = reason or "unsupported_numeric_recommendation"
            if not item.action_id and not context.quality_codes and _QUALITY_INFERENCE.search(item.text):
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
                    action_id=item.action_id, metric_code=item.metric_code,
                    matching_basis=item.matching_basis, evidence_matches=item.evidence_matches,
                    basis=item.basis, data_evidence_refs=item.data_evidence_refs,
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
        if item.basis == "data":
            return None if item.action_id and not item.evidence_refs else "invalid_data_action_binding"
        if not item.evidence_refs or any(
            ref not in evidence_by_id for ref in item.evidence_refs
        ):
            return "invalid_evidence_reference"
        if not item.action_id and (_FORBIDDEN.search(item.text) or _DOSAGE_NUMBER.search(item.text)):
            return "forbidden_recommendation_content"
        if _CITATION_SURFACE.search(item.text):
            return "forbidden_citation_surface"
        allowed_support = _SUPPORT_BY_CATEGORY[item.category]
        claim_metrics = {
            metric
            for ref in item.claim_refs
            for metric in claims[ref].metric_codes
        }
        if item.action_id:
            claim_metrics = {code for metric in claim_metrics for code in literature_metrics(metric)}
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


def build_data_followups(context):
    candidates = [action for action in eligible_actions(context, ()) if action["basis"] == "data"]
    choices = RecommendationActions(recommendations=tuple(RecommendationAction(
        action_id=action["action_id"], claim_id=action["claim_id"], metric_code=action["metric_code"],
        data_evidence_refs=action["data_evidence_refs"],
    ) for action in candidates[:3]))
    draft = render_recommendation_actions(choices, context)
    return RecommendationValidator().validate(draft, context, ())[0].recommendations
