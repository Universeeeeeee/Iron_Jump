"""Contracts for the three Tool catalog and deterministic Method catalog."""

from reporting.kernel import AnalysisMethodRegistry
from reporting.models import DataAccessScope
from reporting.tools import AnalysisToolRegistry
from tests.reporting_fixtures import make_jump_package, make_treadmill_package


def test_tool_registry_contains_exactly_three_tools_with_mvp_states():
    registry = AnalysisToolRegistry()
    specs = registry.all()

    assert {spec.name for spec in specs} == {
        "analyze_current_session",
        "compare_longitudinal",
        "compare_cohort",
    }
    assert registry.get("analyze_current_session").enabled is True
    assert registry.get("compare_longitudinal").enabled is False
    assert registry.get("compare_cohort").enabled is False


def test_capability_catalog_nests_methods_and_respects_side_availability():
    tools = AnalysisToolRegistry()
    methods = AnalysisMethodRegistry()
    jump = {
        item.tool_name: item
        for item in tools.list_capabilities(
            make_jump_package([0.2] * 12), DataAccessScope(), methods
        )
    }
    treadmill = {
        item.tool_name: item
        for item in tools.list_capabilities(
            make_treadmill_package([0.2] * 6, [0.2] * 6),
            DataAccessScope(),
            methods,
        )
    }

    jump_methods = {
        item.analysis_method: item
        for item in jump["analyze_current_session"].available_methods
    }
    treadmill_methods = {
        item.analysis_method: item
        for item in treadmill["analyze_current_session"].available_methods
    }
    assert jump_methods["verify_side_segment_difference"].enabled is False
    assert treadmill_methods["verify_side_segment_difference"].enabled is True
    assert jump["compare_longitudinal"].enabled is False
    assert jump["compare_longitudinal"].unavailable_reason == "tool_not_implemented_in_mvp"


def test_method_registry_exposes_semantic_methods_not_kernel_primitives():
    names = {spec.name for spec in AnalysisMethodRegistry().all()}
    assert names == {
        "summarize_records",
        "verify_temporal_change",
        "verify_side_segment_difference",
        "verify_cross_metric_cochange",
        "verify_exclusion_robustness",
        "quality_scope_check",
    }
    assert not names.intersection({"mean", "filter", "groupby", "std"})


def test_tool_method_and_kernel_versions_are_independent():
    tool = AnalysisToolRegistry().get("analyze_current_session")
    methods = AnalysisMethodRegistry()

    assert tool.version == "analyze-current-session-tool/1.1"
    assert methods.get("verify_temporal_change").version == "temporal-change-method/1.0"
    assert methods.get("verify_side_segment_difference").version == "side-segment-difference-method/1.0"
