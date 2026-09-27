"""Deterministic bilingual hybrid retrieval with reciprocal-rank fusion."""

from __future__ import annotations

import hashlib

import numpy as np

from .embeddings import LocalEmbeddingModel
from .models import (
    KnowledgeQuerySpec,
    LiteratureEvidence,
    RetrievalHit,
    SearchRequest,
    SearchResult,
)
from .store import KnowledgeStore


_ALIASES = {
    "跳跃高度": "vertical jump height flight time countermovement jump CMJ",
    "腾空时间": "flight time air time",
    "触地时间": "contact time ground contact time",
    "步态周期": "gait cycle stride time",
    "步长": "step length",
    "步幅": "stride length",
    "步频": "cadence step frequency",
    "双支撑": "double support",
    "单支撑": "single support",
    "支撑相": "stance phase stance time",
    "摆动相": "swing phase swing time",
    "跑步机": "treadmill running walking",
    "地面跑": "overground running",
    "误差": "measurement error systematic bias limitation posture take-off landing",
    "帧率": "video frame rate technical error",
    "一致性": "agreement validity reliability Bland Altman",
}

RETRIEVER_VERSION = "hybrid-fts5-dense-rrf/1.1"


def expand_query(query: str) -> str:
    additions = [alias for term, alias in _ALIASES.items() if term in query]
    return " ".join([query.strip(), *additions]).strip()


class HybridRetriever:
    def __init__(self, store: KnowledgeStore, embedder: LocalEmbeddingModel):
        self._store = store
        self._embedder = embedder

    def search(
        self,
        request: SearchRequest,
        *,
        domain: str | None = None,
    ) -> tuple[RetrievalHit, ...]:
        query = expand_query(request.query)
        query_vector = self._embedder.embed_query(query)
        all_rows = self._store.load_all(domain)
        return self._rank(query, query_vector, all_rows, request.max_results, domain=domain)

    def retrieve(self, spec: KnowledgeQuerySpec) -> tuple[LiteratureEvidence, ...]:
        query = expand_query(spec.query)
        query_vector = self._embedder.embed_query(query)
        all_rows = self._store.load_all(spec=spec)
        hits = self._rank(query, query_vector, all_rows, 6, spec=spec)
        return tuple(self._as_evidence(spec, hit) for hit in hits)

    def _rank(self, query, query_vector, all_rows, max_results, *, domain=None, spec=None):
        dense_scored = []
        query_norm = float(np.linalg.norm(query_vector)) or 1.0
        for chunk, source, vector in all_rows:
            denominator = query_norm * (float(np.linalg.norm(vector)) or 1.0)
            dense_scored.append((float(np.dot(query_vector, vector) / denominator), chunk, source))
        dense_scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        dense_top = dense_scored[:20]
        lexical_top = self._store.lexical_search(query, 20, domain, spec=spec)

        fused: dict[str, dict] = {}
        for rank, (score, chunk, source) in enumerate(dense_top, start=1):
            fused[chunk.chunk_id] = {
                "chunk": chunk,
                "source": source,
                "score": 1.0 / (60 + rank),
                "dense_rank": rank,
                "lexical_rank": None,
            }
        for rank, (chunk, source, _vector) in enumerate(lexical_top, start=1):
            item = fused.setdefault(
                chunk.chunk_id,
                {
                    "chunk": chunk,
                    "source": source,
                    "score": 0.0,
                    "dense_rank": None,
                    "lexical_rank": None,
                },
            )
            item["score"] += 1.0 / (60 + rank)
            item["lexical_rank"] = rank
        ranked = sorted(fused.values(), key=lambda item: (-item["score"], item["chunk"].chunk_id))
        hits = []
        source_counts: dict[str, int] = {}
        for item in ranked:
            source_id = item["source"].source_id
            if source_counts.get(source_id, 0) >= 2:
                continue
            source_counts[source_id] = source_counts.get(source_id, 0) + 1
            hits.append(RetrievalHit(**item))
            if len(hits) >= max_results:
                break
        return tuple(hits)

    @staticmethod
    def _as_evidence(spec: KnowledgeQuerySpec, hit: RetrievalHit) -> LiteratureEvidence:
        evidence_id = hashlib.sha256(
            f"{spec.query_id}\x1f{hit.chunk.chunk_id}".encode("utf-8")
        ).hexdigest()[:24]
        return LiteratureEvidence(
            evidence_id=evidence_id,
            query_id=spec.query_id,
            chunk_id=hit.chunk.chunk_id,
            document_id=hit.chunk.document_id,
            source_id=hit.source.source_id,
            domain=hit.chunk.domain,
            metric_codes=hit.chunk.metric_codes,
            populations=hit.chunk.populations,
            support_types=hit.chunk.support_types,
            recommendation_allowed=hit.chunk.recommendation_allowed,
            locator=hit.chunk.locator,
            excerpt=hit.chunk.text,
            content_digest=hit.chunk.content_digest,
            score=hit.score,
            dense_rank=hit.dense_rank,
            lexical_rank=hit.lexical_rank,
            metadata=hit.chunk.metadata,
        )

    def model_result(self, request: SearchRequest, hits: tuple[RetrievalHit, ...]) -> SearchResult:
        content = "\n\n".join(
            f"[{hit.chunk.chunk_id}] {hit.chunk.locator}\n{hit.chunk.text}" for hit in hits
        )
        sources = []
        seen_urls = set()
        for hit in hits:
            if hit.source.url in seen_urls:
                continue
            seen_urls.add(hit.source.url)
            sources.append(hit.as_search_source())
        return SearchResult(
            content=content or None,
            sources=tuple(sources),
            truncated=False,
        )
