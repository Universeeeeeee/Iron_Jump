"""Sequential loop tests with a deterministic Fake Agent only."""

from pathlib import Path

import pytest

from agent.report.execution import SequentialActionBoundary
from agent.report.sequential_loop import (
    SequentialAnalysisLoop,
    SequentialAnalysisLoopError,
)
from agent.report.skill_loader import ReportAnalysisSkillLoader
from agent.report.tools import AnalysisToolGateway, TransientAnalysisToolError
from reporting.builders import ReportManifestBuilder
from reporting.kernel import AnalysisMethodRegistry
from reporting.models import (
    DataAccessScope,
    DataScopeAvailability,
    DraftAnalysisPackage,
    HypothesisTarget,
    LoadSkillResource,
    NextAnalysisAction,
    StopAnalysis,
)
from reporting.observation import ObservationBuilder
from reporting.tools import AnalysisToolRegistry
from reporting.validators import ActionValidator
from tests.reporting_fixtures import make_jump_package


SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / "agent"
    / "report"
    / "skills"
    / "report-analysis"
)


def _observation(package):
    scope = DataAccessScope()
    return ObservationBuilder().build(
        package,
        ReportManifestBuilder().build(package),
        DataScopeAvailability(),
        scope,
        AnalysisToolRegistry().list_capabilities(
            package, scope, AnalysisMethodRegistry()
        ),
    )


def _action(
    package,
    *,
    action_id="a1",
    hypothesis_id="h1",
    metric_code="contact_time_s",
    tool_name="analyze_current_session",
):
    return NextAnalysisAction(
        action_id=action_id,
        hypothesis=HypothesisTarget(
            hypothesis_id=hypothesis_id,
            statement=f"{metric_code}是否增加",
            dimensions=("temporal",),
            metric_codes=(metric_code,),
            target_predicate="increase",
            reason="观察到候选变化",
            success_condition="获得方向证据",
        ),
        tool_name=tool_name,
        analysis_method="verify_temporal_change",
        inputs={
            "record_set_id": package.record_sets[0].record_set_id,
            "metric_codes": [metric_code],
        },
        purpose="验证时序变化",
    )


def _stop():
    return StopAnalysis(
        reason_code="evidence_sufficient",
        reason="已有足够证据",
    )


class _FakeSequentialAgent:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.context_references = []
        self.synthesize_calls = 0

    def decide(self, observation, state, evidence, skill_context):
        self.context_references.append(skill_context.loaded_reference_ids)
        return self.decisions.pop(0)

    def synthesize(self, observation, state, evidence):
        self.synthesize_calls += 1
        return DraftAnalysisPackage(summary="draft", claims=())


class _ContextAwareSynthesisAgent(_FakeSequentialAgent):
    def __init__(self, decisions):
        super().__init__(decisions)
        self.synthesis_references = None

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        self.synthesize_calls += 1
        self.synthesis_references = skill_context.loaded_reference_ids
        return DraftAnalysisPackage(summary="draft", claims=())


class _HardFailureGateway:
    def __init__(self):
        self.calls = 0

    def execute_action(self, package, action, access_scope):
        self.calls += 1
        raise RuntimeError("kernel defect")


class _ScriptedGateway:
    def __init__(self, effects):
        self.effects = list(effects)
        self.calls = 0

    def execute_action(self, package, action, access_scope):
        self.calls += 1
        effect = self.effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect


class _CheckpointSink:
    def __init__(self, crash_phase=None):
        self.crash_phase = crash_phase
        self.checkpoints = []

    def save(self, checkpoint):
        self.checkpoints.append(checkpoint)
        if checkpoint.phase == self.crash_phase:
            self.crash_phase = None
            raise RuntimeError("simulated process interruption")


def _loop(agent, **kwargs):
    return SequentialAnalysisLoop(
        agent,
        skill_loader=ReportAnalysisSkillLoader(SKILL_PATH),
        **kwargs,
    )


def test_loop_progressively_loads_skill_and_tests_multiple_hypotheses():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeSequentialAgent(
        [
            _action(package),
            LoadSkillResource(
                reference_id="references/evidence-guidelines.md",
                reason="需要形成受约束结论",
            ),
            _action(
                package,
                action_id="a2",
                hypothesis_id="h2",
                metric_code="air_time_s",
            ),
            _stop(),
        ]
    )

    result = _loop(agent).run(
        _observation(package), package, DataAccessScope()
    )

    assert result.state.decision_count == 4
    assert result.state.tool_call_count == 2
    assert tuple(item.status for item in result.state.hypotheses) == (
        "supported",
        "not_supported",
    )
    assert result.state.loaded_skill_references == (
        "references/jump.md",
        "references/evidence-guidelines.md",
    )
    assert len(result.evidence) == 2
    assert len(result.skill_content_digest) == 64
    assert agent.context_references[0] == ("references/jump.md",)
    assert agent.context_references[2] == (
        "references/jump.md",
        "references/evidence-guidelines.md",
    )
    assert agent.synthesize_calls == 1


def test_system_loads_evidence_guidelines_before_synthesis_without_agent_decision():
    package = make_jump_package([0.2] * 12)
    agent = _ContextAwareSynthesisAgent([_stop()])

    result = _loop(agent).run(
        _observation(package), package, DataAccessScope()
    )

    assert result.state.decision_count == 1
    assert agent.synthesis_references == (
        "references/jump.md",
        "references/evidence-guidelines.md",
    )
    assert result.state.loaded_skill_references == agent.synthesis_references


def test_invalid_action_can_be_corrected_without_consuming_tool_budget():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeSequentialAgent(
        [
            _action(package, tool_name="compare_cohort"),
            _action(package, action_id="a2", hypothesis_id="h2"),
            _stop(),
        ]
    )

    result = _loop(agent).run(
        _observation(package), package, DataAccessScope()
    )

    assert result.state.action_correction_count == 1
    assert result.state.tool_call_count == 1
    assert result.state.failures[0].error_code == "tool_disabled"
    assert result.state.hypotheses[0].status == "supported"


def test_inconclusive_evidence_is_a_valid_hypothesis_result():
    package = make_jump_package([0.20, 0.21, 0.30, 0.31])
    agent = _FakeSequentialAgent([_action(package), _stop()])

    result = _loop(agent).run(
        _observation(package), package, DataAccessScope()
    )

    assert result.state.hypotheses[0].status == "inconclusive"
    assert result.state.rejected_predicates == ()
    assert len(result.evidence) == 1


def test_hard_tool_failure_stops_atomically_without_synthesis():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    agent = _FakeSequentialAgent([_action(package)])
    gateway = _HardFailureGateway()
    boundary = SequentialActionBoundary(tool_gateway=gateway)

    with pytest.raises(SequentialAnalysisLoopError) as exc_info:
        _loop(agent, action_boundary=boundary).run(
            _observation(package), package, DataAccessScope()
        )

    error = exc_info.value
    assert error.code == "tool_execution_failed"
    assert error.state.stop_reason_code == "hard_tool_failure"
    assert error.state.hypotheses[0].status == "active"
    assert error.state.rejected_predicates == ()
    assert gateway.calls == 1
    assert agent.synthesize_calls == 0


def test_transient_tool_failure_recovers_once_and_records_retry():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package)
    validated = ActionValidator().validate_action(
        action, package, DataAccessScope()
    )
    bundle = AnalysisToolGateway().execute_action(
        package, validated, DataAccessScope()
    )
    gateway = _ScriptedGateway(
        [TransientAnalysisToolError("temporary lock"), bundle]
    )
    agent = _FakeSequentialAgent([action, _stop()])

    result = _loop(
        agent,
        action_boundary=SequentialActionBoundary(tool_gateway=gateway),
    ).run(_observation(package), package, DataAccessScope())

    assert gateway.calls == 2
    assert result.state.tool_call_count == 1
    assert result.state.tool_retry_count == 1
    assert result.state.hypotheses[0].status == "supported"


def test_five_tool_call_budget_allows_stop_but_no_extra_analysis():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    metrics = (
        "contact_time_s",
        "air_time_s",
        "jump_height_m",
        "cycle_time_s",
        "cadence_jumps_per_min",
    )
    decisions = [
        _action(
            package,
            action_id=f"a{index}",
            hypothesis_id=f"h{index}",
            metric_code=metric,
        )
        for index, metric in enumerate(metrics, start=1)
    ]
    agent = _FakeSequentialAgent([*decisions, _stop()])

    result = _loop(agent).run(
        _observation(package), package, DataAccessScope()
    )

    assert result.state.tool_call_count == 5
    assert result.state.decision_count == 6
    assert len(result.evidence) == 5
    assert result.state.stop_reason_code == "evidence_sufficient"


def test_action_correction_limit_stops_without_tool_or_partial_draft():
    package = make_jump_package([0.2] * 12)
    invalid = _action(package, tool_name="compare_cohort")
    agent = _FakeSequentialAgent([invalid, invalid, invalid])

    with pytest.raises(SequentialAnalysisLoopError) as exc_info:
        _loop(agent).run(_observation(package), package, DataAccessScope())

    assert exc_info.value.code == "tool_disabled"
    assert exc_info.value.state.stop_reason_code == "action_correction_exhausted"
    assert exc_info.value.state.decision_count == 3
    assert exc_info.value.state.tool_call_count == 0
    assert agent.synthesize_calls == 0


def test_unknown_skill_reference_fails_closed_without_synthesis():
    package = make_jump_package([0.2] * 12)
    invalid = LoadSkillResource(
        reference_id="references/gait.md",
        reason="尝试读取其他测试领域",
    )
    agent = _FakeSequentialAgent([invalid, invalid, invalid])

    with pytest.raises(SequentialAnalysisLoopError) as exc_info:
        _loop(agent).run(_observation(package), package, DataAccessScope())

    assert exc_info.value.code == "unknown_skill_reference"
    assert exc_info.value.state.decision_count == 3
    assert exc_info.value.state.action_correction_count == 2
    assert all(
        failure.failure_type == "skill_resource_rejected"
        for failure in exc_info.value.state.failures
    )
    assert agent.synthesize_calls == 0


def test_invalid_skill_request_can_be_corrected_by_stopping():
    package = make_jump_package([0.2] * 12)
    agent = _FakeSequentialAgent(
        [
            LoadSkillResource(
                reference_id="references/gait.md",
                reason="误请求已由系统处理的领域资料",
            ),
            _stop(),
        ]
    )

    result = _loop(agent).run(
        _observation(package), package, DataAccessScope()
    )

    assert result.state.decision_count == 2
    assert result.state.action_correction_count == 1
    assert result.state.failures[0].failure_type == "skill_resource_rejected"
    assert result.state.stop_reason_code == "evidence_sufficient"


def test_resume_from_accepted_action_executes_pending_tool_once():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package)
    validated = ActionValidator().validate_action(
        action, package, DataAccessScope()
    )
    bundle = AnalysisToolGateway().execute_action(
        package, validated, DataAccessScope()
    )
    gateway = _ScriptedGateway([bundle])
    sink = _CheckpointSink(crash_phase="action_accepted")
    interrupted_agent = _FakeSequentialAgent([action])

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        _loop(
            interrupted_agent,
            checkpoint_sink=sink,
            action_boundary=SequentialActionBoundary(tool_gateway=gateway),
        ).run(_observation(package), package, DataAccessScope())

    checkpoint = sink.checkpoints[-1]
    assert checkpoint.phase == "action_accepted"
    assert checkpoint.pending_action is not None
    assert gateway.calls == 0

    resumed_agent = _FakeSequentialAgent([_stop()])
    result = _loop(
        resumed_agent,
        checkpoint_sink=_CheckpointSink(),
        action_boundary=SequentialActionBoundary(tool_gateway=gateway),
    ).run(
        _observation(package),
        package,
        DataAccessScope(),
        resume_from=checkpoint,
    )

    assert gateway.calls == 1
    assert result.state.hypotheses[0].status == "supported"
    assert result.state.tool_call_count == 1


def test_resume_after_recorded_evidence_does_not_repeat_tool_call():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package)
    validated = ActionValidator().validate_action(
        action, package, DataAccessScope()
    )
    bundle = AnalysisToolGateway().execute_action(
        package, validated, DataAccessScope()
    )
    gateway = _ScriptedGateway([bundle])
    sink = _CheckpointSink(crash_phase="evidence_recorded")

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        _loop(
            _FakeSequentialAgent([action]),
            checkpoint_sink=sink,
            action_boundary=SequentialActionBoundary(tool_gateway=gateway),
        ).run(_observation(package), package, DataAccessScope())

    checkpoint = sink.checkpoints[-1]
    assert checkpoint.pending_action is None
    assert gateway.calls == 1

    result = _loop(
        _FakeSequentialAgent([_stop()]),
        action_boundary=SequentialActionBoundary(tool_gateway=gateway),
    ).run(
        _observation(package),
        package,
        DataAccessScope(),
        resume_from=checkpoint,
    )

    assert gateway.calls == 1
    assert len(result.evidence) == 1
    assert result.state.hypotheses[0].status == "supported"


def test_checkpoint_identity_or_skill_mismatch_is_not_resumed():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    sink = _CheckpointSink(crash_phase="skill_loaded")
    with pytest.raises(RuntimeError):
        _loop(
            _FakeSequentialAgent([]), checkpoint_sink=sink
        ).run(_observation(package), package, DataAccessScope())
    checkpoint = sink.checkpoints[-1]

    changed_package = make_jump_package([0.2] * 12)
    with pytest.raises(SequentialAnalysisLoopError) as identity_error:
        _loop(_FakeSequentialAgent([])).run(
            _observation(changed_package),
            changed_package,
            DataAccessScope(),
            resume_from=checkpoint,
        )
    assert identity_error.value.code == "checkpoint_identity_mismatch"

    changed_skill = checkpoint.model_copy(
        update={"skill_version": "report-analysis-skill/changed"}
    )
    with pytest.raises(SequentialAnalysisLoopError) as skill_error:
        _loop(_FakeSequentialAgent([])).run(
            _observation(package),
            package,
            DataAccessScope(),
            resume_from=changed_skill,
        )
    assert skill_error.value.code == "checkpoint_skill_mismatch"
