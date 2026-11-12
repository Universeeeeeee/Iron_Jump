"""Command-line entry points for the standalone RAG vertical slice."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import load_catalog
from .benchmark import benchmark_chunk_grid
from .citations import format_search_output, render_cited_answer
from .embeddings import LocalEmbeddingModel
from .evaluation import evaluate, validate_against_baseline
from .ingestion import build_chunk_snapshot, download_core_corpus, load_chunk_snapshot
from .models import CitationBinding, SearchRequest
from .live_benchmark import run_live_generator_benchmark
from .retrieval import HybridRetriever
from .store import KnowledgeStore


def _retriever() -> HybridRetriever:
    embedder = LocalEmbeddingModel()
    return HybridRetriever(KnowledgeStore(), embedder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Iron_Jump local sports RAG")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("catalog")
    subparsers.add_parser("download")
    chunk_parser = subparsers.add_parser("chunk")
    chunk_parser.add_argument("--target-tokens", type=int, default=350)
    chunk_parser.add_argument("--overlap-tokens", type=int, default=60)
    subparsers.add_parser("build")
    inspect_parser = subparsers.add_parser("inspect-chunks")
    inspect_parser.add_argument("--source-id")
    inspect_parser.add_argument("--domain", choices=("jump", "walk", "run", "general"))
    inspect_parser.add_argument("--metric-code")
    inspect_parser.add_argument("--support-type")
    inspect_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    subparsers.add_parser("benchmark-chunks")
    live_parser = subparsers.add_parser("benchmark-generator-live")
    live_parser.add_argument("--output", type=Path)
    live_parser.add_argument("--before", type=Path)
    replay_parser = subparsers.add_parser("review-generator-replay")
    replay_parser.add_argument("--source", type=Path, required=True)
    replay_parser.add_argument("--output", type=Path, required=True)
    replay_parser.add_argument("--before", type=Path)
    for name in ("search", "answer"):
        command = subparsers.add_parser(name)
        command.add_argument("query")
        command.add_argument("--domain", choices=("jump", "walk", "run"))
        command.add_argument("--max-results", type=int, default=6)
    subparsers.add_parser("evaluate")
    args = parser.parse_args(argv)

    if args.command == "catalog":
        for source in load_catalog():
            print(f"{source.source_id}\t{source.ingest_policy}\t{source.title}\t{source.url}")
        return 0
    if args.command == "download":
        for path in download_core_corpus():
            print(path)
        return 0
    if args.command == "chunk":
        chunks = build_chunk_snapshot(
            target_tokens=args.target_tokens,
            overlap_tokens=args.overlap_tokens,
        )
        print(f"chunks={len(chunks)}")
        return 0
    if args.command == "build":
        store = KnowledgeStore()
        count = store.build(LocalEmbeddingModel())
        print(f"indexed_chunks={count} embedded={store.last_build_stats['embedded_count']}")
        return 0
    if args.command == "inspect-chunks":
        chunks = load_chunk_snapshot()
        selected = [
            chunk
            for chunk in chunks
            if (not args.source_id or chunk.source_id == args.source_id)
            and (not args.domain or chunk.domain == args.domain)
            and (not args.metric_code or args.metric_code in chunk.metric_codes)
            and (not args.support_type or args.support_type in chunk.support_types)
        ]
        if args.format == "json":
            print(json.dumps([item.model_dump(mode="json") for item in selected], ensure_ascii=False, indent=2))
        else:
            for item in selected:
                print(f"## {item.source_id} — {item.locator}\n\n{item.text}\n")
        return 0
    if args.command == "benchmark-chunks":
        print(json.dumps(benchmark_chunk_grid(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark-generator-live":
        options = {"before_path": args.before}
        if args.output:
            options["output_path"] = args.output
        payload = run_live_generator_benchmark(**options)
        print(
            f"cases={payload['case_count']} review_status={payload['review_status']}"
        )
        return 0
    if args.command == "review-generator-replay":
        from .review import replay_review
        payload = replay_review(args.source, args.output, before_path=args.before)
        print(json.dumps(payload["quality_summary"], ensure_ascii=False))
        return 0 if payload["quality_summary"]["complete_30_case_coverage"] and all(row["quality_checks"]["status"] in {"automated_checks_passed", "supported_abstention", "scenario_only_not_production_validated"}
                        for row in payload["rows"]) else 1
    if args.command == "evaluate":
        metrics = evaluate(_retriever())
        metrics["baseline"] = validate_against_baseline(metrics)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return 0

    request = SearchRequest(query=args.query, max_results=args.max_results)
    retriever = _retriever()
    hits = retriever.search(request, domain=args.domain)
    if args.command == "search":
        print(format_search_output(retriever.model_result(request, hits)))
        return 0
    bindings = tuple(
        CitationBinding(
            binding_id=f"cite-{index}",
            chunk_id=hit.chunk.chunk_id,
            support_type="background",
        )
        for index, hit in enumerate(hits, start=1)
    )
    answer = "检索到以下可用于解释该问题的权威资料片段：\n\n" + "\n".join(
        f"- {hit.chunk.locator}：{hit.chunk.text[:220].strip()}" for hit in hits
    )
    print(render_cited_answer(answer, bindings, hits))
    return 0
