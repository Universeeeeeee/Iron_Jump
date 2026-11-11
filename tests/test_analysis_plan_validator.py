"""Permission and complexity tests for Agent-generated analysis plans."""

import pytest
from dataclasses import replace
from pydantic import ValidationError

from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    SmallAnalysisPlan,
)
from reporting.kernel import AnalysisMethodRegistry
from reporting.validators import PlanValidationError, PlanValidator
from tests.reporting_fixtures import make_jump_package


def _question(question_id="q1"):
    return AnalysisQuestion(
        question_id=question_id,
        description="后半程触地时间是否增加",
        dimensions=("temporal",),
        metric_codes=("contact_time_s",),
        reason="观察到分段均值变化",
        stop_condition="获得受支持的方向证据",
    )


def _node(record_set_id, *, node_id="n1", analysis_method="verify_temporal_change", dependencies=(), inputs=None, tool_name="analyze_current_session"):
    return AnalysisNode(
        node_id=node_id,
        tool_name=tool_name,
        analysis_method=analysis_method,
        inputs=inputs or {
            "record_set_id": record_set_id,
            "metric_codes": ["contact_time_s"],
        },
        dependencies=dependencies,
        question_id="q1",
        purpose="验证时序方向",
    )


def test_valid_plan_has_stable_execution_order_and_request_hash():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    record_set_id = package.record_sets[0].record_set_id
    plan = SmallAnalysisPlan(
        questions=(_question(),),
        nodes=(_node(record_set_id),),
    )

    validated_a = PlanValidator().validate(plan, package, DataAccessScope())
    validated_b = PlanValidator().validate(plan, package, DataAccessScope())

    assert validated_a.execution_order == ("n1",)
    assert validated_a.request_hashes == validated_b.request_hashes


def test_plan_rejects_question_and_node_ids_used_by_previous_cycle():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    plan = SmallAnalysisPlan(
        questions=(_question(),),
        nodes=(_node(package.record_sets[0].record_set_id),),
    )

    with pytest.raises(PlanValidationError) as question_error:
        PlanValidator().validate(
            plan,
            package,
            DataAccessScope(),
            used_question_ids=frozenset((plan.questions[0].question_id,)),
        )
    with pytest.raises(PlanValidationError) as node_error:
        PlanValidator().validate(
            plan,
            package,
            DataAccessScope(),
            used_node_ids=frozenset((plan.nodes[0].node_id,)),
        )

    assert question_error.value.code == "duplicate_question_id_across_cycles"
    assert node_error.value.code == "duplicate_node_id_across_cycles"


def test_analysis_question_rejects_agent_supplied_permission_fields():
    with pytest.raises(ValidationError):
        AnalysisQuestion(
            **_question().model_dump(),
            required_scope="longitudinal",
        )


@pytest.mark.parametrize(
    "mutator,expected_code",
    [
        ("four_nodes", "too_many_nodes"),
        ("unknown_metric", "metric_not_in_record_set"),
        ("duplicate_request", "duplicate_request"),
        ("cycle", "cyclic_dependencies"),
        ("disabled_tool", "tool_disabled"),
    ],
)
def test_invalid_plans_are_rejected_before_kernel(mutator, expected_code):
    package = make_jump_package([0.2] * 12)
    record_set_id = package.record_sets[0].record_set_id
    nodes = [_node(record_set_id)]
    if mutator == "four_nodes":
        nodes = [
            _node(record_set_id, node_id=f"n{index}", inputs={
                "record_set_id": record_set_id,
                "metric_codes": [metric],
            })
            for index, metric in enumerate(
                ["contact_time_s", "air_time_s", "jump_height_m", "cycle_time_s"],
                start=1,
            )
        ]
    elif mutator == "unknown_metric":
        nodes[0] = _node(record_set_id, inputs={"record_set_id": record_set_id, "metric_codes": ["unknown"]})
    elif mutator == "duplicate_request":
        nodes.append(_node(record_set_id, node_id="n2"))
    elif mutator == "cycle":
        nodes = [
            _node(record_set_id, node_id="n1", dependencies=("n2",)),
            _node(record_set_id, node_id="n2", dependencies=("n1",), inputs={"record_set_id": record_set_id, "metric_codes": ["air_time_s"]}),
        ]
    elif mutator == "disabled_tool":
        nodes[0] = _node(record_set_id, tool_name="compare_cohort")
    if mutator == "four_nodes":
        plan = SmallAnalysisPlan.model_construct(
            questions=(_question(),),
            nodes=tuple(nodes),
        )
    else:
        plan = SmallAnalysisPlan(questions=(_question(),), nodes=tuple(nodes))

    with pytest.raises(PlanValidationError) as exc_info:
        PlanValidator().validate(plan, package, DataAccessScope())

    assert exc_info.value.code == expected_code


def test_method_must_belong_to_selected_tool():
    package = make_jump_package([0.2] * 12)
    record_set_id = package.record_sets[0].record_set_id
    registry = AnalysisMethodRegistry()

    class _MismatchedMethodRegistry:
        def get(self, name):
            return replace(registry.get(name), tool_name="compare_cohort")

    plan = SmallAnalysisPlan(
        questions=(_question(),),
        nodes=(_node(record_set_id),),
    )
    with pytest.raises(PlanValidationError) as exc_info:
        PlanValidator(method_registry=_MismatchedMethodRegistry()).validate(
            plan, package, DataAccessScope()
        )

    assert exc_info.value.code == "method_tool_mismatch"
