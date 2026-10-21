"""Deterministic validation boundaries for Agent-generated analysis plans."""

from __future__ import annotations

import hashlib
import json
import re

from .kernel import AnalysisMethodRegistry
from .models import (
    AnalysisNode,
    AnalysisQuestion,
    DraftAnalysisPackage,
    EvidenceBundle,
    DataAccessScope,
    LoadSkillResource,
    NextAnalysisAction,
    PredicateBinding,
    ReportDataPackage,
    SmallAnalysisPlan,
    StopAnalysis,
    ValidatedAnalysisClaim,
    ValidatedAnalysisAction,
    ValidatedAnalysisPackage,
    ValidatedNumericBinding,
    ValidatedAnalysisPlan,
)
from .text import format_numeric_value
from .tools import AnalysisToolRegistry


MAX_ANALYSIS_QUESTIONS_PER_CYCLE = 3
MAX_AGENT_LEVEL_NODES_PER_CYCLE = 3
MAX_PLAN_COST = 9


class PlanValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PlanValidator:
    def __init__(
        self,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
    ):
        self.tool_registry = tool_registry or AnalysisToolRegistry()
        self.method_registry = method_registry or AnalysisMethodRegistry()

    def validate(
        self,
        plan: SmallAnalysisPlan,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        used_question_ids: frozenset[str] = frozenset(),
        used_node_ids: frozenset[str] = frozenset(),
    ) -> ValidatedAnalysisPlan:
        if len(plan.questions) > MAX_ANALYSIS_QUESTIONS_PER_CYCLE:
            self._fail("too_many_questions", "at most three questions are allowed")
        if len(plan.nodes) > MAX_AGENT_LEVEL_NODES_PER_CYCLE:
            self._fail("too_many_nodes", "at most three Agent-level nodes are allowed")
        question_ids = [question.question_id for question in plan.questions]
        node_ids = [node.node_id for node in plan.nodes]
        if len(question_ids) != len(set(question_ids)):
            self._fail("duplicate_question_id", "question IDs must be unique")
        if len(node_ids) != len(set(node_ids)):
            self._fail("duplicate_node_id", "node IDs must be unique")
        repeated_questions = used_question_ids.intersection(question_ids)
        if repeated_questions:
            self._fail(
                "duplicate_question_id_across_cycles",
                f"question IDs have already been used: {sorted(repeated_questions)}",
            )
        repeated_nodes = used_node_ids.intersection(node_ids)
        if repeated_nodes:
            self._fail(
                "duplicate_node_id_across_cycles",
                f"node IDs have already been used: {sorted(repeated_nodes)}",
            )
        question_id_set = set(question_ids)
        node_id_set = set(node_ids)
        record_sets = {item.record_set_id: item for item in package.record_sets}
        request_hashes: list[str] = []
        total_cost = 0
        for node in plan.nodes:
            if node.question_id not in question_id_set:
                self._fail("unknown_question", f"unknown question: {node.question_id}")
            if not node.purpose.strip():
                self._fail("missing_purpose", f"node {node.node_id} has no purpose")
            if any(dependency not in node_id_set for dependency in node.dependencies):
                self._fail("unknown_dependency", f"node {node.node_id} has an unknown dependency")
            try:
                tool = self.tool_registry.get(node.tool_name)
            except KeyError as exc:
                raise PlanValidationError("unknown_tool", str(exc)) from exc
            if not tool.enabled:
                self._fail("tool_disabled", f"analysis tool {node.tool_name} is disabled")
            if not bool(getattr(access_scope, tool.required_scope)):
                self._fail(
                    "scope_not_authorized",
                    f"data scope {tool.required_scope} is not authorized",
                )
            try:
                method = self.method_registry.get(node.analysis_method)
            except KeyError as exc:
                raise PlanValidationError("unknown_analysis_method", str(exc)) from exc
            if method.tool_name != node.tool_name or node.analysis_method not in tool.method_names:
                self._fail(
                    "method_tool_mismatch",
                    f"analysis method {node.analysis_method} does not belong to {node.tool_name}",
                )
            self._validate_inputs(node, method, record_sets)
            request_hash = self._request_hash(node)
            if request_hash in request_hashes:
                self._fail("duplicate_request", "duplicate semantic requests are not allowed")
            request_hashes.append(request_hash)
            total_cost += method.cost
        if total_cost > MAX_PLAN_COST:
            self._fail("cost_budget_exceeded", "plan cost exceeds the cycle budget")
        execution_order = self._topological_order(plan)
        return ValidatedAnalysisPlan(
            plan=plan,
            execution_order=execution_order,
            request_hashes=tuple(request_hashes),
            total_cost=total_cost,
        )

    def _validate_inputs(self, node, spec, record_sets):
        allowed_keys = {
            "verify_temporal_change": {"record_set_id", "metric_codes", "side"},
            "verify_side_segment_difference": {"record_set_id", "metric_codes", "target_side"},
            "verify_cross_metric_cochange": {"record_set_id", "metric_codes", "side"},
            "verify_exclusion_robustness": {"record_set_id", "metric_codes", "side"},
            "quality_scope_check": set(),
        }[node.analysis_method]
        unknown_keys = set(node.inputs) - allowed_keys
        if unknown_keys:
            self._fail(
                "unknown_analysis_method_input",
                f"unknown inputs for {node.analysis_method}: {sorted(unknown_keys)}",
            )
        if not spec.requires_record_set:
            if node.inputs:
                self._fail("unexpected_inputs", "quality_scope_check accepts no inputs")
            return
        record_set_id = node.inputs.get("record_set_id")
        if record_set_id not in record_sets:
            self._fail("unknown_record_set", f"unknown RecordSet: {record_set_id}")
        metric_codes = node.inputs.get("metric_codes")
        if not isinstance(metric_codes, (list, tuple)):
            self._fail("invalid_metric_codes", "metric_codes must be a list")
        if not spec.min_metrics <= len(metric_codes) <= spec.max_metrics:
            self._fail("invalid_metric_count", "analysis method metric count is invalid")
        if len(metric_codes) != len(set(metric_codes)):
            self._fail("duplicate_metric", "metric_codes must be unique")
        record_set = record_sets[record_set_id]
        for metric_code in metric_codes:
            if metric_code not in record_set.metric_codes:
                self._fail(
                    "metric_not_in_record_set",
                    f"metric {metric_code} is not available in {record_set_id}",
                )
        side = node.inputs.get("side")
        target_side = node.inputs.get("target_side")
        if side is not None and side not in {"left", "right"}:
            self._fail("invalid_side", "side must be left or right")
        if target_side is not None and target_side not in {"left", "right"}:
            self._fail("invalid_side", "target_side must be left or right")
        if spec.requires_side:
            available_sides = {record.side for record in record_set.records}
            if not {"left", "right"}.issubset(available_sides):
                self._fail("side_dimension_unavailable", "both sides are required")

    def _topological_order(self, plan: SmallAnalysisPlan) -> tuple[str, ...]:
        dependencies = {
            node.node_id: set(node.dependencies) for node in plan.nodes
        }
        order: list[str] = []
        while dependencies:
            ready = sorted(
                node_id
                for node_id, required in dependencies.items()
                if not required
            )
            if not ready:
                self._fail("cyclic_dependencies", "analysis node dependencies are cyclic")
            for node_id in ready:
                order.append(node_id)
                dependencies.pop(node_id)
            for required in dependencies.values():
                required.difference_update(ready)
        return tuple(order)

    def _request_hash(self, node) -> str:
        payload = {
            "tool": node.tool_name,
            "method": node.analysis_method,
            "inputs": node.inputs,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _fail(self, code: str, message: str):
        raise PlanValidationError(code, message)


class ActionValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ActionValidator:
    """Validate one sequential decision while reusing the existing plan boundary."""

    def __init__(
        self,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
        *,
        available_skill_references: tuple[str, ...] = (
            "references/evidence-guidelines.md",
        ),
    ):
        self.tool_registry = tool_registry or AnalysisToolRegistry()
        self.method_registry = method_registry or AnalysisMethodRegistry()
        self.plan_validator = PlanValidator(
            self.tool_registry,
            self.method_registry,
        )
        self.available_skill_references = frozenset(available_skill_references)

    def validate_decision(
        self,
        decision: NextAnalysisAction | LoadSkillResource | StopAnalysis,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        seen_request_hashes: frozenset[str] = frozenset(),
        seen_action_ids: frozenset[str] = frozenset(),
        seen_hypothesis_ids: frozenset[str] = frozenset(),
        loaded_skill_references: frozenset[str] = frozenset(),
        remaining_tool_calls: int = 1,
        remaining_skill_reference_loads: int = 1,
    ) -> ValidatedAnalysisAction | LoadSkillResource | StopAnalysis:
        if isinstance(decision, NextAnalysisAction):
            return self.validate_action(
                decision,
                package,
                access_scope,
                seen_request_hashes=seen_request_hashes,
                seen_action_ids=seen_action_ids,
                seen_hypothesis_ids=seen_hypothesis_ids,
                remaining_tool_calls=remaining_tool_calls,
            )
        if isinstance(decision, LoadSkillResource):
            return self.validate_skill_resource(
                decision,
                loaded_skill_references=loaded_skill_references,
                remaining_skill_reference_loads=remaining_skill_reference_loads,
            )
        return decision

    def validate_action(
        self,
        action: NextAnalysisAction,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        seen_request_hashes: frozenset[str] = frozenset(),
        seen_action_ids: frozenset[str] = frozenset(),
        seen_hypothesis_ids: frozenset[str] = frozenset(),
        remaining_tool_calls: int = 1,
    ) -> ValidatedAnalysisAction:
        if remaining_tool_calls <= 0:
            self._fail("tool_budget_exhausted", "no analysis Tool calls remain")
        input_metric_codes = tuple(action.inputs.get("metric_codes", ()))
        if input_metric_codes != action.hypothesis.metric_codes:
            self._fail(
                "hypothesis_metric_mismatch",
                "hypothesis metric_codes must match the analysis action inputs",
            )
        try:
            method = self.method_registry.get(action.analysis_method)
        except KeyError as exc:
            raise ActionValidationError("unknown_analysis_method", str(exc)) from exc
        if action.hypothesis.target_predicate not in method.predicate_names:
            self._fail(
                "predicate_method_mismatch",
                "target Predicate is not produced by the selected analysis method",
            )
        question = AnalysisQuestion(
            question_id=action.hypothesis.hypothesis_id,
            description=action.hypothesis.statement,
            dimensions=action.hypothesis.dimensions,
            metric_codes=action.hypothesis.metric_codes,
            reason=action.hypothesis.reason,
            stop_condition=action.hypothesis.success_condition,
        )
        node = AnalysisNode(
            node_id=action.action_id,
            tool_name=action.tool_name,
            analysis_method=action.analysis_method,
            inputs=action.inputs,
            question_id=action.hypothesis.hypothesis_id,
            purpose=action.purpose,
        )
        try:
            validated = self.plan_validator.validate(
                SmallAnalysisPlan(questions=(question,), nodes=(node,)),
                package,
                access_scope,
                used_question_ids=seen_hypothesis_ids,
                used_node_ids=seen_action_ids,
            )
        except PlanValidationError as exc:
            raise ActionValidationError(exc.code, str(exc)) from exc
        request_hash = validated.request_hashes[0]
        if request_hash in seen_request_hashes:
            self._fail(
                "duplicate_action_request",
                "the semantic analysis request has already been executed",
            )
        tool = self.tool_registry.get(action.tool_name)
        return ValidatedAnalysisAction(
            action=action,
            question=question,
            node=node,
            required_scope=tool.required_scope,
            request_hash=request_hash,
            cost=validated.total_cost,
        )

    def validate_skill_resource(
        self,
        decision: LoadSkillResource,
        *,
        loaded_skill_references: frozenset[str] = frozenset(),
        remaining_skill_reference_loads: int = 1,
    ) -> LoadSkillResource:
        if remaining_skill_reference_loads <= 0:
            self._fail(
                "skill_reference_budget_exhausted",
                "no Skill reference loads remain",
            )
        if decision.reference_id not in self.available_skill_references:
            self._fail(
                "unknown_skill_reference",
                f"Skill reference is not available: {decision.reference_id}",
            )
        if decision.reference_id in loaded_skill_references:
            self._fail(
                "duplicate_skill_reference",
                f"Skill reference is already loaded: {decision.reference_id}",
            )
        return decision

    def _fail(self, code: str, message: str):
        raise ActionValidationError(code, message)


class ClaimValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ClaimRepairValidationError(ValueError):
    code = "repair_scope_violation"


class ClaimRepairValidator:
    _NUMERIC_ERRORS = {
        "unbound_numeric_literal",
        "numeric_placeholder_mismatch",
    }
    _PREDICATE_ERRORS = {"predicate_binding_mismatch"}
    _CONDITIONAL_FIELDS = {
        "unknown_fact": {"fact_refs", "numeric_bindings"},
        "unknown_evidence": {
            "evidence_refs",
            "tool_run_ids",
            "predicate_bindings",
            "numeric_bindings",
        },
        "unknown_tool_run": {"tool_run_ids"},
        "descriptive_claim_without_fact": {
            "fact_refs",
            "numeric_bindings",
        },
        "derived_claim_without_evidence": {
            "evidence_refs",
            "tool_run_ids",
            "predicate_bindings",
            "numeric_bindings",
        },
        "evidence_tool_run_unbound": {"tool_run_ids"},
        "predicate_evidence_unbound": {
            "evidence_refs",
            "tool_run_ids",
            "predicate_bindings",
        },
        "unknown_predicate_evidence": {"predicate_bindings"},
    }
    _NUMERIC_UNIT = (
        r"(?:jumps/min|steps/min|steps/s|m/s|次/分|厘米|毫米|公斤|"
        r"秒|ms|cm|mm|kg|count|s|m|米|次|%)"
    )
    _NUMBER_OR_PLACEHOLDER = re.compile(
        r"(?:\{[A-Za-z_][A-Za-z0-9_]*\}|"
        r"(?<![A-Za-z0-9_])[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
        rf"\s*{_NUMERIC_UNIT}?)"
    )
    _NUMERIC_LITERAL = re.compile(
        r"(?P<number>[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
        rf"\s*(?P<unit>{_NUMERIC_UNIT})?"
    )
    _UNIT_ALIASES = {
        "秒": "s",
        "米": "m",
        "厘米": "cm",
        "毫米": "mm",
        "公斤": "kg",
        "次": "count",
        "次/分": "count/min",
        "jumps/min": "count/min",
        "steps/min": "count/min",
    }

    @classmethod
    def can_repair(cls, error_code: str) -> bool:
        return (
            error_code in cls._NUMERIC_ERRORS
            or error_code in cls._PREDICATE_ERRORS
            or error_code in cls._CONDITIONAL_FIELDS
        )

    def validate(
        self,
        original: DraftAnalysisPackage,
        repaired: DraftAnalysisPackage,
        error_code: str,
        package: ReportDataPackage,
        evidence: tuple[EvidenceBundle, ...],
    ) -> None:
        if not self.can_repair(error_code):
            self._fail(f"Claim error is not repairable: {error_code}")
        if (
            original.summary != repaired.summary
            or original.scope_expansion_suggestions
            != repaired.scope_expansion_suggestions
            or original.overall_limitations != repaired.overall_limitations
        ):
            self._fail("repair changed package-level content")
        if len(original.claims) != len(repaired.claims):
            self._fail("repair changed the Claim count")

        changed = []
        for before, after in zip(original.claims, repaired.claims):
            if (
                before.claim_id != after.claim_id
                or before.claim_type != after.claim_type
                or before.limitations != after.limitations
            ):
                self._fail("repair changed Claim identity or type")
            if before != after:
                changed.append((before, after))
        if len(changed) != 1:
            self._fail("repair must change exactly one Claim")

        before, after = changed[0]
        changed_fields = {
            field_name
            for field_name in type(before).model_fields
            if getattr(before, field_name) != getattr(after, field_name)
        }
        if error_code in self._NUMERIC_ERRORS:
            self._validate_numeric_repair(
                before,
                after,
                changed_fields,
                package,
                evidence,
            )
            return

        allowed_fields = (
            {"predicate_bindings"}
            if error_code in self._PREDICATE_ERRORS
            else self._CONDITIONAL_FIELDS[error_code]
        )
        if not changed_fields or not changed_fields.issubset(allowed_fields):
            self._fail(
                f"repair changed fields outside the {error_code} allowance"
            )
        if before.text_template != after.text_template:
            self._fail("non-numeric repair changed Claim text")

        fact_map, evidence_map, predicate_map = self._source_maps(
            package, evidence
        )
        original_metrics = self._claim_metric_codes(
            before, fact_map, evidence_map, predicate_map
        )
        if not original_metrics:
            self._fail("original Claim has no resolvable metric set")
        repaired_metrics = self._claim_metric_codes(
            after, fact_map, evidence_map, predicate_map
        )
        if not repaired_metrics or not repaired_metrics.issubset(
            original_metrics
        ):
            self._fail("repair introduced metrics outside the original Claim")
        if error_code in {
            "predicate_binding_mismatch",
            "unknown_predicate_evidence",
        }:
            original_evidence_refs = set(before.evidence_refs)
            for binding in after.predicate_bindings:
                resolved = predicate_map.get(binding.predicate_evidence_ref)
                if resolved is None or resolved[0].evidence_id not in (
                    original_evidence_refs
                ):
                    self._fail(
                        "repair selected Predicate Evidence outside original Evidence refs"
                    )

    def _validate_numeric_repair(
        self,
        before,
        after,
        changed_fields,
        package,
        evidence,
    ) -> None:
        if not changed_fields or not changed_fields.issubset(
            {"text_template", "numeric_bindings"}
        ):
            self._fail("numeric repair changed non-numeric Claim fields")
        before_skeleton = self._NUMBER_OR_PLACEHOLDER.sub(
            "<NUM>", before.text_template
        )
        after_skeleton = self._NUMBER_OR_PLACEHOLDER.sub(
            "<NUM>", after.text_template
        )
        if before_skeleton != after_skeleton:
            self._fail("numeric repair rewrote non-numeric Claim text")
        before_tokens = tuple(
            match.group(0)
            for match in self._NUMBER_OR_PLACEHOLDER.finditer(
                before.text_template
            )
        )
        after_tokens = tuple(
            match.group(0)
            for match in self._NUMBER_OR_PLACEHOLDER.finditer(
                after.text_template
            )
        )
        if len(before_tokens) != len(after_tokens):
            self._fail("numeric repair changed the numeric token count")
        fact_refs = set(before.fact_refs)
        evidence_refs = set(before.evidence_refs)
        after_bindings = {}
        for binding in after.numeric_bindings:
            if binding.binding_id in after_bindings:
                self._fail("numeric repair introduced duplicate bindings")
            allowed = (
                fact_refs
                if binding.source_type == "fact"
                else evidence_refs
            )
            if binding.source_ref not in allowed:
                self._fail(
                    "numeric repair used a source outside original Claim refs"
                )
            after_bindings[binding.binding_id] = binding
        before_bindings = {
            binding.binding_id: binding for binding in before.numeric_bindings
        }
        fact_map, evidence_map, _ = self._source_maps(package, evidence)
        for before_token, after_token in zip(before_tokens, after_tokens):
            if not after_token.startswith("{"):
                self._fail(
                    "numeric repair must replace numeric surfaces with placeholders"
                )
            before_surface = self._numeric_token_surface(
                before_token,
                before_bindings,
                fact_map,
                evidence_map,
            )
            after_surface = self._numeric_token_surface(
                after_token,
                after_bindings,
                fact_map,
                evidence_map,
            )
            if before_surface != after_surface:
                self._fail(
                    "numeric repair changed the rendered numeric value or unit"
                )

    def _numeric_token_surface(
        self,
        token,
        bindings,
        fact_map,
        evidence_map,
    ) -> str:
        if token.startswith("{"):
            binding = bindings.get(token[1:-1])
            if binding is None:
                self._fail(
                    "numeric repair cannot establish the original placeholder value"
                )
            value, unit = self._numeric_binding_value(
                binding, fact_map, evidence_map
            )
        else:
            match = self._NUMERIC_LITERAL.fullmatch(token)
            if match is None:
                self._fail("numeric repair contains an invalid numeric token")
            value = float(match.group("number"))
            unit = match.group("unit") or ""
        normalized_unit = self._UNIT_ALIASES.get(unit, unit)
        return format_numeric_value(value, normalized_unit).strip()

    def _numeric_binding_value(self, binding, fact_map, evidence_map):
        if binding.source_type == "fact":
            fact = fact_map.get(binding.source_ref)
            if (
                fact is None
                or fact.state != "present"
                or fact.value is None
                or binding.value_key is not None
            ):
                self._fail("numeric repair uses an unresolved Fact value")
            return fact.value, fact.unit
        item = evidence_map.get(binding.source_ref)
        if (
            item is None
            or binding.value_key is None
            or binding.value_key not in item.numeric_values
            or binding.value_key not in item.numeric_units
        ):
            self._fail("numeric repair uses an unresolved Evidence value")
        return (
            item.numeric_values[binding.value_key],
            item.numeric_units[binding.value_key],
        )

    def _source_maps(self, package, evidence):
        fact_map = {fact.fact_id: fact for fact in package.scalar_facts}
        evidence_map = {}
        predicate_map = {}
        for bundle in evidence:
            for item in bundle.items:
                evidence_map.setdefault(item.evidence_id, item)
                for predicate in item.predicates:
                    if predicate.predicate_evidence_id:
                        predicate_map.setdefault(
                            predicate.predicate_evidence_id,
                            (item, predicate),
                        )
        return fact_map, evidence_map, predicate_map

    def _claim_metric_codes(
        self, claim, fact_map, evidence_map, predicate_map
    ) -> set[str]:
        metrics = set()
        for ref in claim.fact_refs:
            fact = fact_map.get(ref)
            metric = getattr(fact, "metric_code", None)
            if metric:
                metrics.add(metric)
        for ref in claim.evidence_refs:
            item = evidence_map.get(ref)
            if item is not None:
                for predicate in item.predicates:
                    metrics.update(predicate.metric_codes)
        for binding in claim.numeric_bindings:
            if binding.source_type == "fact":
                fact = fact_map.get(binding.source_ref)
                metric = getattr(fact, "metric_code", None)
                if metric:
                    metrics.add(metric)
            else:
                item = evidence_map.get(binding.source_ref)
                if item is not None:
                    for predicate in item.predicates:
                        metrics.update(predicate.metric_codes)
        for binding in claim.predicate_bindings:
            resolved = predicate_map.get(binding.predicate_evidence_ref)
            if resolved is not None:
                metrics.update(resolved[1].metric_codes)
        return metrics

    def _fail(self, message: str) -> None:
        raise ClaimRepairValidationError(message)


class ClaimValidator:
    _FORBIDDEN_TERMS = (
        "导致",
        "引起",
        "证明了",
        "受伤风险",
        "伤病风险",
        "诊断",
        "治疗",
        "训练处方",
        "causes",
        "diagnosis",
        "injury risk",
    )

    def validate(
        self,
        draft: DraftAnalysisPackage,
        package: ReportDataPackage,
        evidence: tuple[EvidenceBundle, ...],
        access_scope: DataAccessScope,
    ) -> ValidatedAnalysisPackage:
        fact_map = {fact.fact_id: fact for fact in package.scalar_facts}
        evidence_map = {}
        predicate_evidence_map = {}
        run_map = {}
        provenance_ids: set[str] = set()
        for bundle in evidence:
            if bundle.package_id != package.metadata.package_id or bundle.package_digest != package.metadata.package_digest:
                self._fail("snapshot_mismatch", "evidence belongs to another report snapshot")
            for item in bundle.items:
                if item.evidence_id in evidence_map:
                    self._fail(
                        "duplicate_evidence_id",
                        f"duplicate Evidence ID: {item.evidence_id}",
                    )
                evidence_map[item.evidence_id] = item
            for run in bundle.tool_runs:
                if run.tool_run_id in run_map:
                    self._fail(
                        "duplicate_tool_run_id",
                        f"duplicate Tool Run ID: {run.tool_run_id}",
                    )
                run_map[run.tool_run_id] = run
            for provenance in bundle.provenance:
                if provenance.provenance_id in provenance_ids:
                    self._fail(
                        "duplicate_provenance_id",
                        f"duplicate Provenance ID: {provenance.provenance_id}",
                    )
                provenance_ids.add(provenance.provenance_id)
            for item in bundle.items:
                for predicate in item.predicates:
                    if not predicate.predicate_evidence_id:
                        self._fail(
                            "missing_predicate_evidence_id",
                            f"Evidence {item.evidence_id} has an unaddressable predicate",
                        )
                    if predicate.predicate_evidence_id in predicate_evidence_map:
                        self._fail(
                            "duplicate_predicate_evidence_id",
                            f"duplicate Predicate Evidence ID: {predicate.predicate_evidence_id}",
                        )
                    predicate_evidence_map[predicate.predicate_evidence_id] = (
                        item,
                        predicate,
                    )
        validated_claims = []
        claim_ids: set[str] = set()
        for claim in draft.claims:
            if claim.claim_id in claim_ids:
                self._fail("duplicate_claim_id", f"duplicate claim ID: {claim.claim_id}")
            claim_ids.add(claim.claim_id)
            self._validate_language(claim.text_template)
            self._require_unique_refs(claim.fact_refs, "duplicate_fact_ref")
            self._require_unique_refs(
                claim.evidence_refs, "duplicate_evidence_ref"
            )
            self._require_unique_refs(
                claim.tool_run_ids, "duplicate_tool_run_ref"
            )
            referenced_facts = self._resolve_refs(claim.fact_refs, fact_map, "unknown_fact")
            referenced_evidence = self._resolve_refs(claim.evidence_refs, evidence_map, "unknown_evidence")
            referenced_runs = self._resolve_refs(claim.tool_run_ids, run_map, "unknown_tool_run")
            for fact in referenced_facts:
                if fact.state != "present":
                    self._fail("missing_fact", f"claim references missing fact {fact.fact_id}")
            for run in referenced_runs:
                if not bool(getattr(access_scope, run.data_scope)):
                    self._fail("scope_not_authorized", f"tool run used unauthorized scope {run.data_scope}")
            if claim.claim_type == "descriptive":
                if not claim.fact_refs:
                    self._fail("descriptive_claim_without_fact", "descriptive claims require a Fact")
            else:
                if not claim.evidence_refs or not claim.tool_run_ids or not claim.predicate_bindings:
                    self._fail("derived_claim_without_evidence", "derived claims require Evidence, Tool Run and Predicate")
            if claim.claim_type == "synthesis" and len(set(claim.evidence_refs)) < 2:
                self._fail("synthesis_requires_multiple_evidence", "synthesis claims require at least two Evidence items")
            expected_tool_run_ids = {
                item.tool_run_id for item in referenced_evidence
            }
            if set(claim.tool_run_ids) != expected_tool_run_ids:
                self._fail(
                    "evidence_tool_run_unbound",
                    "tool_run_ids must exactly match the Tool Runs for referenced Evidence",
                )
            self._validate_predicates(
                claim.predicate_bindings,
                predicate_evidence_map,
                set(claim.evidence_refs),
            )
            numeric_bindings = self._validate_numeric_bindings(
                claim.numeric_bindings,
                fact_map,
                evidence_map,
                set(claim.fact_refs),
                set(claim.evidence_refs),
            )
            placeholders = self._parse_placeholders(claim.text_template)
            binding_ids = {binding.binding_id for binding in numeric_bindings}
            if placeholders != binding_ids:
                self._fail("numeric_placeholder_mismatch", "numeric placeholders must exactly match NumericBindings")
            text_without_placeholders = re.sub(
                r"\{[A-Za-z_][A-Za-z0-9_]*\}",
                "",
                claim.text_template,
            )
            if re.search(r"\d", text_without_placeholders):
                self._fail("unbound_numeric_literal", "Claim text contains an unbound numeric literal")
            validated_claims.append(
                ValidatedAnalysisClaim(
                    claim_id=claim.claim_id,
                    claim_type=claim.claim_type,
                    text_template=claim.text_template,
                    fact_refs=claim.fact_refs,
                    evidence_refs=claim.evidence_refs,
                    tool_run_ids=claim.tool_run_ids,
                    predicate_bindings=claim.predicate_bindings,
                    numeric_bindings=tuple(numeric_bindings),
                    limitations=tuple(
                        dict.fromkeys(
                            (*claim.limitations, *(limitation for item in referenced_evidence for limitation in item.limitations))
                        )
                    ),
                )
            )
        return ValidatedAnalysisPackage(
            summary="基于本次测试记录的受限证据分析。",
            claims=tuple(validated_claims),
            scope_expansion_suggestions=draft.scope_expansion_suggestions,
            overall_limitations=draft.overall_limitations,
        )

    def _validate_language(self, text: str):
        lowered = text.lower()
        for term in self._FORBIDDEN_TERMS:
            if term.lower() in lowered:
                self._fail("forbidden_claim_language", f"forbidden term in claim: {term}")

    def _resolve_refs(self, refs, mapping, code):
        result = []
        for ref in refs:
            if ref not in mapping:
                self._fail(code, f"unknown reference: {ref}")
            result.append(mapping[ref])
        return result

    def _require_unique_refs(self, refs, code):
        if len(refs) != len(set(refs)):
            self._fail(code, "Claim references must be unique")

    def _parse_placeholders(self, text: str) -> set[str]:
        matches = tuple(re.finditer(r"\{([^{}]+)\}", text))
        without_matches = re.sub(r"\{[^{}]+\}", "", text)
        if "{" in without_matches or "}" in without_matches:
            self._fail(
                "invalid_numeric_placeholder",
                "Claim text contains malformed or escaped braces",
            )
        placeholders = set()
        for match in matches:
            name = match.group(1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                self._fail(
                    "invalid_numeric_placeholder",
                    f"invalid numeric placeholder: {name}",
                )
            placeholders.add(name)
        return placeholders

    def _validate_predicates(
        self,
        bindings: tuple[PredicateBinding, ...],
        predicate_evidence_map,
        claim_evidence_refs: set[str],
    ):
        for binding in bindings:
            resolved = predicate_evidence_map.get(
                binding.predicate_evidence_ref
            )
            if resolved is None:
                self._fail(
                    "unknown_predicate_evidence",
                    "unknown Predicate Evidence: "
                    f"{binding.predicate_evidence_ref}",
                )
            item, predicate = resolved
            if item.evidence_id not in claim_evidence_refs:
                self._fail(
                    "predicate_evidence_unbound",
                    f"Predicate Evidence belongs to unreferenced Evidence {item.evidence_id}",
                )
            if predicate.predicate != binding.predicate:
                self._fail(
                    "predicate_binding_mismatch",
                    "Predicate Binding name does not match the exact "
                    "Predicate Evidence",
                )
            if item.analysis_status != "conclusive" or not predicate.supported:
                self._fail("unsupported_predicate", f"predicate is not supported: {binding.predicate}")

    def _validate_numeric_bindings(
        self,
        bindings,
        fact_map,
        evidence_map,
        claim_fact_refs,
        claim_evidence_refs,
    ):
        validated = []
        ids: set[str] = set()
        for binding in bindings:
            if binding.binding_id in ids:
                self._fail("duplicate_numeric_binding", f"duplicate binding: {binding.binding_id}")
            ids.add(binding.binding_id)
            if binding.source_type == "fact":
                if binding.source_ref not in claim_fact_refs:
                    self._fail(
                        "numeric_fact_source_unbound",
                        f"numeric Fact source is not referenced by Claim: {binding.source_ref}",
                    )
                fact = fact_map.get(binding.source_ref)
                if fact is None or fact.state != "present" or fact.value is None:
                    self._fail("invalid_numeric_fact", f"invalid numeric Fact: {binding.source_ref}")
                if binding.value_key is not None:
                    self._fail("unexpected_value_key", "Fact bindings cannot specify value_key")
                value = fact.value
                unit = fact.unit
            else:
                if binding.source_ref not in claim_evidence_refs:
                    self._fail(
                        "numeric_evidence_source_unbound",
                        f"numeric Evidence source is not referenced by Claim: {binding.source_ref}",
                    )
                item = evidence_map.get(binding.source_ref)
                if item is None or binding.value_key is None:
                    self._fail("invalid_numeric_evidence", f"invalid numeric Evidence: {binding.source_ref}")
                if binding.value_key not in item.numeric_values or binding.value_key not in item.numeric_units:
                    self._fail("unknown_numeric_value", f"unknown evidence numeric value: {binding.value_key}")
                value = item.numeric_values[binding.value_key]
                unit = item.numeric_units[binding.value_key]
            validated.append(
                ValidatedNumericBinding(
                    binding_id=binding.binding_id,
                    value=value,
                    unit=unit,
                    source_ref=binding.source_ref,
                )
            )
        return validated

    def _fail(self, code: str, message: str):
        raise ClaimValidationError(code, message)
