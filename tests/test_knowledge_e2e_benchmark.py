"""Thirty fixed V1 end-to-end fixtures: ten per supported report mode."""

import pytest

from knowledge.models import (
    KnowledgeQuerySpec,
    KnowledgeSource,
    LiteratureEvidence,
)
from knowledge.pipeline import DeterministicRAGPipeline
from knowledge.live_benchmark import benchmark_contexts
from knowledge.recommendations import RecommendationValidator
from tests.knowledge_fixtures import verified_context, reviewed_support, action_draft


DOMAINS = (
    ("jump", "Jump Test", "jump_height_m"),
    ("walk", "Treadmill Gait Test", "step_length_cm"),
    ("run", "Treadmill Running Test", "contact_time_s"),
)
MODES = (
    "valid-1",
    "valid-2",
    "valid-3",
    "valid-4",
    "no-evidence",
    "generation-failure",
    "bad-reference",
    "forbidden-dosage",
    "bad-population",
    "deterministic-repeat",
)
CASES = tuple(
    (domain, test_type, metric, mode)
    for domain, test_type, metric in DOMAINS
    for mode in MODES
)


def test_live_review_fixture_set_is_fixed_at_thirty_cases():
    contexts = benchmark_contexts()
    assert len(contexts) == 30
    assert len({case_id for case_id, _ in contexts}) == 30



class _Planner:
    def __init__(self, spec):
        self.spec = spec

    def plan(self, context):
        return (self.spec,)


class _Retriever:
    def __init__(self, evidence):
        self.evidence = evidence

    def retrieve(self, spec):
        return self.evidence


class _Generator:
    model_name = "benchmark-model"
    prompt_version = "benchmark-prompt/1.0"

    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def generate(self, context, evidence):
        self.calls += 1
        if self.mode == "generation-failure":
            raise ValueError("synthetic parse failure")
        evidence_refs = (
            ("missing",) if self.mode == "bad-reference" else ("evidence-1",)
        )
        text = (
            "每周3次，每次做4组。"
            if self.mode == "forbidden-dosage"
            else "建议复核测试动作与测量条件的一致性。"
        )
        valid_evidence = evidence[0].model_copy(update={"populations": ("general",)})
        draft = action_draft(context, valid_evidence)
        update = {"evidence_refs": evidence_refs}
        if self.mode == "forbidden-dosage":
            update["text"] = text
        return draft.model_copy(update={"recommendations": (draft.recommendations[0].model_copy(update=update),)})


def _fixture(domain, test_type, metric, mode):
    source = KnowledgeSource(
        source_id="source-1",
        title="Reviewed benchmark source",
        url="https://example.org/source",
        download_url="https://example.org/source.xml",
        source_format="jats_xml",
        source_kind="journal_article",
        domains=(domain,),
        metric_codes=(metric,),
        populations=("general",),
        support_types=("method",),
        recommendation_allowed=True,
        license="CC BY",
        ingest_policy="full_text",
    )
    spec = KnowledgeQuerySpec(
        query_id=f"query-{domain}",
        query=f"{domain} {metric} measurement reliability",
        domain=domain,
        metric_codes=(metric,),
        population="general",
        support_types=("method",),
        recommendation_allowed=True,
        recommendation_intent="measurement_review",
        planner_version="benchmark",
    )
    context = verified_context(metric, test_type)
    evidence = LiteratureEvidence(
        evidence_id="evidence-1",
        query_id=spec.query_id,
        chunk_id="chunk-1",
        document_id="source-1",
        source_id="source-1",
        domain=domain,
        metric_codes=(metric,),
        populations=("clinical",) if mode == "bad-population" else ("general",),
        support_types=("method",),
        recommendation_allowed=True,
        locator="Methods ¶1",
        excerpt="The standardized test method has documented reliability limitations.",
        content_digest="b" * 64,
        score=0.03,
        metadata=reviewed_support(metric, "The standardized test method has documented reliability limitations.",
                                  {"jump":"vertical_jump", "walk":"treadmill_walk", "run":"treadmill_run"}[domain]),
    )
    evidence_items = () if mode == "no-evidence" else (evidence,)
    generator = _Generator(mode)
    pipeline = DeterministicRAGPipeline(
        _Retriever(evidence_items),
        planner=_Planner(spec),
        generator=generator,
        validator=RecommendationValidator((source,)),
    )
    return context, pipeline, generator


@pytest.mark.parametrize("domain,test_type,metric,mode", CASES)
def test_v1_e2e_benchmark_fixture(domain, test_type, metric, mode):
    assert len(CASES) == 30
    context, pipeline, generator = _fixture(domain, test_type, metric, mode)

    result = pipeline.run(context)

    if mode == "no-evidence":
        assert result.audit.status == "no_evidence"
        assert generator.calls == 0
    elif mode == "generation-failure":
        assert result.audit.status == "degraded"
        assert generator.calls == 1
    elif mode in {"bad-reference", "forbidden-dosage", "bad-population"}:
        assert result.audit.status == "ok"
        assert result.package.recommendations == ()
        assert result.audit.validations[0].accepted is False
    else:
        assert result.audit.status == "ok"
        assert len(result.package.recommendations) == 1
        assert len(result.package.citations) == 1

    if mode == "deterministic-repeat":
        repeated = pipeline.run(context)
        assert result.audit.query_specs == repeated.audit.query_specs
        assert result.audit.retrievals == repeated.audit.retrievals
        assert result.audit.output_digest == repeated.audit.output_digest
