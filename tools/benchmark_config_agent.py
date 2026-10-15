"""Evaluate the frozen instruction matrix through the non-streaming config path.

Run with ``python -m tools.benchmark_config_agent --online --output RESULT.json``.
Without --online only validate the matrix; no credentials or network are used.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import subprocess
import time

from agent.config.agent import LLMConfigAgent
from agent.config import intent
from agent.config.models import (
    AthleteProfile, LLMTestConfig, LLMTreadmillGaitConfig,
    LLMTreadmillRunningConfig, LLMWalkingConfig, LLMOvergroundRunningConfig,
)
from agent.config.modes import MODE_TEST_TYPES
from config.config_validation import validate_runtime_config
from config.test_config import config_from_dict


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "tests/fixtures/config_agent/instructions_v1.json"
OUTPUT_TYPES = dict(zip(MODE_TEST_TYPES, (
    LLMTestConfig, LLMTreadmillGaitConfig, LLMTreadmillRunningConfig,
    LLMWalkingConfig, LLMOvergroundRunningConfig,
)))


def load_matrix(path=MATRIX):
    matrix = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = matrix["cases"]
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id")
    if Counter(case["mode"] for case in cases) != Counter({mode: 10 for mode in MODE_TEST_TYPES}):
        raise ValueError("matrix must contain ten cases per mode")
    for case in cases:
        expected = case["expected"]
        if expected["outcome"] not in {"config", "clarify", "reject", "query"}:
            raise ValueError(f"unknown outcome: {case['case_id']}")
        if case.get("initial_mode", case["mode"]) not in MODE_TEST_TYPES or expected["mode"] not in MODE_TEST_TYPES:
            raise ValueError(f"unknown mode: {case['case_id']}")
        if expected["outcome"] == "config":
            model = OUTPUT_TYPES[expected["mode"]](**expected["fields"])
            config = model.to_test_config()
            if validate_runtime_config(config):
                raise ValueError(f"invalid expected config: {case['case_id']}")
            for key, value in expected["fields"].items():
                if getattr(config, key) != value:
                    raise ValueError(f"invalid expected field: {case['case_id']}/{key}")
        elif not expected["reply_groups"]:
            raise ValueError(f"reply checks required: {case['case_id']}")
    return matrix


class _RecordedAgent:
    def __init__(self, agent, records, timeout_s):
        self.agent, self.records, self.timeout_s = agent, records, timeout_s

    async def run(self, *args, **kwargs):
        record = {"sample": len(self.records) + 1, "status": "running"}
        self.records.append(record)
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(self.agent.run(*args, **kwargs), self.timeout_s)
            record.update(status="ok", output_type=type(result.output).__name__,
                          output=result.output.model_dump(mode="json"))
            # Includes structural repair attempts, without storing provider settings.
            record["messages"] = json.loads(result.new_messages_json())
            return result
        except Exception as exc:
            record.update(status="error", error_type=type(exc).__name__)
            raise
        finally:
            record["elapsed_s"] = time.perf_counter() - started


class TracedConfigAgent(LLMConfigAgent):
    def __init__(self, mode, timeout_s=60):
        super().__init__(mode)
        self.samples = []
        self.decision = None
        self.timeout_s = timeout_s

    def _make_agent(self, http_client, mode="jump"):
        return _RecordedAgent(super()._make_agent(http_client, mode), self.samples, self.timeout_s)

    def _finalize(self, config, message, t_start, timing, label, stream_callback=None):
        self.decision = {"label": label, "timing": list(timing)}
        return super()._finalize(config, message, t_start, timing, label, stream_callback)


def score_case(case, result):
    expected = case["expected"]
    config = result.get("config")
    checks = {"no_execution_error": result["status"] == "ok",
              "mode": result["mode"] == expected["mode"]}
    checks["config_presence"] = (config is not None) == (expected["outcome"] == "config")
    if config is not None:
        try:
            checks["runtime_valid"] = not validate_runtime_config(config_from_dict(config))
        except (ValueError, TypeError, KeyError):
            checks["runtime_valid"] = False
        checks["test_type"] = config.get("test_type") == MODE_TEST_TYPES[expected["mode"]]
    for field, value in expected["fields"].items():
        checks[f"field:{field}"] = config is not None and config.get(field) == value
    for index, alternatives in enumerate(expected["reply_groups"]):
        checks[f"reply_group:{index}"] = any(word.casefold() in result.get("reply", "").casefold() for word in alternatives)
    if expected["outcome"] == "query":
        checks["local_query"] = not result["samples"] and result.get("decision", {}).get("label") == "当前配置查询"
    return {"passed": all(checks.values()), "checks": checks,
            "failed_checks": [key for key, value in checks.items() if not value],
            "semantic_review": "required" if expected["outcome"] in {"clarify", "reject"} else "not_applicable"}


def run_case(case, profile, *, classifier=None, agent_factory=TracedConfigAgent, timeout_s=60):
    classifier = classifier or intent.classify
    started = time.perf_counter()
    mode = case.get("initial_mode", case["mode"])
    result = {"case_id": case["case_id"], "category": case["category"],
              "message": case["message"], "expected": case["expected"],
              "mode": mode, "status": "ok", "config": None, "samples": [], "reply": ""}
    try:
        # Same classifier and deterministic routing as Worker route_intent.
        # Expected answers never decide which production path to execute.
        route_started = time.perf_counter()
        classified = classifier(case["message"])
        result["intent"] = classified.model_dump(mode="json")
        routing = intent.resolve(classified, mode, None, case["message"])
        result["routing"] = routing
        result["routing_elapsed_s"] = time.perf_counter() - route_started
        result["mode"] = mode = routing["mode"]
        if "message" not in routing:
            result["reply"] = routing["reply"]
            result["decision"] = {"label": "模式澄清"}
            return _finish_case(case, result, started)
        agent = agent_factory(mode, timeout_s)
        result["samples"] = agent.samples
        if "seed" in case:
            seed = OUTPUT_TYPES[mode](**case["seed"]).to_test_config()
            agent._last_config = seed
            result["seed"] = seed.to_dict()
        with redirect_stdout(io.StringIO()):
            config, reply = agent.chat(routing["message"], AthleteProfile(**profile))
        result.update(config=config.to_dict() if config is not None else None,
                      reply=reply, decision=agent.decision or {})
        if reply.startswith("配置生成失败:") or (config is None and any(s["status"] == "error" for s in agent.samples)):
            result["status"] = "execution_error"
    except Exception as exc:
        result.update(status="execution_error", error_type=type(exc).__name__)
    return _finish_case(case, result, started)


def _finish_case(case, result, started):
    result["elapsed_s"] = time.perf_counter() - started
    result["score"] = score_case(case, result)
    return result


def summarize(results):
    def rate(items, predicate):
        passed = sum(bool(predicate(item)) for item in items)
        return {"passed": passed, "total": len(items), "rate": passed / len(items) if items else None}

    config = [item for item in results if item["expected"]["outcome"] == "config"]
    clarify = [item for item in results if item["expected"]["outcome"] == "clarify"]
    reject = [item for item in results if item["expected"]["outcome"] == "reject"]
    elapsed = sorted(item["elapsed_s"] for item in results if item["expected"]["outcome"] != "query")
    return {
        "cases_completed": len(results),
        "automated_checks": rate(results, lambda r: r["score"]["passed"]),
        "config_success": rate(config, lambda r: r["status"] == "ok" and r["config"] is not None),
        "key_fields_exact": rate(config, lambda r: r["score"]["passed"]),
        "unnecessary_nonconfig": rate(config, lambda r: r["status"] == "ok" and r["config"] is None),
        "required_clarification_checks": rate(clarify, lambda r: r["score"]["passed"]),
        "invalid_request_blocked": rate(reject, lambda r: r["status"] == "ok" and r["config"] is None),
        "rejection_reply_checks": rate(reject, lambda r: r["score"]["passed"]),
        "execution_errors": sum(r["status"] != "ok" for r in results),
        "non_query_latency_s": {"count": len(elapsed), **{
            f"p{q}": elapsed[math.ceil(len(elapsed) * q / 100) - 1] if elapsed else None for q in (50, 95)}},
        "semantic_review": "pending",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--request-timeout", type=float, default=60)
    args = parser.parse_args()
    matrix = load_matrix()
    selected = [case for case in matrix["cases"] if not args.case or case["case_id"] in args.case]
    if set(args.case) - {case["case_id"] for case in selected}:
        parser.error("unknown case id")
    if not args.online:
        print(json.dumps({"status": "matrix_valid", "cases": len(matrix["cases"]), "selected": len(selected)}, ensure_ascii=False))
        return
    if not args.output or args.output.exists() or args.request_timeout <= 0:
        parser.error("--online requires a new --output path and positive timeout")
    from agent.common.model_provider import load_model_provider_settings
    settings = load_model_provider_settings()
    sources = sorted((ROOT / "agent/config").rglob("*.py")) + sorted((ROOT / "agent/config/prompts").glob("*.md"))
    sources += [ROOT / name for name in ("agent/worker.py", "agent/common/model_provider.py", "config/config_validation.py", "tools/benchmark_config_agent.py")]
    audit = {"schema_version": "config-agent-benchmark/1.0", "kind": "real_model",
             "started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
             "platform": platform.platform(), "python": platform.python_version(),
             "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             "model": settings.model_name, "request_timeout_s": args.request_timeout,
             "matrix_sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest(),
             "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
             "matrix": matrix, "selected_case_ids": [case["case_id"] for case in selected], "results": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        audit["summary"] = summarize(audit["results"])
        args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save()
    for case in selected:
        result = run_case(case, matrix["profile"], timeout_s=args.request_timeout)
        audit["results"].append(result)
        save()
        print(f"{case['case_id']}: {result['status']} passed={result['score']['passed']} {result['elapsed_s']:.2f}s", flush=True)
    audit["status"] = "completed"
    audit["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()


if __name__ == "__main__":
    main()
