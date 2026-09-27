"""Frozen retrieval evaluation for the initial sports corpus."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .models import SearchRequest


DEFAULT_EVAL_PATH = Path(__file__).with_name("eval_questions.json")
DEFAULT_BASELINE_PATH = Path(__file__).with_name("retrieval_baseline.json")


class EvalQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    domain: str
    query: str
    expected_source_ids: tuple[str, ...]


def load_questions(path: Path = DEFAULT_EVAL_PATH) -> tuple[EvalQuestion, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(EvalQuestion.model_validate(item) for item in payload["questions"])


def evaluate(retriever, questions: tuple[EvalQuestion, ...] | None = None) -> dict:
    resolved = questions or load_questions()
    rows = []
    reciprocal_ranks = []
    dcgs = []
    recalls_5 = []
    recalls_10 = []
    precisions_5 = []
    domain_hits: dict[str, list[float]] = {}
    for question in resolved:
        hits = retriever.search(
            SearchRequest(query=question.query, max_results=10),
            domain=question.domain,
        )
        ranked_ids = list(
            dict.fromkeys(hit.source.source_id for hit in hits)
        )
        expected = set(question.expected_source_ids)
        first_rank = next(
            (index for index, source_id in enumerate(ranked_ids, start=1) if source_id in expected),
            None,
        )
        recall_5 = len(expected.intersection(ranked_ids[:5])) / len(expected)
        recall_10 = len(expected.intersection(ranked_ids[:10])) / len(expected)
        precision_5 = len(expected.intersection(ranked_ids[:5])) / max(
            1, len(ranked_ids[:5])
        )
        dcg = sum(
            1.0 / math.log2(index + 1)
            for index, source_id in enumerate(ranked_ids[:10], start=1)
            if source_id in expected
        )
        ideal = sum(1.0 / math.log2(index + 1) for index in range(1, min(10, len(expected)) + 1))
        ndcg = dcg / ideal if ideal else 1.0
        reciprocal = 1.0 / first_rank if first_rank else 0.0
        recalls_5.append(recall_5)
        recalls_10.append(recall_10)
        precisions_5.append(precision_5)
        reciprocal_ranks.append(reciprocal)
        dcgs.append(ndcg)
        domain_hits.setdefault(question.domain, []).append(recall_10)
        rows.append(
            {
                "question_id": question.question_id,
                "query": question.query,
                "expected_source_ids": list(question.expected_source_ids),
                "retrieved_source_ids": ranked_ids,
                "recall_at_5": recall_5,
                "recall_at_10": recall_10,
                "precision_at_5": precision_5,
                "reciprocal_rank": reciprocal,
                "ndcg_at_10": ndcg,
            }
        )
    count = len(resolved)
    return {
        "question_count": count,
        "recall_at_5": sum(recalls_5) / count,
        "recall_at_10": sum(recalls_10) / count,
        "precision_at_5": sum(precisions_5) / count,
        "mrr": sum(reciprocal_ranks) / count,
        "ndcg_at_10": sum(dcgs) / count,
        "domain_recall_at_10": {
            domain: sum(values) / len(values) for domain, values in sorted(domain_hits.items())
        },
        "rows": rows,
    }


def validate_against_baseline(
    metrics: dict,
    path: Path = DEFAULT_BASELINE_PATH,
) -> dict:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    regressions = {
        name: {"actual": metrics[name], "baseline": expected}
        for name, expected in baseline["metrics"].items()
        if metrics[name] < expected
    }
    return {
        "passed": not regressions,
        "baseline_version": baseline["baseline_version"],
        "regressions": regressions,
    }


def evaluate_metadata_gates(retriever, specs) -> dict:
    """Evaluate hard filtering and enabled-scenario Evidence coverage."""
    leakage = 0
    forbidden_population_leakage = 0
    covered = 0
    rows = []
    forbidden = {"clinical", "older_adults", "postoperative", "rehabilitation"}
    for spec in specs:
        evidence = retriever.retrieve(spec)
        if evidence:
            covered += 1
        row_leakage = 0
        row_forbidden = 0
        for item in evidence:
            valid = (
                item.domain == spec.domain
                and bool(set(item.metric_codes).intersection(spec.metric_codes))
                and spec.population in item.populations
                and bool(set(item.support_types).intersection(spec.support_types))
                and item.recommendation_allowed == spec.recommendation_allowed
                and (not spec.protocols or item.metadata.get("protocol") in spec.protocols)
            )
            if not valid:
                row_leakage += 1
            if forbidden.intersection(item.populations):
                row_forbidden += 1
        leakage += row_leakage
        forbidden_population_leakage += row_forbidden
        rows.append(
            {
                "query_id": spec.query_id,
                "evidence_count": len(evidence),
                "metadata_leakage": row_leakage,
                "forbidden_population_leakage": row_forbidden,
            }
        )
    count = len(specs)
    return {
        "scenario_count": count,
        "evidence_coverage": covered / count if count else 1.0,
        "metadata_leakage": leakage,
        "forbidden_population_leakage": forbidden_population_leakage,
        "passed": leakage == 0 and forbidden_population_leakage == 0,
        "rows": rows,
    }
