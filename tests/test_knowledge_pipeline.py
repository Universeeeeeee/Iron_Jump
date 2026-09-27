from knowledge.models import (
    DraftRecommendation,
    DraftRecommendationPackage,
    KnowledgeQuerySpec,
    KnowledgeSource,
    LiteratureEvidence,
    RecommendationClaim,
    ReportRAGContext,
)
from knowledge.pipeline import DeterministicRAGPipeline
from knowledge.recommendations import RecommendationValidator


class _Planner:
    def plan(self, context):
        return (
            KnowledgeQuerySpec(
                query_id="query-1",
                query="jump height measurement validity",
                domain="jump",
                metric_codes=("jump_height_m",),
                population="general",
                support_types=("method",),
                recommendation_allowed=True,
                recommendation_intent="measurement_review",
                planner_version="test",
            ),
        )


class _Retriever:
    def __init__(self, evidence=()):
        self.evidence = evidence
        self.calls = 0

    def retrieve(self, spec):
        self.calls += 1
        return self.evidence


class _Generator:
    model_name = "fake-model"
    prompt_version = "fake-prompt/1.0"

    def __init__(self, *, fail=False):
        self.calls = 0
        self.fail = fail

    def generate(self, context, evidence):
        self.calls += 1
        if self.fail:
            raise ValueError("invalid structured output")
        return DraftRecommendationPackage(
            recommendations=(
                DraftRecommendation(
                    recommendation_id="rec-1",
                    category="measurement_review",
                    text="建议复核起跳和落地动作的一致性。",
                    claim_refs=("claim-1",),
                    evidence_refs=("evidence-1",),
                ),
            )
        )


def _source():
    return KnowledgeSource(
        source_id="s1",
        title="Paper",
        url="https://example.org/paper",
        download_url="https://example.org/paper.xml",
        source_format="jats_xml",
        source_kind="journal_article",
        domains=("jump",),
        metric_codes=("jump_height_m",),
        populations=("general",),
        support_types=("method",),
        recommendation_allowed=True,
        license="CC BY",
        ingest_policy="full_text",
    )


def _evidence():
    return LiteratureEvidence(
        evidence_id="evidence-1",
        query_id="query-1",
        chunk_id="chunk-1",
        document_id="s1",
        source_id="s1",
        domain="jump",
        metric_codes=("jump_height_m",),
        populations=("general",),
        support_types=("method",),
        recommendation_allowed=True,
        locator="Methods ¶1",
        excerpt="Take-off and landing posture affect flight-time estimates.",
        content_digest="b" * 64,
        score=0.03,
    )


def _context():
    return ReportRAGContext(
        package_digest="a" * 64,
        test_type="Jump Test",
        metric_codes=("jump_height_m",),
        claims=(
            RecommendationClaim(
                claim_id="claim-1",
                text="跳跃高度后段较低。",
                metric_codes=("jump_height_m",),
            ),
        ),
    )


def test_fixture_context_to_validated_package_and_citation():
    retriever = _Retriever((_evidence(),))
    generator = _Generator()
    pipeline = DeterministicRAGPipeline(
        retriever,
        planner=_Planner(),
        generator=generator,
        validator=RecommendationValidator((_source(),)),
    )

    result = pipeline.run(_context())

    assert result.audit.status == "ok"
    assert generator.calls == 1
    assert len(result.package.recommendations) == 1
    assert result.package.citations[0].url == "https://example.org/paper"
    assert "完整 Prompt" not in result.audit.model_dump_json()
    assert "Take-off and landing" not in result.audit.model_dump_json()


def test_empty_evidence_skips_generation():
    generator = _Generator()
    result = DeterministicRAGPipeline(
        _Retriever(), planner=_Planner(), generator=generator
    ).run(_context())
    assert result.audit.status == "no_evidence"
    assert generator.calls == 0
    assert result.package.recommendations == ()


def test_generation_failure_is_not_retried_and_degrades():
    generator = _Generator(fail=True)
    result = DeterministicRAGPipeline(
        _Retriever((_evidence(),)),
        planner=_Planner(),
        generator=generator,
    ).run(_context())
    assert result.audit.status == "degraded"
    assert result.audit.error_code == "generation_or_validation_failed"
    assert generator.calls == 1
    assert result.package.recommendations == ()


def test_planning_failure_degrades_without_retrieving_or_generating():
    class BrokenPlanner:
        def plan(self, context):
            raise RuntimeError("broken catalog")

    retriever, generator = _Retriever(), _Generator()
    result = DeterministicRAGPipeline(
        retriever, planner=BrokenPlanner(), generator=generator
    ).run(_context())
    assert result.audit.status == "degraded"
    assert result.audit.error_code == "planning_failed"
    assert retriever.calls == generator.calls == 0


def test_unsupported_ground_running_reports_reason_without_generation():
    retriever, generator = _Retriever(), _Generator()
    context = _context().model_copy(update={"test_type": "Overground Running Test"})
    result = DeterministicRAGPipeline(retriever, generator=generator).run(context)
    assert result.audit.status == "no_evidence"
    assert result.audit.error_code == "no_supported_query"
    assert retriever.calls == generator.calls == 0
