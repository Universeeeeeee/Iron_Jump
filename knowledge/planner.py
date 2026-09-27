"""Deterministic report-context to knowledge-query planning."""

from __future__ import annotations

import hashlib

from reporting.metric_catalog import METRIC_CATALOG

from .catalog import load_catalog
from .models import (
    Domain,
    KnowledgeQuerySpec,
    RecommendationIntent,
    ReportRAGContext,
    SupportType,
)


PLANNER_VERSION = "deterministic-query-planner/1.1"

_DOMAIN_BY_TEST_TYPE: dict[str, Domain] = {
    "Jump Test": "jump",
    "Treadmill Gait Test": "walk",
    "Treadmill Running Test": "run",
    "Sprint and Gait Test": "walk",
    "Overground Running Test": "run",
}

# Ground reports must not inherit treadmill or distance-training evidence.
_GROUND_PROTOCOLS = {
    "Sprint and Gait Test": ("overground_walk",),
    "Overground Running Test": ("overground_run", "treadmill_and_overground_run"),
}

_TERMS_BY_INTENT: dict[RecommendationIntent, str] = {
    "measurement_review": "measurement validity reliability limitations",
    "technique_focus": "movement technique performance",
    "general_training_focus": "training intervention performance systematic review",
    "retest": "measurement repeatability standardized retest protocol",
    "coach_review": "measurement interpretation coach review",
}

_SUPPORT_BY_INTENT: dict[RecommendationIntent, tuple[SupportType, ...]] = {
    "measurement_review": ("method", "interpretation", "limitation"),
    "technique_focus": ("training_direction",),
    "general_training_focus": ("training_direction",),
    "retest": ("method", "limitation"),
    "coach_review": ("method", "interpretation", "limitation"),
}


class SupportMatrix:
    """The enabled matrix is derived only from reviewed catalog metadata."""

    def __init__(self, sources=None):
        self._sources = tuple(sources or load_catalog())

    def supports(
        self,
        domain: Domain,
        metric_codes: tuple[str, ...],
        population: str,
        intent: RecommendationIntent,
        protocols: tuple[str, ...] = (),
    ) -> bool:
        allowed_types = set(_SUPPORT_BY_INTENT[intent])
        for source in self._sources:
            if protocols and source.metadata.get("protocol") not in protocols:
                continue
            if not source.recommendation_allowed or domain not in source.domains:
                continue
            if population not in source.populations:
                continue
            if not set(metric_codes).intersection(source.metric_codes):
                continue
            if allowed_types.intersection(source.support_types):
                return True
        return False


class QueryPlanner:
    def __init__(self, support_matrix: SupportMatrix | None = None):
        self._support_matrix = support_matrix or SupportMatrix()

    def plan(self, context: ReportRAGContext) -> tuple[KnowledgeQuerySpec, ...]:
        if not context.claims:
            return ()
        domain = _DOMAIN_BY_TEST_TYPE.get(context.test_type)
        if domain is None:
            return ()
        protocols = _GROUND_PROTOCOLS.get(context.test_type, ())
        claim_metrics = {
            metric
            for claim in context.claims
            for metric in claim.metric_codes
        }
        metric_codes = tuple(
            sorted(claim_metrics.intersection(context.metric_codes))
        )
        if not metric_codes:
            return ()

        intents: list[RecommendationIntent] = ["measurement_review"]
        if context.quality_codes or any(claim.limitations for claim in context.claims):
            intents.append("retest")
        intents.append("general_training_focus")

        specs = []
        seen = set()
        for intent in intents:
            key = (domain, metric_codes, intent)
            if key in seen or not self._support_matrix.supports(
                domain, metric_codes, context.population, intent, protocols
            ):
                continue
            seen.add(key)
            labels = [
                METRIC_CATALOG[code].label if code in METRIC_CATALOG else code
                for code in metric_codes
            ]
            query = " ".join([domain, *labels, *metric_codes, _TERMS_BY_INTENT[intent]])
            if protocols:
                query += " " + " ".join(protocols)
            query_id = hashlib.sha256(
                f"{PLANNER_VERSION}\x1f{context.test_type}\x1f{domain}\x1f{','.join(metric_codes)}\x1f{intent}".encode()
            ).hexdigest()[:24]
            specs.append(
                KnowledgeQuerySpec(
                    query_id=query_id,
                    query=query,
                    domain=domain,
                    metric_codes=metric_codes,
                    population=context.population,
                    support_types=_SUPPORT_BY_INTENT[intent],
                    recommendation_allowed=True,
                    recommendation_intent=intent,
                    planner_version=PLANNER_VERSION,
                    protocols=protocols,
                )
            )
            if len(specs) == 3:
                break
        return tuple(specs)
