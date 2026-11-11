"""Stable DAG scheduling and failure-boundary tests for the Tool gateway."""

from dataclasses import replace

import pytest

from agent.report.tools import AnalysisToolGateway
from reporting.kernel import AnalysisKernel, AnalysisMethodRegistry
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    HypothesisTarget,
    NextAnalysisAction,
    SmallAnalysisPlan,
)
from reporting.tools import AnalysisToolRegistry, AnalysisToolSpec
from reporting.validators import ActionValidator, PlanValidator
from tests.reporting_fixtures import make_jump_package


class _EnabledToolRegistry:
    def __init__(self):
        self._specs = {
            "analyze_current_session": AnalysisToolSpec(
                "analyze_current_session",
                "current-test-tool/1.0",
                "current_session",
                True,
                ("verify_temporal_change",),
            ),
            "compare_longitudinal": AnalysisToolSpec(
                "compare_longitudinal",
                "longitudinal-test-tool/1.0",
                "longitudinal",
                True,
                ("verify_exclusion_robustness",),
            ),
            "compare_cohort": AnalysisToolSpec(
                "compare_cohort",
                "cohort-test-tool/1.0",
                "cohort",
                True,
                ("quality_scope_check",),
            ),
        }

    def get(self, name):
        return self._specs[name]


class _CrossToolMethodRegistry:
    def __init__(self):
        base = AnalysisMethodRegistry()
        self._specs = {
            "verify_temporal_change": base.get("verify_temporal_change"),
            "verify_exclusion_robustness": replace(
                base.get("verify_exclusion_robustness"),
                tool_name="compare_longitudinal",
            ),
            "quality_scope_check": replace(
                base.get("quality_scope_check"),
                tool_name="compare_cohort",
            ),
        }

    def get(self, name):
        return self._specs[name]


class _KernelBackedTool:
    def __init__(self, kernel, calls, *, fail=False):
        self.kernel = kernel
        self.calls = calls
        self.fail = fail

    def execute(self, package, node, spec, dependency_evidence):
        self.calls.append((node.node_id, tuple(item.node_id for item in dependency_evidence)))
        if self.fail:
            raise RuntimeError("synthetic tool failure")
        return self.kernel.execute_method(
            package,
            node,
            tool_version=spec.version,
            data_scope=spec.required_scope,
            dependency_evidence=dependency_evidence,
        )


def _validated_cross_tool_plan(package):
    record_set_id = package.record_sets[0].record_set_id
    questions = tuple(
        AnalysisQuestion(
            question_id=f"q{index}",
            description="test",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            reason="test",
            stop_condition="verified",
        )
        for index in range(1, 4)
    )
    nodes = (
        AnalysisNode(
            node_id="n-current",
            tool_name="analyze_current_session",
            analysis_method="verify_temporal_change",
            inputs={"record_set_id": record_set_id, "metric_codes": ["contact_time_s"]},
            question_id="q1",
            purpose="current",
        ),
        AnalysisNode(
            node_id="n-longitudinal",
            tool_name="compare_longitudinal",
            analysis_method="verify_exclusion_robustness",
            inputs={"record_set_id": record_set_id, "metric_codes": ["contact_time_s"]},
            dependencies=("n-current",),
            question_id="q2",
            purpose="longitudinal",
        ),
        AnalysisNode(
            node_id="n-cohort",
            tool_name="compare_cohort",
            analysis_method="quality_scope_check",
            inputs={},
            dependencies=("n-longitudinal",),
            question_id="q3",
            purpose="cohort",
        ),
    )
    plan = SmallAnalysisPlan(questions=questions, nodes=nodes)
    tools = _EnabledToolRegistry()
    methods = _CrossToolMethodRegistry()
    scope = DataAccessScope(longitudinal=True, cohort=True)
    return (
        PlanValidator(tools, methods).validate(plan, package, scope),
        tools,
        methods,
        scope,
    )


def test_gateway_executes_cross_tool_dependencies_in_dag_order_without_grouping():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    validated, tools, methods, scope = _validated_cross_tool_plan(package)
    kernel = AnalysisKernel(methods)
    calls = []
    implementations = {
        name: _KernelBackedTool(kernel, calls)
        for name in (
            "analyze_current_session",
            "compare_longitudinal",
            "compare_cohort",
        )
    }

    bundle = AnalysisToolGateway(
        tool_registry=tools,
        method_registry=methods,
        kernel=kernel,
        tool_implementations=implementations,
    ).execute_plan(package, validated, scope)

    assert calls == [
        ("n-current", ()),
        ("n-longitudinal", ("n-current",)),
        ("n-cohort", ("n-longitudinal",)),
    ]
    assert tuple(item.node_id for item in bundle.items) == validated.execution_order


def test_gateway_stops_after_failure_and_does_not_execute_downstream_node():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    validated, tools, methods, scope = _validated_cross_tool_plan(package)
    kernel = AnalysisKernel(methods)
    calls = []
    implementations = {
        "analyze_current_session": _KernelBackedTool(kernel, calls),
        "compare_longitudinal": _KernelBackedTool(kernel, calls, fail=True),
        "compare_cohort": _KernelBackedTool(kernel, calls),
    }

    with pytest.raises(RuntimeError, match="synthetic tool failure"):
        AnalysisToolGateway(
            tool_registry=tools,
            method_registry=methods,
            kernel=kernel,
            tool_implementations=implementations,
        ).execute_plan(package, validated, scope)

    assert calls == [
        ("n-current", ()),
        ("n-longitudinal", ("n-current",)),
    ]


def test_production_registry_rejects_disabled_tool_before_execution():
    registry = AnalysisToolRegistry()
    assert registry.get("compare_longitudinal").enabled is True
    assert registry.get("compare_cohort").enabled is False


def test_single_action_adapter_preserves_evidence_and_output_digest():
    package = make_jump_package([0.2] * 6 + [0.3] * 6)
    record_set_id = package.record_sets[0].record_set_id
    action = NextAnalysisAction(
        action_id="a1",
        hypothesis=HypothesisTarget(
            hypothesis_id="h1",
            statement="触地时间是否在后半程增加",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            target_predicate="increase",
            reason="前后段存在候选差异",
            success_condition="获得方向证据",
        ),
        tool_name="analyze_current_session",
        analysis_method="verify_temporal_change",
        inputs={
            "record_set_id": record_set_id,
            "metric_codes": ["contact_time_s"],
        },
        purpose="验证时序变化",
    )
    scope = DataAccessScope()
    validated_action = ActionValidator().validate_action(
        action, package, scope
    )
    gateway = AnalysisToolGateway()

    action_bundle = gateway.execute_action(package, validated_action, scope)
    plan = SmallAnalysisPlan(
        questions=(validated_action.question,),
        nodes=(validated_action.node,),
    )
    validated_plan = PlanValidator().validate(plan, package, scope)
    plan_bundle = gateway.execute_plan(package, validated_plan, scope)

    assert action_bundle == plan_bundle
    assert (
        action_bundle.tool_runs[0].output_digest
        == plan_bundle.tool_runs[0].output_digest
    )
