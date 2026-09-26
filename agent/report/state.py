"""Deterministic state transitions for sequential Report Agent decisions."""

from __future__ import annotations

from reporting.models import (
    ActionRejected,
    AnalysisFailureRecord,
    EvidenceBundle,
    EvidenceProduced,
    HypothesisEvaluation,
    LoadSkillResource,
    StopAnalysis,
    SequentialAnalysisState,
    ToolExecutionFailed,
    ValidatedAnalysisAction,
)


MAX_AGENT_DECISIONS = 9
MAX_ANALYSIS_TOOL_CALLS = 5
MAX_SKILL_REFERENCE_LOADS = 3


class AnalysisStateReductionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AnalysisStateReducer:
    def begin_action(
        self,
        state: SequentialAnalysisState,
        action: ValidatedAnalysisAction,
    ) -> SequentialAnalysisState:
        self._require_decision_budget(state)
        if state.tool_call_count >= MAX_ANALYSIS_TOOL_CALLS:
            self._fail("tool_budget_exhausted", "no analysis Tool calls remain")
        action_id = action.action.action_id
        if action_id in state.action_ids:
            self._fail(
                "duplicate_action_id",
                f"action ID has already been used: {action_id}",
            )
        hypothesis_id = action.action.hypothesis.hypothesis_id
        if any(
            item.target.hypothesis_id == hypothesis_id
            for item in state.hypotheses
        ):
            self._fail(
                "duplicate_hypothesis_id",
                f"hypothesis ID has already been used: {hypothesis_id}",
            )
        if action.request_hash in state.seen_request_hashes:
            self._fail(
                "duplicate_action_request",
                "the semantic analysis request has already been executed",
            )
        evaluation = HypothesisEvaluation(
            target=action.action.hypothesis,
            status="active",
            request_hash=action.request_hash,
        )
        return state.model_copy(
            update={
                "decision_count": state.decision_count + 1,
                "tool_call_count": state.tool_call_count + 1,
                "action_ids": (*state.action_ids, action_id),
                "question_ids": tuple(
                    dict.fromkeys((*state.question_ids, hypothesis_id))
                ),
                "seen_request_hashes": (
                    *state.seen_request_hashes,
                    action.request_hash,
                ),
                "hypotheses": (*state.hypotheses, evaluation),
            }
        )

    def apply_evidence(
        self,
        state: SequentialAnalysisState,
        action: ValidatedAnalysisAction,
        evidence: EvidenceBundle,
    ) -> SequentialAnalysisState:
        hypothesis_id = action.action.hypothesis.hypothesis_id
        matching_indexes = [
            index
            for index, item in enumerate(state.hypotheses)
            if item.target.hypothesis_id == hypothesis_id
        ]
        if len(matching_indexes) != 1:
            self._fail(
                "unknown_active_hypothesis",
                f"active hypothesis is not uniquely registered: {hypothesis_id}",
            )
        hypothesis_index = matching_indexes[0]
        current = state.hypotheses[hypothesis_index]
        if current.status != "active":
            self._fail(
                "hypothesis_already_resolved",
                f"hypothesis is already {current.status}: {hypothesis_id}",
            )
        if len(evidence.items) != 1:
            self._fail(
                "unexpected_evidence_count",
                "a sequential analysis action must produce exactly one Evidence item",
            )
        item = evidence.items[0]
        if item.evidence_id in state.evidence_refs:
            self._fail(
                "duplicate_evidence_id",
                f"Evidence has already been consumed: {item.evidence_id}",
            )
        self._validate_evidence_identity(action, item)
        target = action.action.hypothesis
        predicates = [
            predicate
            for predicate in item.predicates
            if predicate.predicate == target.target_predicate
            and predicate.metric_codes == target.metric_codes
        ]
        if len(predicates) != 1:
            self._fail(
                "target_predicate_not_resolved",
                "Evidence does not contain exactly one matching target Predicate",
            )
        predicate = predicates[0]
        if not predicate.predicate_evidence_id:
            self._fail(
                "missing_predicate_evidence_id",
                "target Predicate has no stable Evidence reference",
            )
        if item.analysis_status == "inconclusive":
            status = "inconclusive"
        elif predicate.supported:
            status = "supported"
        else:
            status = "not_supported"
        resolved = current.model_copy(
            update={
                "status": status,
                "evidence_refs": (item.evidence_id,),
                "predicate_evidence_refs": (
                    predicate.predicate_evidence_id,
                ),
            }
        )
        hypotheses = list(state.hypotheses)
        hypotheses[hypothesis_index] = resolved
        predicate_key = ":".join(
            (target.target_predicate, *target.metric_codes)
        )
        supported = state.supported_predicates
        rejected = state.rejected_predicates
        inconclusive = state.inconclusive_predicates
        if status == "supported":
            supported = tuple(dict.fromkeys((*supported, predicate_key)))
        elif status == "not_supported":
            rejected = tuple(dict.fromkeys((*rejected, predicate_key)))
        else:
            inconclusive = tuple(
                dict.fromkeys((*inconclusive, predicate_key))
            )
        return state.model_copy(
            update={
                "hypotheses": tuple(hypotheses),
                "supported_predicates": supported,
                "rejected_predicates": rejected,
                "inconclusive_predicates": inconclusive,
                "evidence_refs": tuple(
                    dict.fromkeys((*state.evidence_refs, item.evidence_id))
                ),
                "limitations": tuple(
                    dict.fromkeys((*state.limitations, *item.limitations))
                ),
            }
        )

    def apply_evidence_outcome(
        self,
        state: SequentialAnalysisState,
        outcome: EvidenceProduced,
    ) -> SequentialAnalysisState:
        resolved = self.apply_evidence(
            state,
            outcome.action,
            outcome.evidence,
        )
        return resolved.model_copy(
            update={
                "tool_retry_count": (
                    resolved.tool_retry_count
                    + max(0, outcome.attempt_count - 1)
                )
            }
        )

    def record_skill_resource(
        self,
        state: SequentialAnalysisState,
        decision: LoadSkillResource,
    ) -> SequentialAnalysisState:
        self._require_decision_budget(state)
        if len(state.loaded_skill_references) >= MAX_SKILL_REFERENCE_LOADS:
            self._fail(
                "skill_reference_budget_exhausted",
                "no Skill reference loads remain",
            )
        if decision.reference_id in state.loaded_skill_references:
            self._fail(
                "duplicate_skill_reference",
                f"Skill reference is already loaded: {decision.reference_id}",
            )
        return state.model_copy(
            update={
                "decision_count": state.decision_count + 1,
                "loaded_skill_references": (
                    *state.loaded_skill_references,
                    decision.reference_id,
                ),
            }
        )

    def record_stop(
        self,
        state: SequentialAnalysisState,
        decision: StopAnalysis,
    ) -> SequentialAnalysisState:
        self._require_decision_budget(state)
        return state.model_copy(
            update={
                "decision_count": state.decision_count + 1,
                "stop_reason_code": decision.reason_code,
                "unresolved_questions": tuple(
                    dict.fromkeys(
                        (
                            *state.unresolved_questions,
                            *decision.unresolved_hypothesis_ids,
                        )
                    )
                ),
            }
        )

    def record_deadline_stop(
        self,
        state: SequentialAnalysisState,
        reason_code: str,
    ) -> SequentialAnalysisState:
        if state.stop_reason_code is not None:
            return state
        return state.model_copy(
            update={
                "stop_reason_code": reason_code,
                "limitations": tuple(
                    dict.fromkeys((*state.limitations, reason_code))
                ),
            }
        )

    def record_action_rejection(
        self,
        state: SequentialAnalysisState,
        outcome: ActionRejected,
    ) -> SequentialAnalysisState:
        self._require_decision_budget(state)
        correction_count = state.action_correction_count
        stop_reason_code = state.stop_reason_code
        if outcome.correction_allowed:
            correction_count += 1
        else:
            stop_reason_code = "action_correction_exhausted"
        failure = AnalysisFailureRecord(
            failure_type="action_rejected",
            action_id=outcome.action.action_id,
            error_code=outcome.error_code,
            retryable=outcome.correction_allowed,
            attempt_count=0,
        )
        return state.model_copy(
            update={
                "decision_count": state.decision_count + 1,
                "action_correction_count": correction_count,
                "failures": (*state.failures, failure),
                "stop_reason_code": stop_reason_code,
            }
        )

    def record_skill_rejection(
        self,
        state: SequentialAnalysisState,
        decision: LoadSkillResource,
        error_code: str,
    ) -> tuple[SequentialAnalysisState, bool]:
        self._require_decision_budget(state)
        correction_allowed = state.action_correction_count < 2
        failure = AnalysisFailureRecord(
            failure_type="skill_resource_rejected",
            action_id=decision.reference_id,
            error_code=error_code,
            retryable=correction_allowed,
            attempt_count=0,
        )
        return (
            state.model_copy(
                update={
                    "decision_count": state.decision_count + 1,
                    "action_correction_count": (
                        state.action_correction_count + 1
                        if correction_allowed
                        else state.action_correction_count
                    ),
                    "failures": (*state.failures, failure),
                    "stop_reason_code": (
                        state.stop_reason_code
                        if correction_allowed
                        else "action_correction_exhausted"
                    ),
                }
            ),
            correction_allowed,
        )

    def record_tool_failure(
        self,
        state: SequentialAnalysisState,
        outcome: ToolExecutionFailed,
    ) -> SequentialAnalysisState:
        hypothesis_id = outcome.action.action.hypothesis.hypothesis_id
        matches = [
            item
            for item in state.hypotheses
            if item.target.hypothesis_id == hypothesis_id
        ]
        if len(matches) != 1 or matches[0].status != "active":
            self._fail(
                "unknown_active_hypothesis",
                f"Tool failure has no unique active hypothesis: {hypothesis_id}",
            )
        failure = AnalysisFailureRecord(
            failure_type="tool_execution_failed",
            action_id=outcome.action.action.action_id,
            error_code=outcome.error_code,
            retryable=False,
            attempt_count=outcome.attempt_count,
        )
        stop_reason_code = (
            "tool_retry_exhausted"
            if outcome.failure_kind == "transient"
            else "hard_tool_failure"
        )
        return state.model_copy(
            update={
                "tool_retry_count": (
                    state.tool_retry_count + max(0, outcome.attempt_count - 1)
                ),
                "failures": (*state.failures, failure),
                "limitations": tuple(
                    dict.fromkeys(
                        (*state.limitations, f"tool_failure:{outcome.error_code}")
                    )
                ),
                "stop_reason_code": stop_reason_code,
            }
        )

    def _validate_evidence_identity(self, action, item) -> None:
        if item.node_id != action.node.node_id:
            self._fail("evidence_action_mismatch", "Evidence action ID does not match")
        if item.question_id != action.action.hypothesis.hypothesis_id:
            self._fail(
                "evidence_hypothesis_mismatch",
                "Evidence hypothesis ID does not match",
            )
        if item.tool_name != action.action.tool_name:
            self._fail("evidence_tool_mismatch", "Evidence Tool does not match")
        if item.analysis_method != action.action.analysis_method:
            self._fail(
                "evidence_method_mismatch",
                "Evidence analysis method does not match",
            )

    def _require_decision_budget(self, state: SequentialAnalysisState) -> None:
        if state.decision_count >= MAX_AGENT_DECISIONS:
            self._fail("decision_budget_exhausted", "no Agent decisions remain")

    def _fail(self, code: str, message: str) -> None:
        raise AnalysisStateReductionError(code, message)


__all__ = [
    "AnalysisStateReducer",
    "AnalysisStateReductionError",
    "MAX_AGENT_DECISIONS",
    "MAX_ANALYSIS_TOOL_CALLS",
    "MAX_SKILL_REFERENCE_LOADS",
]
