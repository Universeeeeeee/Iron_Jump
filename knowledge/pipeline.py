"""Deterministic V1 RAG orchestration without tools or retrieval loops."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .chunking import CHUNKER_VERSION
from .embeddings import MODEL_VERSION
from .models import AuditRetrieval, RAGAudit, RAGResult, ReportRAGContext
from .planner import PLANNER_VERSION, QueryPlanner
from .recommendations import (
    RECOMMENDATION_MODEL_NAME,
    RECOMMENDATION_PROMPT_VERSION,
    DeepSeekRecommendationGenerator,
    RecommendationValidator,
)
from .retrieval import RETRIEVER_VERSION


def degraded_rag_result(
    analysis_input_digest: str,
    error_code: str,
) -> RAGResult:
    return RAGResult(
        audit=RAGAudit(
            status="degraded",
            analysis_input_digest=analysis_input_digest,
            corpus_version="unknown",
            planner_version=PLANNER_VERSION,
            chunker_version=CHUNKER_VERSION,
            embedding_version=MODEL_VERSION,
            retriever_version=RETRIEVER_VERSION,
            prompt_version=RECOMMENDATION_PROMPT_VERSION,
            model_name=RECOMMENDATION_MODEL_NAME,
            error_code=error_code,
        )
    )


class DeterministicRAGPipeline:
    def __init__(
        self,
        retriever,
        *,
        planner=None,
        generator=None,
        validator=None,
        manifest_path: Path | None = None,
    ):
        self._retriever = retriever
        self._planner = planner or QueryPlanner()
        self._generator = generator or DeepSeekRecommendationGenerator()
        self._validator = validator or RecommendationValidator()
        self._manifest_path = manifest_path

    def run(self, context: ReportRAGContext) -> RAGResult:
        started = time.perf_counter()
        input_digest = self._digest(context.model_dump(mode="json"))
        try:
            specs = self._planner.plan(context)
        except Exception:
            return self._failure(context, input_digest, (), (), started, "planning_failed")
        retrievals = []
        evidence = []
        try:
            for spec in specs:
                resolved = self._retriever.retrieve(spec)
                evidence.extend(resolved)
                retrievals.append(
                    AuditRetrieval(
                        query_id=spec.query_id,
                        evidence_ids=tuple(item.evidence_id for item in resolved),
                        scores=tuple(item.score for item in resolved),
                    )
                )
        except Exception:
            return self._failure(
                context,
                input_digest,
                specs,
                tuple(retrievals),
                started,
                "retrieval_failed",
            )

        resolved_evidence = tuple(evidence)
        if not resolved_evidence:
            return RAGResult(
                audit=self._audit(
                    status="no_evidence",
                    input_digest=input_digest,
                    specs=specs,
                    retrievals=tuple(retrievals),
                    started=started,
                    error_code="no_matching_evidence" if specs else "no_supported_query",
                )
            )
        try:
            draft = self._generator.generate(context, resolved_evidence)
            package, validations = self._validator.validate(
                draft, context, resolved_evidence
            )
        except Exception:
            return self._failure(
                context,
                input_digest,
                specs,
                tuple(retrievals),
                started,
                "generation_or_validation_failed",
                evidence=resolved_evidence,
            )
        output_digest = self._digest(package.model_dump(mode="json"))
        return RAGResult(
            evidence=resolved_evidence,
            package=package,
            audit=self._audit(
                status="ok",
                input_digest=input_digest,
                specs=specs,
                retrievals=tuple(retrievals),
                validations=validations,
                citation_ids=tuple(item.citation_id for item in package.citations),
                output_digest=output_digest,
                started=started,
            ),
        )

    def _failure(
        self,
        context,
        input_digest,
        specs,
        retrievals,
        started,
        error_code,
        *,
        evidence=(),
    ):
        return RAGResult(
            evidence=evidence,
            audit=self._audit(
                status="degraded",
                input_digest=input_digest,
                specs=specs,
                retrievals=retrievals,
                error_code=error_code,
                started=started,
            ),
        )

    def _audit(
        self,
        *,
        status,
        input_digest,
        specs,
        retrievals,
        started,
        validations=(),
        citation_ids=(),
        error_code=None,
        output_digest="",
    ):
        return RAGAudit(
            status=status,
            analysis_input_digest=input_digest,
            corpus_version=self._corpus_version(),
            planner_version=PLANNER_VERSION,
            chunker_version=CHUNKER_VERSION,
            embedding_version=MODEL_VERSION,
            retriever_version=RETRIEVER_VERSION,
            prompt_version=getattr(
                self._generator, "prompt_version", RECOMMENDATION_PROMPT_VERSION
            ),
            model_name=getattr(
                self._generator, "model_name", RECOMMENDATION_MODEL_NAME
            ),
            query_specs=specs,
            retrievals=retrievals,
            citation_ids=citation_ids,
            validations=validations,
            elapsed_ms=max(0, int((time.perf_counter() - started) * 1000)),
            error_code=error_code,
            output_digest=output_digest,
        )

    def _corpus_version(self):
        if self._manifest_path is None or not self._manifest_path.exists():
            return "unknown"
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))[
                "corpus_version"
            ]
        except (OSError, KeyError, ValueError, TypeError):
            return "unknown"

    @staticmethod
    def _digest(value) -> str:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
