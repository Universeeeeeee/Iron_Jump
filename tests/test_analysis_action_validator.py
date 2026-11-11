"""Single-decision contracts for sequential Report Agent analysis."""

import pytest
from pydantic import TypeAdapter, ValidationError

from reporting.models import (
    AnalysisDecision,
    DataAccessScope,
    HypothesisTarget,
    LoadSkillResource,
    NextAnalysisAction,
    StopAnalysis,
)
from reporting.validators import ActionValidationError, ActionValidator
from tests.reporting_fixtures import make_jump_package


def _action(record_set_id, **updates):
    values = {
        "action_id": "a1",
        "hypothesis": HypothesisTarget(
            hypothesis_id="h1",
            statement="触地时间是否在后半程增加",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            target_predicate="increase",
            reason="观察到前后段差异",
            success_condition="获得确定性的方向证据",
        ),
        "tool_name": "analyze_current_session",
        "analysis_method": "verify_temporal_change",
        "inputs": {
            "record_set_id": record_set_id,
            "metric_codes": ["contact_time_s"],
        },
        "purpose": "验证当前记录的时序变化",
    }
    values.update(updates)
    return NextAnalysisAction(**values)


def test_analysis_decision_union_dispatches_all_three_decision_types():
    adapter = TypeAdapter(AnalysisDecision)

    stop = adapter.validate_python(
        {
            "decision_type": "stop",
            "reason_code": "no_high_value_hypothesis",
            "reason": "没有新的可验证线索",
        }
    )
    load = adapter.validate_python(
        {
            "decision_type": "load_skill_resource",
            "reference_id": "references/evidence-guidelines.md",
            "reason": "准备综合结论",
        }
    )

    assert isinstance(stop, StopAnalysis)
    assert isinstance(load, LoadSkillResource)


def test_agent_cannot_put_scope_or_versions_in_next_action():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package.record_sets[0].record_set_id)

    with pytest.raises(ValidationError):
        NextAnalysisAction(
            **action.model_dump(),
            data_scope="longitudinal",
            tool_version="invented",
        )


def test_valid_action_derives_scope_and_has_stable_request_hash():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package.record_sets[0].record_set_id)
    validator = ActionValidator()

    first = validator.validate_action(action, package, DataAccessScope())
    second = validator.validate_action(action, package, DataAccessScope())

    assert first.required_scope == "current_session"
    assert first.cost == 2
    assert first.request_hash == second.request_hash
    assert len(first.request_hash) == 64


def test_action_rejects_hypothesis_metric_mismatch():
    package = make_jump_package([0.2] * 12)
    hypothesis = HypothesisTarget(
        hypothesis_id="h1",
        statement="滞空时间是否变化",
        dimensions=("temporal",),
        metric_codes=("air_time_s",),
        target_predicate="increase",
        reason="候选变化",
        success_condition="获得方向证据",
    )
    action = _action(
        package.record_sets[0].record_set_id,
        hypothesis=hypothesis,
    )

    with pytest.raises(ActionValidationError) as exc_info:
        ActionValidator().validate_action(action, package, DataAccessScope())

    assert exc_info.value.code == "hypothesis_metric_mismatch"


def test_action_rejects_predicate_not_produced_by_selected_method():
    package = make_jump_package([0.2] * 12)
    hypothesis = HypothesisTarget(
        hypothesis_id="h1",
        statement="是否存在跨指标共同变化",
        dimensions=("cross_metric",),
        metric_codes=("contact_time_s",),
        target_predicate="co_change",
        reason="候选关系",
        success_condition="获得共同变化证据",
    )
    action = _action(
        package.record_sets[0].record_set_id,
        hypothesis=hypothesis,
    )

    with pytest.raises(ActionValidationError) as exc_info:
        ActionValidator().validate_action(action, package, DataAccessScope())

    assert exc_info.value.code == "predicate_method_mismatch"


def test_action_rejects_disabled_tool_before_execution():
    package = make_jump_package([0.2] * 12)
    action = _action(
        package.record_sets[0].record_set_id,
        tool_name="compare_cohort",
    )

    with pytest.raises(ActionValidationError) as exc_info:
        ActionValidator().validate_action(action, package, DataAccessScope())

    assert exc_info.value.code == "tool_disabled"


def test_action_rejects_duplicate_request_and_exhausted_budget():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package.record_sets[0].record_set_id)
    validator = ActionValidator()
    validated = validator.validate_action(action, package, DataAccessScope())

    with pytest.raises(ActionValidationError) as duplicate:
        validator.validate_action(
            action,
            package,
            DataAccessScope(),
            seen_request_hashes=frozenset((validated.request_hash,)),
        )
    with pytest.raises(ActionValidationError) as exhausted:
        validator.validate_action(
            action,
            package,
            DataAccessScope(),
            remaining_tool_calls=0,
        )

    assert duplicate.value.code == "duplicate_action_request"
    assert exhausted.value.code == "tool_budget_exhausted"


def test_action_rejects_ids_used_by_previous_sequential_turn():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    action = _action(package.record_sets[0].record_set_id)
    validator = ActionValidator()

    with pytest.raises(ActionValidationError) as action_error:
        validator.validate_action(
            action,
            package,
            DataAccessScope(),
            seen_action_ids=frozenset((action.action_id,)),
        )
    with pytest.raises(ActionValidationError) as hypothesis_error:
        validator.validate_action(
            action,
            package,
            DataAccessScope(),
            seen_hypothesis_ids=frozenset(
                (action.hypothesis.hypothesis_id,)
            ),
        )

    assert action_error.value.code == "duplicate_node_id_across_cycles"
    assert (
        hypothesis_error.value.code
        == "duplicate_question_id_across_cycles"
    )


def test_skill_reference_is_whitelisted_and_cannot_be_loaded_twice():
    validator = ActionValidator()
    decision = LoadSkillResource(
        reference_id="references/evidence-guidelines.md",
        reason="准备生成Evidence绑定结论",
    )

    assert validator.validate_skill_resource(decision) is decision
    with pytest.raises(ActionValidationError) as duplicate:
        validator.validate_skill_resource(
            decision,
            loaded_skill_references=frozenset((decision.reference_id,)),
        )
    with pytest.raises(ActionValidationError) as unknown:
        validator.validate_skill_resource(
            LoadSkillResource(
                reference_id="references/unknown.md",
                reason="尝试读取未注册内容",
            )
        )
    with pytest.raises(ActionValidationError) as exhausted:
        validator.validate_skill_resource(
            decision,
            remaining_skill_reference_loads=0,
        )

    assert duplicate.value.code == "duplicate_skill_reference"
    assert unknown.value.code == "unknown_skill_reference"
    assert exhausted.value.code == "skill_reference_budget_exhausted"


def test_stop_decision_does_not_consume_tool_budget():
    package = make_jump_package([0.2] * 12)
    stop = StopAnalysis(
        reason_code="no_high_value_hypothesis",
        reason="没有值得继续验证的假设",
    )

    validated = ActionValidator().validate_decision(
        stop,
        package,
        DataAccessScope(),
        remaining_tool_calls=0,
    )

    assert validated is stop
