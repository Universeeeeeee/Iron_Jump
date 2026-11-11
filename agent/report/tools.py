"""Controlled Tool gateway for deterministic Report Agent plan execution."""

from __future__ import annotations

from typing import Protocol

from reporting.kernel import AnalysisKernel, AnalysisMethodRegistry
from reporting.models import (
    AnalysisNode,
    DataAccessScope,
    EvidenceBundle,
    EvidenceItem,
    ReportDataPackage,
    SmallAnalysisPlan,
    ValidatedAnalysisAction,
    ValidatedAnalysisPlan,
)
from reporting.tools import AnalysisToolRegistry, AnalysisToolSpec


class AnalysisToolExecutionError(RuntimeError):
    code = "analysis_tool_execution_failed"


class TransientAnalysisToolError(AnalysisToolExecutionError):
    code = "transient_analysis_tool_failure"


class AnalysisTool(Protocol):
    def execute(
        self,
        package: ReportDataPackage,
        node: AnalysisNode,
        spec: AnalysisToolSpec,
        dependency_evidence: tuple[EvidenceItem, ...],
    ): ...


class CurrentSessionAnalysisTool:
    def __init__(self, kernel: AnalysisKernel):
        self._kernel = kernel

    def execute(self, package, node, spec, dependency_evidence):
        if spec.required_scope != "current_session":
            raise AnalysisToolExecutionError("current-session Tool received another scope")
        return self._kernel.execute_method(
            package,
            node,
            tool_version=spec.version,
            data_scope=spec.required_scope,
            dependency_evidence=dependency_evidence,
        )


class DisabledAnalysisTool:
    def execute(self, package, node, spec, dependency_evidence):
        raise AnalysisToolExecutionError(
            f"analysis tool {spec.name} is disabled: {spec.unavailable_reason}"
        )


class AnalysisToolGateway:
    def __init__(
        self,
        *,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
        kernel: AnalysisKernel | None = None,
        tool_implementations: dict[str, AnalysisTool] | None = None,
        longitudinal_tool=None,
    ):
        self._tool_registry = tool_registry or AnalysisToolRegistry()
        self._method_registry = method_registry or AnalysisMethodRegistry()
        self._kernel = kernel or AnalysisKernel(self._method_registry)
        self._tool_implementations = tool_implementations or {
            "analyze_current_session": CurrentSessionAnalysisTool(self._kernel),
            "compare_longitudinal": DisabledAnalysisTool(),
            "compare_cohort": DisabledAnalysisTool(),
        }
        if longitudinal_tool is not None:
            self._tool_implementations["compare_longitudinal"] = longitudinal_tool

    def execute_plan(
        self,
        package: ReportDataPackage,
        validated_plan: ValidatedAnalysisPlan,
        access_scope: DataAccessScope,
    ) -> EvidenceBundle:
        nodes = {node.node_id: node for node in validated_plan.plan.nodes}
        completed: dict[str, EvidenceItem] = {}
        items: list[EvidenceItem] = []
        runs = []
        provenance = []
        for node_id in validated_plan.execution_order:
            node = nodes[node_id]
            spec = self._tool_registry.get(node.tool_name)
            if not spec.enabled:
                raise AnalysisToolExecutionError(f"analysis tool {node.tool_name} is disabled")
            if not bool(getattr(access_scope, spec.required_scope)):
                raise AnalysisToolExecutionError(
                    f"data scope {spec.required_scope} is not authorized"
                )
            method = self._method_registry.get(node.analysis_method)
            if method.tool_name != node.tool_name or node.analysis_method not in spec.method_names:
                raise AnalysisToolExecutionError(
                    f"analysis method {node.analysis_method} does not belong to {node.tool_name}"
                )
            try:
                implementation = self._tool_implementations[node.tool_name]
            except KeyError as exc:
                raise AnalysisToolExecutionError(
                    f"analysis tool {node.tool_name} has no implementation"
                ) from exc
            dependency_evidence = tuple(completed[item] for item in node.dependencies)
            item, run, provenance_record = implementation.execute(
                package,
                node,
                spec,
                dependency_evidence,
            )
            completed[node_id] = item
            items.append(item)
            runs.append(run)
            provenance.append(provenance_record)
        return EvidenceBundle(
            package_id=package.metadata.package_id,
            package_digest=package.metadata.package_digest,
            items=tuple(items),
            tool_runs=tuple(runs),
            provenance=tuple(provenance),
        )

    def execute_action(
        self,
        package: ReportDataPackage,
        validated_action: ValidatedAnalysisAction,
        access_scope: DataAccessScope,
    ) -> EvidenceBundle:
        """Execute one validated action through the unchanged DAG executor."""

        return self.execute_plan(
            package,
            ValidatedAnalysisPlan(
                plan=SmallAnalysisPlan(
                    questions=(validated_action.question,),
                    nodes=(validated_action.node,),
                ),
                execution_order=(validated_action.node.node_id,),
                request_hashes=(validated_action.request_hash,),
                total_cost=validated_action.cost,
            ),
            access_scope,
        )
