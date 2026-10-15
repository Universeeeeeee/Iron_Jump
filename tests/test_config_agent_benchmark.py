"""Benchmark scoring must detect bad outputs, including transport failures."""
import asyncio
from copy import deepcopy
import json

import pytest

from agent.config.agent import LLMConfigAgent
from agent.config.intent import ModeIntent
from agent.config.models import LLMTestConfig
from tools.benchmark_config_agent import (
    TracedConfigAgent, _RecordedAgent, load_matrix, run_case, score_case, summarize,
)


def case_named(name):
    return next(c for c in load_matrix()["cases"] if c["case_id"] == name)


class Result:
    def __init__(self, output):
        self.output = output

    def all_messages(self):
        return []

    def new_messages_json(self):
        return b'[{"kind":"response"}]'


def configure_jump(_):
    return ModeIntent(action="configure", movement="jump", surface="unknown")


def install_samples(monkeypatch, outputs):
    queue = iter(outputs)
    class FakeAgent:
        async def run(self, *args, **kwargs):
            output = next(queue)
            if isinstance(output, Exception):
                raise output
            return Result(output)
    monkeypatch.setattr(LLMConfigAgent, "_make_agent", staticmethod(lambda *args: FakeAgent()))


def test_matrix_frozen_shape_and_invalid_expectation(tmp_path):
    matrix = load_matrix()
    assert len(matrix["cases"]) == 50
    case = next(c for c in matrix["cases"] if c["case_id"] == "treadmill_running_defaults")
    assert case["expected"]["fields"]["treadmill_speed"] == 6
    matrix["cases"][0]["expected"]["fields"]["nonexistent"] = 10
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(matrix))
    with pytest.raises((ValueError, AttributeError)):
        load_matrix(path)


def test_three_candidates_and_final_config_are_saved(monkeypatch):
    install_samples(monkeypatch, [LLMTestConfig(number_of_jumps=5)] * 3)
    result = run_case(case_named("jump_count"), load_matrix()["profile"], classifier=configure_jump)
    assert result["score"]["passed"]
    assert len(result["samples"]) == 3
    assert [r["sample"] for r in result["samples"]] == [1, 2, 3]
    assert all(r["output"]["number_of_jumps"] == 5 for r in result["samples"])
    assert all(r["messages"] for r in result["samples"])
    assert result["decision"]["label"] == "配置成功"


def test_consensus_disagreement_preserved_as_failed_explicit_request(monkeypatch):
    install_samples(monkeypatch, [LLMTestConfig(number_of_jumps=n) for n in (5, 10, 5)])
    result = run_case(case_named("jump_count"), load_matrix()["profile"], classifier=configure_jump)
    assert result["config"] is None
    assert result["decision"]["label"] == "追问"
    assert not result["score"]["passed"]
    assert [s["output"]["number_of_jumps"] for s in result["samples"]] == [5, 10, 5]


def test_model_failure_is_not_scored_as_valid_rejection(monkeypatch):
    install_samples(monkeypatch, [RuntimeError("network unavailable")] * 3)
    result = run_case(case_named("jump_removed"), load_matrix()["profile"], classifier=configure_jump)
    assert result["status"] == "execution_error"
    assert not result["score"]["passed"]
    summary = summarize([result])
    assert summary["invalid_request_blocked"]["passed"] == 0
    assert summary["execution_errors"] == 1


def test_query_is_local_after_routing_and_reads_frozen_seed(monkeypatch):
    def no_agent(*args):
        pytest.fail("query should not call configuration model")
    monkeypatch.setattr(TracedConfigAgent, "_make_agent", no_agent)
    result = run_case(case_named("jump_query"), load_matrix()["profile"], classifier=lambda _: ModeIntent(
        action="discuss", movement="unknown", surface="unknown"))
    assert result["score"]["passed"]
    assert result["samples"] == []
    assert result["seed"]["number_of_jumps"] == 7


def test_route_clarification_does_not_instantiate_agent():
    def no_agent(*args):
        pytest.fail("ambiguous surface must be resolved before configuring")
    result = run_case(case_named("walking_surface"), load_matrix()["profile"],
                      classifier=lambda _: ModeIntent(action="configure", movement="walk", surface="unknown"),
                      agent_factory=no_agent)
    assert result["score"]["passed"]
    assert result["decision"]["label"] == "模式澄清"


@pytest.mark.parametrize("mutation,failed", [
    ({"number_of_jumps": 6}, "field:number_of_jumps"),
    ({"number_of_jumps": -1}, "runtime_valid"),
    ({"test_type": "Treadmill Gait Test"}, "test_type"),
])
def test_scoring_catches_wrong_fields_and_invalid_runtime(mutation, failed):
    config = LLMTestConfig(number_of_jumps=5).to_test_config().to_dict()
    config.update(mutation)
    result = {"mode": "jump", "status": "ok", "config": config, "reply": "", "samples": []}
    score = score_case(case_named("jump_count"), result)
    assert not score["passed"]
    assert failed in score["failed_checks"]


def test_empty_reply_does_not_pass_clarification():
    result = {"mode": "jump", "status": "ok", "config": None, "reply": "", "samples": []}
    score = score_case(case_named("jump_missing_stop"), result)
    assert not score["passed"]
    assert score["semantic_review"] == "required"


def test_expected_outcome_does_not_change_execution(monkeypatch):
    case = case_named("jump_count")
    install_samples(monkeypatch, [LLMTestConfig(number_of_jumps=5)] * 6)
    original = run_case(case, load_matrix()["profile"], classifier=configure_jump)
    case = deepcopy(case)
    case["expected"]["outcome"] = "query"
    changed = run_case(case, load_matrix()["profile"], classifier=configure_jump)
    assert original["config"] == changed["config"]
    assert len(changed["samples"]) == 3
    assert not changed["score"]["passed"]


def test_request_timeout_is_retained():
    class Slow:
        async def run(self):
            await asyncio.sleep(1)
    records = []
    with pytest.raises(TimeoutError):
        asyncio.run(_RecordedAgent(Slow(), records, .001).run())
    assert records[0]["error_type"] == "TimeoutError"
    assert records[0]["status"] == "error"


def test_latency_excludes_local_queries_and_retains_failure_denominators():
    rows = []
    for name, elapsed, status in [("jump_query", 1000, "ok"), ("jump_count", 2, "execution_error"), ("jump_time", 4, "ok")]:
        case = case_named(name)
        rows.append(dict(expected=case["expected"], elapsed_s=elapsed, status=status, config=None, score={"passed": False}))
    result = summarize(rows)
    assert result["non_query_latency_s"] == {"count": 2, "p50": 2, "p95": 4}
    assert result["config_success"]["total"] == 2
