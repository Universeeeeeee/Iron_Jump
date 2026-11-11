"""Typed outcome and bounded recovery tests for sequential Tool execution."""

import pytest
from pydantic import ValidationError

from agent.report.execution import SequentialActionBoundary
from agent.report.state import AnalysisStateReducer
from agent.report.tools import AnalysisToolGateway, TransientAnalysisToolError
from reporting.models import (
    ActionRejected,
    DataAccessScope,
    EvidenceProduced,
    HypothesisTarget,
    NextAnalysisAction,
    SequentialAnalysisState,
    ToolExecutionFailed,
)
from reporting.validators import ActionValidator
from tests.reporting_fixtures import make_jump_package


def _action(package, *, tool_name="analyze_current_session"):
    return NextAnalysisAction(
        action_id="a1",
        hypothesis=HypothesisTarget(
            hypothesis_id="h1",
            statement="触地时间是否增加",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            target_predicate="increase",
            reason="观察到候选变化",
            success_condition="获得方向证据",
        ),
        tool_name=tool_name,
        analysis_method="verify_temporal_change",
        inputs={
            "record_set_id": package.record_sets[0].record_set_id,
            "metric_codes": ["contact_time_s"],
        },
        purpose="验证时序变化",
    )


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


def _validated_and_bundle(package):
    action = ActionValidator().validate_action(
        _action(package),
        package,
        DataAccessScope(),
    )
    bundle = AnalysisToolGateway().execute_action(
        package,
        action,
        DataAccessScope(),
    )
    return action, bundle


def test_invalid_action_is_rejected_before_tool_execution():
    package = make_jump_package([0.2] * 12)
    gateway = _ScriptedGateway([])
    boundary = SequentialActionBoundary(tool_gateway=gateway)

    first = boundary.validate(
        _action(package, tool_name="compare_cohort"),
        package,
        DataAccessScope(),
    )
    exhausted = boundary.validate(
        _action(package, tool_name="compare_cohort"),
        package,
        DataAccessScope(),
        action_correction_count=2,
    )

    assert isinstance(first, ActionRejected)
    assert first.error_code == "tool_disabled"
    assert first.correction_allowed is True
    assert isinstance(exhausted, ActionRejected)
    assert exhausted.correction_allowed is False
    assert gateway.calls == 0


def test_valid_action_returns_evidence_produced():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action, bundle = _validated_and_bundle(package)
    boundary = SequentialActionBoundary(
        tool_gateway=_ScriptedGateway([bundle])
    )

    outcome = boundary.execute(action, package, DataAccessScope())

    assert isinstance(outcome, EvidenceProduced)
    assert outcome.attempt_count == 1
    assert outcome.evidence == bundle


def test_transient_failure_retries_once_then_returns_evidence():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action, bundle = _validated_and_bundle(package)
    gateway = _ScriptedGateway(
        [TransientAnalysisToolError("temporary lock"), bundle]
    )
    boundary = SequentialActionBoundary(tool_gateway=gateway)

    outcome = boundary.execute(action, package, DataAccessScope())

    assert isinstance(outcome, EvidenceProduced)
    assert outcome.attempt_count == 2
    assert gateway.calls == 2

    active = AnalysisStateReducer().begin_action(
        SequentialAnalysisState(), action
    )
    resolved = AnalysisStateReducer().apply_evidence_outcome(active, outcome)
    assert resolved.tool_retry_count == 1


def test_transient_failure_after_retry_budget_returns_typed_failure():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action, _ = _validated_and_bundle(package)
    gateway = _ScriptedGateway(
        [
            TransientAnalysisToolError("temporary lock"),
            TransientAnalysisToolError("temporary lock"),
        ]
    )

    outcome = SequentialActionBoundary(tool_gateway=gateway).execute(
        action,
        package,
        DataAccessScope(),
    )

    assert isinstance(outcome, ToolExecutionFailed)
    assert outcome.failure_kind == "transient"
    assert outcome.retry_exhausted is True
    assert outcome.attempt_count == 2


def test_hard_failure_is_not_retried_or_converted_to_evidence():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action, _ = _validated_and_bundle(package)
    gateway = _ScriptedGateway([RuntimeError("kernel defect")])

    outcome = SequentialActionBoundary(tool_gateway=gateway).execute(
        action,
        package,
        DataAccessScope(),
    )

    assert isinstance(outcome, ToolExecutionFailed)
    assert outcome.failure_kind == "hard"
    assert outcome.retry_exhausted is False
    assert outcome.attempt_count == 1
    assert gateway.calls == 1

    with pytest.raises(ValidationError):
        ToolExecutionFailed(
            action=action,
            error_code="hard_failure",
            message="not retryable",
            failure_kind="hard",
            attempt_count=1,
            retry_exhausted=True,
        )


def test_inconclusive_result_is_evidence_not_tool_failure():
    package = make_jump_package([0.2, 0.21, 0.3, 0.31])
    action = ActionValidator().validate_action(
        _action(package),
        package,
        DataAccessScope(),
    )

    outcome = SequentialActionBoundary().execute(
        action,
        package,
        DataAccessScope(),
    )

    assert isinstance(outcome, EvidenceProduced)
    assert outcome.evidence.items[0].analysis_status == "inconclusive"


def test_tool_failure_is_recorded_without_negating_active_hypothesis():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action, _ = _validated_and_bundle(package)
    reducer = AnalysisStateReducer()
    active = reducer.begin_action(SequentialAnalysisState(), action)
    outcome = SequentialActionBoundary(
        tool_gateway=_ScriptedGateway([RuntimeError("kernel defect")])
    ).execute(action, package, DataAccessScope())

    failed = reducer.record_tool_failure(active, outcome)

    assert isinstance(outcome, ToolExecutionFailed)
    assert failed.hypotheses[0].status == "active"
    assert failed.rejected_predicates == ()
    assert failed.failures[0].failure_type == "tool_execution_failed"
    assert failed.stop_reason_code == "hard_tool_failure"


def test_action_rejection_consumes_decision_not_tool_budget_and_stops_after_limit():
    package = make_jump_package([0.2] * 12)
    action = _action(package, tool_name="compare_cohort")
    boundary = SequentialActionBoundary()
    reducer = AnalysisStateReducer()
    state = SequentialAnalysisState()

    for _ in range(2):
        rejection = boundary.validate(
            action,
            package,
            DataAccessScope(),
            action_correction_count=state.action_correction_count,
        )
        state = reducer.record_action_rejection(state, rejection)
    final_rejection = boundary.validate(
        action,
        package,
        DataAccessScope(),
        action_correction_count=state.action_correction_count,
    )
    state = reducer.record_action_rejection(state, final_rejection)

    assert state.decision_count == 3
    assert state.tool_call_count == 0
    assert state.action_correction_count == 2
    assert len(state.failures) == 3
    assert final_rejection.correction_allowed is False
    assert state.stop_reason_code == "action_correction_exhausted"
