"""Stable, provider-neutral contracts for deterministic sports RAG."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


Domain = Literal["jump", "walk", "run", "general"]
SupportType = Literal[
    "definition",
    "method",
    "background",
    "interpretation",
    "limitation",
    "training_direction",
]
RecommendationIntent = Literal[
    "measurement_review",
    "technique_focus",
    "general_training_focus",
    "retest",
    "coach_review",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _validate_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must be an absolute HTTP(S) URL")
    return value


class KnowledgeSource(FrozenModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str
    download_url: str | None = None
    source_format: Literal["jats_xml", "pdf", "metadata"]
    source_kind: Literal["journal_article", "official_manual", "official_web", "book"]
    domains: tuple[Domain, ...]
    metric_codes: tuple[str, ...] = ()
    populations: tuple[str, ...] = ("general",)
    support_types: tuple[SupportType, ...] = ("background",)
    recommendation_allowed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    authors: tuple[str, ...] = ()
    year: int | None = None
    publisher: str = ""
    doi: str | None = None
    license: str
    ingest_policy: Literal["full_text", "metadata_only"]

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)

    @field_validator("download_url")
    @classmethod
    def validate_download_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_http_url(value)


class KnowledgeDocument(FrozenModel):
    document_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    canonical_uri: str
    active_version_id: str | None = None

    @field_validator("canonical_uri")
    @classmethod
    def validate_canonical_uri(cls, value: str) -> str:
        return _validate_http_url(value)


class DocumentVersion(FrozenModel):
    version_id: str = Field(min_length=64, max_length=64)
    document_id: str = Field(min_length=1)
    raw_digest: str = Field(min_length=64, max_length=64)
    normalized_digest: str = Field(min_length=64, max_length=64)
    source_format: Literal["jats_xml", "pdf"]
    parser_version: str
    ingested_at: str
    active: bool = False


class KnowledgeChunk(FrozenModel):
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    document_id: str = ""
    version_id: str = ""
    domain: Domain
    section: str
    locator: str
    logical_position: str = ""
    text: str = Field(min_length=1)
    content_digest: str = Field(min_length=64, max_length=64)
    token_count: int = Field(ge=1)
    metric_codes: tuple[str, ...] = ()
    populations: tuple[str, ...] = ("general",)
    support_types: tuple[SupportType, ...] = ("background",)
    recommendation_allowed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationClaim(FrozenModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    metric_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class ReportRAGContext(FrozenModel):
    package_digest: str = Field(min_length=1)
    test_type: str = Field(min_length=1)
    metric_codes: tuple[str, ...]
    claims: tuple[RecommendationClaim, ...]
    quality_codes: tuple[str, ...] = ()
    population: str = "general"


class KnowledgeQuerySpec(FrozenModel):
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    domain: Domain
    metric_codes: tuple[str, ...]
    population: str
    support_types: tuple[SupportType, ...]
    recommendation_allowed: bool
    recommendation_intent: RecommendationIntent
    planner_version: str
    protocols: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(FrozenModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=8, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def non_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must be non-blank")
        return value


class SearchSource(FrozenModel):
    """The exact Harness-style model-facing source seam."""

    url: str
    title: str | None = None
    snippet: str | None = None
    published_at: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)


class SearchResult(FrozenModel):
    content: str | None = None
    sources: tuple[SearchSource, ...]
    truncated: bool


class RetrievalHit(FrozenModel):
    chunk: KnowledgeChunk
    source: KnowledgeSource
    score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None

    def as_search_source(self) -> SearchSource:
        snippet = self.chunk.text.replace("\n", " ").strip()
        if len(snippet) > 240:
            snippet = snippet[:237].rstrip() + "..."
        return SearchSource(
            url=self.source.url,
            title=self.source.title,
            snippet=f"{self.chunk.locator}: {snippet}",
            published_at=str(self.source.year) if self.source.year else None,
        )


class LiteratureEvidence(FrozenModel):
    evidence_id: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    domain: Domain
    metric_codes: tuple[str, ...]
    populations: tuple[str, ...]
    support_types: tuple[SupportType, ...]
    recommendation_allowed: bool
    locator: str
    excerpt: str = Field(min_length=1)
    content_digest: str = Field(min_length=64, max_length=64)
    score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Citation(FrozenModel):
    citation_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str
    doi: str | None = None
    locator: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_http_url(value)


class CitationBinding(FrozenModel):
    binding_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    support_type: SupportType


class Recommendation(FrozenModel):
    recommendation_id: str = Field(min_length=1)
    category: RecommendationIntent
    text: str = Field(min_length=1)
    claim_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    citation_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class DraftRecommendation(FrozenModel):
    recommendation_id: str = Field(min_length=1)
    category: RecommendationIntent
    text: str = Field(min_length=1)
    claim_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...] = ()


class DraftRecommendationPackage(FrozenModel):
    recommendations: tuple[DraftRecommendation, ...] = ()


class ValidatedRecommendationPackage(FrozenModel):
    recommendations: tuple[Recommendation, ...] = ()
    citations: tuple[Citation, ...] = ()
    references_markdown: str = ""


class AuditRetrieval(FrozenModel):
    query_id: str
    evidence_ids: tuple[str, ...]
    scores: tuple[float, ...]


class AuditValidation(FrozenModel):
    recommendation_id: str
    accepted: bool
    reason: str = ""


class RAGAudit(FrozenModel):
    status: Literal["ok", "degraded", "no_evidence"]
    analysis_input_digest: str
    corpus_version: str
    planner_version: str
    chunker_version: str
    embedding_version: str
    retriever_version: str
    prompt_version: str
    model_name: str
    query_specs: tuple[KnowledgeQuerySpec, ...] = ()
    retrievals: tuple[AuditRetrieval, ...] = ()
    citation_ids: tuple[str, ...] = ()
    validations: tuple[AuditValidation, ...] = ()
    elapsed_ms: int = Field(default=0, ge=0)
    error_code: str | None = None
    output_digest: str = ""


class RAGResult(FrozenModel):
    evidence: tuple[LiteratureEvidence, ...] = ()
    package: ValidatedRecommendationPackage = Field(
        default_factory=ValidatedRecommendationPackage
    )
    audit: RAGAudit
