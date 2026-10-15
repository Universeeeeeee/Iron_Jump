"""Failures found by the frozen real-model instruction benchmark."""
import pytest

from agent.config.agent import LLMConfigAgent
from agent.config.models import LLMTestConfig, LLMTreadmillRunningConfig
from tools.benchmark_config_agent import OUTPUT_TYPES


def test_timed_jump_consensus_ignores_inactive_count():
    agent = LLMConfigAgent("jump")
    candidates = [LLMTestConfig(stop_type="End of Time", test_length="01:30", number_of_jumps=n)
                  for n in (None, 5, None)]
    assert len(agent._cluster_configs(candidates)) == 1
    assert agent._find_disagreements(candidates) == {}
    assert candidates[1].number_of_jumps == 5  # Keep original model evidence.


def test_counted_jump_consensus_ignores_inactive_duration_but_not_count():
    agent = LLMConfigAgent("jump")
    candidates = [LLMTestConfig(number_of_jumps=5, test_length=t) for t in (None, "01:30", None)]
    assert len(agent._cluster_configs(candidates)) == 1
    candidates[2].number_of_jumps = 10
    assert agent._find_disagreements(candidates) == {"number_of_jumps": {5, 10}}


def test_different_stop_modes_still_require_clarification():
    agent = LLMConfigAgent("jump")
    candidates = [LLMTestConfig(), LLMTestConfig(stop_type="End of Time", test_length="01:30")]
    assert len(agent._cluster_configs(candidates)) == 2
    assert "stop_type" in agent._find_disagreements(candidates)


@pytest.mark.parametrize("mode", OUTPUT_TYPES)
def test_current_config_query_includes_test_type_once(mode):
    agent = LLMConfigAgent(mode)
    config = OUTPUT_TYPES[mode]().to_test_config()
    agent._last_config = config
    reply = agent._current_config_query_reply()
    assert reply.count(f"| 测试类型 | {config.test_type} |") == 1


def test_running_prompt_default_agrees_with_schema_and_runtime():
    agent = LLMConfigAgent("treadmill_running")
    model = LLMTreadmillRunningConfig()
    assert model.treadmill_speed == model.to_test_config().treadmill_speed == 6.0
    assert "默认 6.0 km/h" in agent._system_prompt
    assert "默认 3.0 km/h" not in agent._system_prompt
