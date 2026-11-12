"""Synthetic live-DeepSeek benchmark export for manual Groundedness review."""

from __future__ import annotations

import json
from pathlib import Path

from .catalog import DEFAULT_CATALOG_PATH
from .embeddings import LocalEmbeddingModel
from .ingestion import DEFAULT_DATA_DIR
from .models import RecommendationClaim, ReportRAGContext
from .pipeline import DeterministicRAGPipeline
from .retrieval import HybridRetriever
from .store import KnowledgeStore


DEFAULT_REVIEW_PATH = DEFAULT_DATA_DIR / "groundedness_review.json"
LIVE_BENCHMARK_VERSION = "live-generator-groundedness/2.0"

_CASES = (
    (
        "jump",
        "Jump Test",
        "jump_height_m",
        (
            "纵跳高度在已验证分段比较中发生变化。",
            "纵跳高度的稳定性值得复核。",
            "纵跳高度结果需要结合测量限制解释。",
            "纵跳高度变化已由本次测试证据支持。",
            "纵跳高度的后段表现与前段不同。",
        ),
    ),
    (
        "jump",
        "Jump Test",
        "air_time_s",
        (
            "腾空时间在已验证分段比较中发生变化。",
            "腾空时间结果需要复核动作一致性。",
            "腾空时间的测量限制需要说明。",
            "腾空时间变化已由本次测试证据支持。",
            "腾空时间的后段表现与前段不同。",
        ),
    ),
    (
        "walk",
        "Treadmill Gait Test",
        "step_length_cm",
        (
            "步长在已验证比较中发生变化。",
            "步长结果需要复核测试条件。",
            "步长的测量限制需要说明。",
            "步长变化已由本次测试证据支持。",
            "左右步长差异已由测试证据支持。",
        ),
    ),
    (
        "walk",
        "Treadmill Gait Test",
        "cadence_steps_per_min",
        (
            "步频在已验证比较中发生变化。",
            "步频结果需要复核测试条件。",
            "步频的测量限制需要说明。",
            "步频变化已由本次测试证据支持。",
            "步频的后段表现与前段不同。",
        ),
    ),
    (
        "run",
        "Treadmill Running Test",
        "contact_time_s",
        (
            "触地时间在已验证比较中发生变化。",
            "触地时间结果需要复核测试条件。",
            "触地时间的测量限制需要说明。",
            "触地时间变化已由本次测试证据支持。",
            "触地时间的后段表现与前段不同。",
        ),
    ),
    (
        "run",
        "Treadmill Running Test",
        "cadence_steps_per_min",
        (
            "跑步步频在已验证比较中发生变化。",
            "跑步步频结果需要复核测试条件。",
            "跑步步频的测量限制需要说明。",
            "跑步步频变化已由本次测试证据支持。",
            "跑步步频的后段表现与前段不同。",
        ),
    ),
)


def benchmark_contexts() -> tuple[tuple[str, ReportRAGContext], ...]:
    rows = []
    for domain, test_type, metric_code, claims in _CASES:
        for index, claim_text in enumerate(claims, start=1):
            case_id = f"{domain}-{metric_code}-{index:02d}"
            types = ("verified_change", "conditions_review", "measurement_limitation", "verified_change", "temporal_change")
            if metric_code == "jump_height_m":
                types = ("temporal_change", "variability", "measurement_limitation", "verified_change", "temporal_change")
            elif metric_code == "air_time_s":
                types = ("temporal_change", "conditions_review", "measurement_limitation", "verified_change", "temporal_change")
            elif domain == "walk" and metric_code == "step_length_cm":
                types = (*types[:4], "side_difference")
            rows.append(
                (
                    case_id,
                    ReportRAGContext(
                        package_digest=(case_id.encode("utf-8").hex() + "0" * 64)[:64],
                        test_type=test_type,
                        metric_codes=(metric_code,),
                        claims=(
                            RecommendationClaim(
                                claim_id=f"claim-{case_id}",
                                text=claim_text,
                                metric_codes=(metric_code,),
                                finding_type=types[index - 1],
                                data_origin="synthetic_text_only",
                            ),
                        ),
                        population="general",
                    ),
                )
            )
    return tuple(rows)


def run_live_generator_benchmark(
    output_path: Path = DEFAULT_REVIEW_PATH,
    *,
    before_path: Path | None = None,
) -> dict:
    embedder = LocalEmbeddingModel()
    pipeline = DeterministicRAGPipeline(
        HybridRetriever(KnowledgeStore(), embedder),
        manifest_path=DEFAULT_DATA_DIR / "manifest.json",
    )
    rows = []
    for case_id, context in benchmark_contexts():
        result = pipeline.run(context)
        rows.append(
            {
                "case_id": case_id,
                "test_type": context.test_type,
                "claim": context.claims[0].model_dump(mode="json"),
                "context": context.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in result.evidence],
                "recommendations": [
                    item.model_dump(mode="json")
                    for item in result.package.recommendations
                ],
                "citations": [
                    item.model_dump(mode="json") for item in result.package.citations
                ],
                "audit": result.audit.model_dump(mode="json"),
                "groundedness_review": "pending",
                "review_comment": "",
            }
        )
    payload = {
        "benchmark_version": LIVE_BENCHMARK_VERSION,
        "case_count": len(rows),
        "runtime_content_digests": _runtime_content_digests(),
        "review_status": "pending",
        "unsupported_recommendation_count": None,
        "rows": rows,
        "evaluation_mode": "text_only_scenarios; production fact validation required; no fabricated measurements",
    }
    from .review import evaluate_review, write_review_html
    evaluate_review(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_review_html(payload, output_path.with_suffix(".html"), before_path=before_path)
    return payload


def _runtime_content_digests() -> dict[str, str]:
    from .release_artifacts import build_runtime_content_digests

    return build_runtime_content_digests(
        catalog_path=DEFAULT_CATALOG_PATH,
        manifest_path=DEFAULT_DATA_DIR / "manifest.json",
    )
