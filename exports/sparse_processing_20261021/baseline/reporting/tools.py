"""Trusted analysis-tool catalog used for permission and capability checks."""

from __future__ import annotations

from dataclasses import dataclass

from .kernel import AnalysisMethodRegistry
from .models import (
    AnalysisMethodCapability,
    AnalysisToolCapability,
    AnalysisToolName,
    DataAccessScope,
    DataScope,
    ReportDataPackage,
)


ANALYSIS_TOOL_REGISTRY_VERSION = "analysis-tool-registry/1.0"


@dataclass(frozen=True)
class AnalysisToolSpec:
    name: AnalysisToolName
    version: str
    required_scope: DataScope
    enabled: bool
    method_names: tuple[str, ...]
    unavailable_reason: str | None = None


class AnalysisToolRegistry:
    def __init__(self):
        specs = (
            AnalysisToolSpec(
                "analyze_current_session",
                "analyze-current-session-tool/1.0",
                "current_session",
                True,
                (
                    "verify_temporal_change",
                    "verify_side_segment_difference",
                    "verify_cross_metric_cochange",
                    "verify_exclusion_robustness",
                    "quality_scope_check",
                ),
            ),
            AnalysisToolSpec(
                "compare_longitudinal",
                "compare-longitudinal-tool/0.1-disabled",
                "longitudinal",
                False,
                (),
                "tool_not_implemented_in_mvp",
            ),
            AnalysisToolSpec(
                "compare_cohort",
                "compare-cohort-tool/0.1-disabled",
                "cohort",
                False,
                (),
                "tool_not_implemented_in_mvp",
            ),
        )
        self._specs = {spec.name: spec for spec in specs}

    def get(self, name: str) -> AnalysisToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"Unknown analysis tool: {name}") from exc

    def all(self) -> tuple[AnalysisToolSpec, ...]:
        return tuple(self._specs.values())

    def list_capabilities(
        self,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        method_registry: AnalysisMethodRegistry,
    ) -> list[AnalysisToolCapability]:
        metric_codes = tuple(
            sorted(
                {
                    metric_code
                    for record_set in package.record_sets
                    for metric_code in record_set.metric_codes
                }
            )
        )
        has_both_sides = any(
            {record.side for record in record_set.records}.issuperset({"left", "right"})
            for record_set in package.record_sets
        )
        capabilities: list[AnalysisToolCapability] = []
        for tool in self.all():
            authorized = bool(getattr(access_scope, tool.required_scope))
            tool_enabled = tool.enabled and authorized
            tool_reason = tool.unavailable_reason
            if tool.enabled and not authorized:
                tool_reason = "data_scope_not_authorized"
            methods = []
            for method_name in tool.method_names:
                method = method_registry.get(method_name)
                method_enabled = tool_enabled
                method_reason = tool_reason
                if method.requires_side and not has_both_sides:
                    method_enabled = False
                    method_reason = "side_dimension_unavailable"
                methods.append(
                    AnalysisMethodCapability(
                        analysis_method=method.name,
                        analysis_method_version=method.version,
                        dimensions=method.dimensions,
                        metric_codes=metric_codes if method.max_metrics else (),
                        enabled=method_enabled,
                        unavailable_reason=method_reason,
                    )
                )
            capabilities.append(
                AnalysisToolCapability(
                    tool_name=tool.name,
                    tool_version=tool.version,
                    required_scope=tool.required_scope,
                    enabled=tool_enabled,
                    available_methods=tuple(methods),
                    unavailable_reason=tool_reason,
                )
            )
        return capabilities
