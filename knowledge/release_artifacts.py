"""Canonical V1 RAG release artifacts and frozen-version fingerprints."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .catalog import DEFAULT_CATALOG_PATH
from .chunking import CHUNKER_VERSION
from .embeddings import MODEL_VERSION
from .ingestion import DEFAULT_DATA_DIR
from .live_benchmark import LIVE_BENCHMARK_VERSION, benchmark_contexts
from .planner import PLANNER_VERSION
from .recommendations import (
    RECOMMENDATION_MODEL_NAME,
    RECOMMENDATION_PROMPT_VERSION,
    RECOMMENDATION_SYSTEM_PROMPT,
    recommendation_content_digest,
)
from .retrieval import RETRIEVER_VERSION


RELEASE_GATE_VERSION = "sports-rag-v1/1.2"
DEFAULT_MANIFEST_PATH = DEFAULT_DATA_DIR / "manifest.json"
DEFAULT_FROZEN_REVIEW_PATH = (
    Path(__file__).with_name("release_artifacts")
    / "sports-rag-v1-groundedness.json"
)


class ReleaseArtifactError(ValueError):
    pass


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_digest(value) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_json_object(path: Path, *, label: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReleaseArtifactError(f"{label} must be a JSON object")
    return value


def build_runtime_content_digests(
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, str]:
    catalog = load_json_object(catalog_path, label="knowledge catalog")
    manifest = load_json_object(manifest_path, label="corpus manifest")
    benchmark_cases = [
        {
            "case_id": case_id,
            "context": context.model_dump(mode="json"),
        }
        for case_id, context in benchmark_contexts()
    ]
    return {
        "catalog_digest": canonical_json_digest(catalog),
        "manifest_digest": canonical_json_digest(manifest),
        "recommendation_prompt_digest": recommendation_content_digest(RECOMMENDATION_SYSTEM_PROMPT),
        "benchmark_cases_digest": canonical_json_digest(benchmark_cases),
    }


def validate_groundedness_review(
    review: dict,
    *,
    expected_runtime_signature: tuple | None = None,
    expected_content_digests: dict[str, str] | None = None,
) -> None:
    if review.get("benchmark_version") != LIVE_BENCHMARK_VERSION:
        raise ReleaseArtifactError("groundedness benchmark version mismatch")
    if review.get("review_status") != "passed":
        raise ReleaseArtifactError("groundedness review is not passed")
    if review.get("unsupported_recommendation_count") != 0:
        raise ReleaseArtifactError(
            "groundedness review contains unsupported recommendations"
        )
    rows = review.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ReleaseArtifactError("groundedness review rows are missing")
    expected_case_ids = tuple(
        case_id for case_id, _ in benchmark_contexts()
    )
    reviewed_case_ids = tuple(
        row.get("case_id") if isinstance(row, dict) else None
        for row in rows
    )
    if (
        review.get("case_count") != len(expected_case_ids)
        or len(reviewed_case_ids) != len(set(reviewed_case_ids))
        or set(reviewed_case_ids) != set(expected_case_ids)
    ):
        raise ReleaseArtifactError(
            "groundedness review does not cover the complete benchmark case set"
        )
    content_digests = review.get("runtime_content_digests")
    if (
        not isinstance(content_digests, dict)
        or set(content_digests) != {
            "catalog_digest",
            "manifest_digest",
            "recommendation_prompt_digest",
            "benchmark_cases_digest",
        }
        or any(
            not isinstance(value, str) or len(value) != 64
            for value in content_digests.values()
        )
    ):
        raise ReleaseArtifactError(
            "groundedness review content digests are missing or invalid"
        )
    if (
        expected_content_digests is not None
        and content_digests != expected_content_digests
    ):
        raise ReleaseArtifactError(
            "groundedness review does not match the frozen runtime content"
        )
    signatures = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ReleaseArtifactError("groundedness review row is invalid")
        if row.get("groundedness_review") != "supported":
            raise ReleaseArtifactError(
                "groundedness review contains pending or rejected rows"
            )
        audit = row.get("audit")
        if not isinstance(audit, dict):
            raise ReleaseArtifactError("groundedness review audit is missing")
        signatures.add(
            (
                audit.get("corpus_version"),
                audit.get("planner_version"),
                audit.get("chunker_version"),
                audit.get("embedding_version"),
                audit.get("retriever_version"),
                audit.get("prompt_version"),
                audit.get("model_name"),
            )
        )
    if len(signatures) != 1:
        raise ReleaseArtifactError(
            "groundedness review rows use inconsistent runtime versions"
        )
    if (
        expected_runtime_signature is not None
        and next(iter(signatures)) != expected_runtime_signature
    ):
        raise ReleaseArtifactError(
            "groundedness review does not match the frozen runtime versions"
        )


def promote_groundedness_review(
    source: Path,
    destination: Path,
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> dict:
    review = load_json_object(source, label="groundedness review")
    manifest = load_json_object(manifest_path, label="corpus manifest")
    validate_groundedness_review(
        review,
        expected_runtime_signature=(
            manifest.get("corpus_version"),
            PLANNER_VERSION,
            CHUNKER_VERSION,
            MODEL_VERSION,
            RETRIEVER_VERSION,
            RECOMMENDATION_PROMPT_VERSION,
            RECOMMENDATION_MODEL_NAME,
        ),
        expected_content_digests=build_runtime_content_digests(
            catalog_path=catalog_path,
            manifest_path=manifest_path,
        ),
    )
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(review) + b"\n")
    return review


def build_release_fingerprint(
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    review_path: Path = DEFAULT_FROZEN_REVIEW_PATH,
) -> str:
    manifest = load_json_object(manifest_path, label="corpus manifest")
    review = load_json_object(review_path, label="groundedness review")
    runtime_content_digests = build_runtime_content_digests(
        catalog_path=catalog_path,
        manifest_path=manifest_path,
    )
    validate_groundedness_review(
        review,
        expected_runtime_signature=(
            manifest.get("corpus_version"),
            PLANNER_VERSION,
            CHUNKER_VERSION,
            MODEL_VERSION,
            RETRIEVER_VERSION,
            RECOMMENDATION_PROMPT_VERSION,
            RECOMMENDATION_MODEL_NAME,
        ),
        expected_content_digests=runtime_content_digests,
    )
    payload = {
        "gate_version": RELEASE_GATE_VERSION,
        "benchmark_version": LIVE_BENCHMARK_VERSION,
        "catalog_digest": runtime_content_digests["catalog_digest"],
        "manifest_digest": runtime_content_digests["manifest_digest"],
        "planner_version": PLANNER_VERSION,
        "chunker_version": CHUNKER_VERSION,
        "embedding_version": MODEL_VERSION,
        "retriever_version": RETRIEVER_VERSION,
        "recommendation_model_name": RECOMMENDATION_MODEL_NAME,
        "recommendation_prompt_version": RECOMMENDATION_PROMPT_VERSION,
        "recommendation_prompt_digest": runtime_content_digests[
            "recommendation_prompt_digest"
        ],
        "benchmark_cases_digest": runtime_content_digests[
            "benchmark_cases_digest"
        ],
        "groundedness_review_digest": canonical_json_digest(review),
    }
    return canonical_json_digest(payload)


__all__ = [
    "DEFAULT_FROZEN_REVIEW_PATH",
    "DEFAULT_MANIFEST_PATH",
    "RELEASE_GATE_VERSION",
    "ReleaseArtifactError",
    "build_release_fingerprint",
    "build_runtime_content_digests",
    "canonical_json_bytes",
    "canonical_json_digest",
    "load_json_object",
    "promote_groundedness_review",
    "validate_groundedness_review",
]
