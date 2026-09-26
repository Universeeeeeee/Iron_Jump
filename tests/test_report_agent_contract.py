"""Static contracts for the single logical Report Agent."""

from agent.report.agent import ReportAgent
from agent.report.prompts import (
    DECISION_STAGE_TEMPLATE,
    SEQUENTIAL_PROMPT_VERSION,
    load_sequential_system_prompt,
    load_system_prompt,
    prompt_content_digest,
)
from agent.report.skill_loader import ReportAnalysisSkillLoader
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    SequentialAnalysisState,
    StopAnalysis,
)


def test_analysis_question_schema_has_no_permission_field():
    properties = AnalysisQuestion.model_json_schema()["properties"]
    assert "required_scope" not in properties
    assert "required_permission" not in properties


def test_analysis_node_schema_exposes_tool_and_method_but_no_permission_or_versions():
    properties = AnalysisNode.model_json_schema()["properties"]

    assert {"tool_name", "analysis_method"} <= properties.keys()
    assert not {
        "data_scope",
        "required_scope",
        "tool_version",
        "analysis_method_version",
        "kernel_version",
    }.intersection(properties)


def test_report_agent_prompt_declares_scope_evidence_and_safety_boundaries():
    prompt = load_system_prompt()
    for expected in (
        "Screening Cue",
        "NumericBinding",
        "required_scope",
        "tool_name",
        "analysis_method",
        "不得自行构造分析工具",
        "最多提出 3 个",
        "co_change",
        "医学诊断",
        "因果",
    ):
        assert expected in prompt


def test_constructing_report_agent_does_not_make_network_request(monkeypatch):
    called = False

    def fail(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network/model construction during initialization")

    monkeypatch.setattr("agent.report.agent.build_chat_model", fail)
    ReportAgent()
    assert called is False


def test_builtin_agent_uses_readable_content_bound_prompt_identity():
    agent = ReportAgent()

    assert agent.sequential_prompt_version.startswith(
        SEQUENTIAL_PROMPT_VERSION + "#"
    )
    assert len(agent.sequential_prompt_version.rsplit("#", 1)[1]) == 12
    assert len(agent.sequential_prompt_content_digest) == 64
    assert prompt_content_digest(
        DECISION_STAGE_TEMPLATE, "changed"
    ) != prompt_content_digest(DECISION_STAGE_TEMPLATE, "original")


def test_sequential_prompt_requires_one_typed_decision_and_no_permission_fields():
    prompt = load_sequential_system_prompt()

    for expected in (
        "NextAnalysisAction",
        "LoadSkillResource",
        "StopAnalysis",
        "每轮只验证一个假设",
        "不得输出Plan",
        "inconclusive",
        "Tool失败也不构成否定Evidence",
    ):
        assert expected in prompt
    assert SEQUENTIAL_PROMPT_VERSION == "report-agent-sequential-system/3.0"


def test_decide_includes_progressive_skill_and_uses_sequential_instructions(
    monkeypatch,
):
    class _Observation:
        def model_dump(self, mode):
            return {"report_context": {"test_type": "Jump Test"}}

    agent = ReportAgent()
    context = ReportAnalysisSkillLoader().load_initial("Jump Test")
    captured = {}
    expected = StopAnalysis(
        reason_code="no_high_value_hypothesis",
        reason="没有值得继续验证的假设",
    )

    def fake_run(output_type, prompt, *, instructions=None, **kwargs):
        captured["prompt"] = prompt
        captured["instructions"] = instructions
        return expected

    monkeypatch.setattr(agent, "_run", fake_run)

    decision = agent.decide(
        _Observation(),
        SequentialAnalysisState(
            loaded_skill_references=("references/jump.md",)
        ),
        (),
        context,
    )

    assert decision is expected
    assert "# Skill Resource: SKILL.md" in captured["prompt"]
    assert "# Skill Resource: references/jump.md" in captured["prompt"]
    assert "Treadmill Gait Analysis Prior" not in captured["prompt"]
    assert captured["instructions"] == load_sequential_system_prompt()


def test_sequential_synthesis_receives_loaded_evidence_guidelines(monkeypatch):
    class _Observation:
        def model_dump(self, mode):
            return {"report_context": {"test_type": "Jump Test"}}

    agent = ReportAgent()
    loader = ReportAnalysisSkillLoader()
    context = loader.load_reference(
        loader.load_initial("Jump Test"),
        "references/evidence-guidelines.md",
    )
    captured = {}

    def fake_run(output_type, prompt, *, instructions=None, **kwargs):
        captured["prompt"] = prompt
        return object()

    monkeypatch.setattr(agent, "_run", fake_run)
    agent.synthesize_sequential(
        _Observation(),
        SequentialAnalysisState(
            loaded_skill_references=context.loaded_reference_ids
        ),
        (),
        context,
    )

    assert "# Skill Resource: references/evidence-guidelines.md" in captured[
        "prompt"
    ]
