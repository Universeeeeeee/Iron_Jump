import json

import pytest

from knowledge.planner import PLANNER_VERSION
from knowledge.retrieval import RETRIEVER_VERSION

from knowledge.live_benchmark import (
    LIVE_BENCHMARK_VERSION,
    benchmark_contexts,
)
from knowledge.release_artifacts import (
    RELEASE_GATE_VERSION,
    ReleaseArtifactError,
    build_release_fingerprint,
    build_runtime_content_digests,
    promote_groundedness_review,
)
from knowledge.release_gate import (
    RELEASE_GATE_DISABLED,
    RELEASE_GATE_INVALID,
    v1_release_enabled,
    v1_release_status,
)


def _review(
    runtime_content_digests,
    *,
    status="passed",
    unsupported=0,
    row_status="supported",
):
    audit = {
        "corpus_version": "fixture-corpus/1",
        "planner_version": PLANNER_VERSION,
        "chunker_version": "chunker/2.2",
        "embedding_version": "paraphrase-multilingual-MiniLM-L12-v2/fastembed-onnx",
        "retriever_version": RETRIEVER_VERSION,
        "prompt_version": "sports-recommendation/1.0",
        "model_name": "deepseek-v4-flash",
    }
    rows = [
        {
            "case_id": case_id,
            "audit": audit,
            "groundedness_review": row_status,
            "review_comment": "reviewed",
        }
        for case_id, _ in benchmark_contexts()
    ]
    return {
        "benchmark_version": LIVE_BENCHMARK_VERSION,
        "case_count": len(rows),
        "runtime_content_digests": runtime_content_digests,
        "review_status": status,
        "unsupported_recommendation_count": unsupported,
        "rows": rows,
    }


def _write_release_fixture(tmp_path):
    catalog = tmp_path / "sources.json"
    manifest = tmp_path / "manifest.json"
    review = tmp_path / "review.json"
    catalog.write_text(json.dumps({"sources": []}), encoding="utf-8")
    manifest.write_text(
        json.dumps({"corpus_version": "fixture-corpus/1"}),
        encoding="utf-8",
    )
    content_digests = build_runtime_content_digests(
        catalog_path=catalog,
        manifest_path=manifest,
    )
    review.write_text(
        json.dumps(_review(content_digests)), encoding="utf-8"
    )
    fingerprint = build_release_fingerprint(
        catalog_path=catalog,
        manifest_path=manifest,
        review_path=review,
    )
    gate = tmp_path / "gate.json"
    gate.write_text(
        json.dumps(
            {
                "gate_version": RELEASE_GATE_VERSION,
                "enabled": True,
                "retrieval_baseline_passed": True,
                "metadata_gates_passed": True,
                "automated_generator_e2e_passed": True,
                "human_groundedness_review_passed": True,
                "review_artifact": "review.json",
                "release_fingerprint": fingerprint,
            }
        ),
        encoding="utf-8",
    )
    return gate, catalog, manifest, review


def test_release_gate_requires_frozen_matching_review(tmp_path):
    gate, catalog, manifest, review = _write_release_fixture(tmp_path)

    assert v1_release_enabled(
        gate,
        catalog_path=catalog,
        manifest_path=manifest,
        review_path=review,
    ) is True

    original = review.read_text(encoding="utf-8")
    stale = json.loads(original)
    for row in stale["rows"]:
        row["audit"]["planner_version"] = "deterministic-query-planner/1.0"
    review.write_text(json.dumps(stale), encoding="utf-8")
    assert v1_release_status(gate, catalog_path=catalog, manifest_path=manifest,
                             review_path=review) == RELEASE_GATE_INVALID
    review.write_text(original, encoding="utf-8")

    manifest.write_text(
        json.dumps({"corpus_version": "fixture-corpus/2"}),
        encoding="utf-8",
    )
    assert v1_release_enabled(
        gate,
        catalog_path=catalog,
        manifest_path=manifest,
        review_path=review,
    ) is False


@pytest.mark.parametrize("payload", ([], None, "enabled"))
def test_release_gate_non_object_json_is_disabled(tmp_path, payload):
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps(payload), encoding="utf-8")

    assert v1_release_enabled(gate) is False
    assert v1_release_status(gate) == RELEASE_GATE_INVALID


def test_release_gate_missing_file_and_pending_review_are_disabled(tmp_path):
    assert v1_release_enabled(tmp_path / "missing.json") is False
    assert v1_release_status(tmp_path / "missing.json") == RELEASE_GATE_INVALID
    gate, catalog, manifest, review = _write_release_fixture(tmp_path)
    content_digests = build_runtime_content_digests(
        catalog_path=catalog,
        manifest_path=manifest,
    )
    review.write_text(
        json.dumps(
            _review(
                content_digests,
                status="pending",
                row_status="pending",
            )
        ),
        encoding="utf-8",
    )

    assert v1_release_enabled(
        gate,
        catalog_path=catalog,
        manifest_path=manifest,
        review_path=review,
    ) is False


def test_promotion_requires_complete_consistent_human_review(tmp_path):
    catalog = tmp_path / "sources.json"
    manifest = tmp_path / "manifest.json"
    source = tmp_path / "local-review.json"
    destination = tmp_path / "release" / "review.json"
    catalog.write_text(json.dumps({"sources": []}), encoding="utf-8")
    manifest.write_text(
        json.dumps({"corpus_version": "fixture-corpus/1"}),
        encoding="utf-8",
    )
    content_digests = build_runtime_content_digests(
        catalog_path=catalog,
        manifest_path=manifest,
    )
    source.write_text(
        json.dumps(_review(content_digests)), encoding="utf-8"
    )

    promoted = promote_groundedness_review(
        source,
        destination,
        catalog_path=catalog,
        manifest_path=manifest,
    )

    assert promoted["review_status"] == "passed"
    assert destination.exists()
    assert json.loads(destination.read_text(encoding="utf-8")) == promoted

    source.write_text(
        json.dumps(_review(content_digests, row_status="pending")),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseArtifactError):
        promote_groundedness_review(
            source,
            destination,
            catalog_path=catalog,
            manifest_path=manifest,
        )


def test_promotion_rejects_incomplete_case_set_and_content_drift(tmp_path):
    catalog = tmp_path / "sources.json"
    manifest = tmp_path / "manifest.json"
    source = tmp_path / "local-review.json"
    destination = tmp_path / "release" / "review.json"
    catalog.write_text(json.dumps({"sources": []}), encoding="utf-8")
    manifest.write_text(
        json.dumps({"corpus_version": "fixture-corpus/1"}),
        encoding="utf-8",
    )
    content_digests = build_runtime_content_digests(
        catalog_path=catalog,
        manifest_path=manifest,
    )
    incomplete = _review(content_digests)
    incomplete["rows"] = incomplete["rows"][:1]
    incomplete["case_count"] = 1
    source.write_text(json.dumps(incomplete), encoding="utf-8")

    with pytest.raises(ReleaseArtifactError):
        promote_groundedness_review(
            source,
            destination,
            catalog_path=catalog,
            manifest_path=manifest,
        )

    source.write_text(
        json.dumps(_review(content_digests)), encoding="utf-8"
    )
    catalog.write_text(
        json.dumps({"sources": [{"source_id": "changed"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseArtifactError):
        promote_groundedness_review(
            source,
            destination,
            catalog_path=catalog,
            manifest_path=manifest,
        )


def test_release_gate_distinguishes_configured_off_from_invalid_enabled(tmp_path):
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps({"enabled": False}), encoding="utf-8")

    assert v1_release_status(gate) == RELEASE_GATE_DISABLED

    gate.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    assert v1_release_status(gate) == RELEASE_GATE_INVALID
