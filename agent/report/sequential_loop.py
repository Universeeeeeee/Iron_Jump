"""Skill-guided sequential hypothesis testing loop for report analysis."""

from __future__ import annotations

from reporting.models import (
    ActionRejected,
    AgentObservation,
    DataAccessScope,
    EvidenceBundle,
    EvidenceProduced,
    LoadSkillResource,
    NextAnalysisAction,
    ReportDataPackage,
    SequentialAnalysisState,
    SequentialLoopCheckpoint,
    SequentialLoopResult,
    StopAnalysis,
    ToolExecutionFailed,
)
from reporting.kernel import (
    ANALYSIS_METHOD_REGISTRY_VERSION,
    KERNEL_VERSION,
)
from reporting.observation import OBSERVATION_BUILDER_VERSION
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION
from reporting.validators import ActionValidationError, ActionValidator

from .execution import SequentialActionBoundary
from .agent import ReportAgentCallTimeout
from .deadline import (
    AnalysisDeadlineExceeded,
    ReportAnalysisDeadline,
    call_with_optional_timeout,
)
from .skill_loader import (
    ReportAnalysisSkillContext,
    ReportAnalysisSkillLoader,
    SkillLoadError,
)
from .state import (
    AnalysisStateReducer,
    AnalysisStateReductionError,
    MAX_AGENT_DECISIONS,
    MAX_ANALYSIS_TOOL_CALLS,
    MAX_SKILL_REFERENCE_LOADS,
)


class SequentialAnalysisLoopError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        state: SequentialAnalysisState,
        outcome: ToolExecutionFailed | None = None,
        timeout_stage: str | None = None,
        investigation_elapsed_ms: int = 0,
        synthesis_elapsed_ms: int = 0,
    ):
        super().__init__(message)
        self.code = code
        self.state = state
        self.outcome = outcome
        self.timeout_stage = timeout_stage
        self.investigation_elapsed_ms = investigation_elapsed_ms
        self.synthesis_elapsed_ms = synthesis_elapsed_ms


class SequentialAnalysisLoop:
    """Run one validated action per turn without changing the legacy loop."""

    def __init__(
        self,
        agent,
        *,
        skill_loader: ReportAnalysisSkillLoader | None = None,
        action_validator: ActionValidator | None = None,
        action_boundary: SequentialActionBoundary | None = None,
        state_reducer: AnalysisStateReducer | None = None,
        checkpoint_sink=None,
        prompt_content_digest: str | None = None,
    ):
        self._agent = agent
        self._skill_loader = skill_loader or ReportAnalysisSkillLoader()
        self._action_validator = action_validator or ActionValidator()
        self._action_boundary = action_boundary or SequentialActionBoundary(
            action_validator=self._action_validator
        )
        self._state_reducer = state_reducer or AnalysisStateReducer()
        self._checkpoint_sink = checkpoint_sink
        self._prompt_content_digest = prompt_content_digest

    def run(
        self,
        observation: AgentObservation,
        package: ReportDataPackage,
        access_scope: DataAccessScope,
        *,
        resume_from: SequentialLoopCheckpoint | None = None,
        deadline: ReportAnalysisDeadline | None = None,
    ) -> SequentialLoopResult:
        if resume_from is None:
            context = self._load_initial_skill(observation)
            state = SequentialAnalysisState(
                loaded_skill_references=context.loaded_reference_ids
            )
            evidence_bundles: list[EvidenceBundle] = []
            self._save_checkpoint(
                "skill_loaded",
                package,
                access_scope,
                context,
                state,
                evidence_bundles,
            )
        else:
            context, state, evidence_bundles = self._restore_checkpoint(
                resume_from,
                observation,
                package,
                access_scope,
            )
            if resume_from.pending_action is not None:
                state = self._execute_validated_action(
                    resume_from.pending_action,
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )

        while (
            state.stop_reason_code is None
            and state.decision_count < MAX_AGENT_DECISIONS
        ):
            if deadline is not None and deadline.investigation_expired():
                state = self._record_deadline_stop(
                    state, "investigation_deadline_reached"
                )
                self._save_checkpoint(
                    "ready_for_synthesis",
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )
                break
            try:
                if deadline is None:
                    decision = self._agent.decide(
                        observation,
                        state,
                        tuple(evidence_bundles),
                        context,
                    )
                else:
                    decision = call_with_optional_timeout(
                        self._agent.decide,
                        observation,
                        state,
                        tuple(evidence_bundles),
                        context,
                        timeout_s=deadline.model_timeout_seconds("decision"),
                    )
            except (ReportAgentCallTimeout, AnalysisDeadlineExceeded):
                state = self._record_deadline_stop(
                    state, "decision_request_timeout"
                )
                self._save_checkpoint(
                    "ready_for_synthesis",
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )
                break
            if deadline is not None and deadline.investigation_expired():
                state = self._record_deadline_stop(
                    state, "investigation_deadline_reached"
                )
                self._save_checkpoint(
                    "ready_for_synthesis",
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )
                break
            if isinstance(decision, LoadSkillResource):
                context, state, loaded = self._load_skill_reference(
                    decision,
                    context,
                    state,
                )
                self._save_checkpoint(
                    "skill_loaded" if loaded else "state_updated",
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )
                continue
            if isinstance(decision, StopAnalysis):
                state = self._reduce(
                    state,
                    lambda: self._state_reducer.record_stop(state, decision),
                )
                self._save_checkpoint(
                    "ready_for_synthesis",
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )
                break
            if not isinstance(decision, NextAnalysisAction):
                raise SequentialAnalysisLoopError(
                    "invalid_analysis_decision",
                    f"unsupported analysis decision: {type(decision).__name__}",
                    state=state,
                )

            validated = self._action_boundary.validate(
                decision,
                package,
                access_scope,
                seen_request_hashes=frozenset(state.seen_request_hashes),
                seen_action_ids=frozenset(state.action_ids),
                seen_hypothesis_ids=frozenset(state.question_ids),
                remaining_tool_calls=(
                    MAX_ANALYSIS_TOOL_CALLS - state.tool_call_count
                ),
                action_correction_count=state.action_correction_count,
            )
            if isinstance(validated, ActionRejected):
                state = self._reduce(
                    state,
                    lambda: self._state_reducer.record_action_rejection(
                        state, validated
                    ),
                )
                self._save_checkpoint(
                    "state_updated",
                    package,
                    access_scope,
                    context,
                    state,
                    evidence_bundles,
                )
                if validated.correction_allowed:
                    continue
                raise SequentialAnalysisLoopError(
                    validated.error_code,
                    validated.message,
                    state=state,
                )

            state = self._reduce(
                state,
                lambda: self._state_reducer.begin_action(state, validated),
            )
            self._save_checkpoint(
                "action_accepted",
                package,
                access_scope,
                context,
                state,
                evidence_bundles,
                pending_action=validated,
            )
            state = self._execute_validated_action(
                validated,
                package,
                access_scope,
                context,
                state,
                evidence_bundles,
            )
        else:
            state = state.model_copy(
                update={
                    "stop_reason_code": "decision_budget_exhausted",
                    "limitations": tuple(
                        dict.fromkeys(
                            (*state.limitations, "decision_budget_exhausted")
                        )
                    ),
                }
            )
            self._save_checkpoint(
                "ready_for_synthesis",
                package,
                access_scope,
                context,
                state,
                evidence_bundles,
            )

        investigation_elapsed_ms = (
            round(deadline.elapsed_seconds() * 1000)
            if deadline is not None
            else 0
        )
        if deadline is not None:
            try:
                deadline.require_total_time("synthesis")
            except AnalysisDeadlineExceeded as exc:
                raise SequentialAnalysisLoopError(
                    "analysis_timeout",
                    str(exc),
                    state=state,
                    timeout_stage=exc.stage,
                    investigation_elapsed_ms=investigation_elapsed_ms,
                ) from exc
        context, state = self._prepare_synthesis_context(
            package,
            access_scope,
            context,
            state,
            evidence_bundles,
        )
        synthesize_sequential = getattr(
            self._agent, "synthesize_sequential", None
        )
        synthesis_started = (
            deadline.elapsed_seconds() if deadline is not None else 0.0
        )
        try:
            if callable(synthesize_sequential):
                if deadline is None:
                    draft = synthesize_sequential(
                        observation,
                        state,
                        tuple(evidence_bundles),
                        context,
                    )
                else:
                    draft = call_with_optional_timeout(
                        synthesize_sequential,
                        observation,
                        state,
                        tuple(evidence_bundles),
                        context,
                        timeout_s=deadline.model_timeout_seconds("synthesis"),
                    )
            elif deadline is None:
                draft = self._agent.synthesize(
                    observation,
                    state,
                    tuple(evidence_bundles),
                )
            else:
                draft = call_with_optional_timeout(
                    self._agent.synthesize,
                    observation,
                    state,
                    tuple(evidence_bundles),
                    timeout_s=deadline.model_timeout_seconds("synthesis"),
                )
            if deadline is not None:
                deadline.require_total_time("synthesis")
        except (ReportAgentCallTimeout, AnalysisDeadlineExceeded) as exc:
            stage = getattr(exc, "stage", "synthesis")
            raise SequentialAnalysisLoopError(
                "analysis_timeout",
                str(exc),
                state=state,
                timeout_stage=stage,
                investigation_elapsed_ms=investigation_elapsed_ms,
                synthesis_elapsed_ms=(
                    round(
                        (deadline.elapsed_seconds() - synthesis_started)
                        * 1000
                    )
                    if deadline is not None
                    else 0
                ),
            ) from exc
        synthesis_elapsed_ms = (
            round((deadline.elapsed_seconds() - synthesis_started) * 1000)
            if deadline is not None
            else 0
        )
        return SequentialLoopResult(
            state=state,
            evidence=tuple(evidence_bundles),
            draft=draft,
            skill_version=context.skill_version,
            skill_content_digest=context.content_digest,
            investigation_elapsed_ms=investigation_elapsed_ms,
            synthesis_elapsed_ms=synthesis_elapsed_ms,
        )

    def _record_deadline_stop(self, state, reason_code):
        return self._reduce(
            state,
            lambda: self._state_reducer.record_deadline_stop(
                state, reason_code
            ),
        )

    def _prepare_synthesis_context(
        self,
        package,
        access_scope,
        context,
        state,
        evidence_bundles,
    ):
        reference_id = "references/evidence-guidelines.md"
        if reference_id in context.loaded_reference_ids:
            return context, state
        try:
            context = self._skill_loader.load_reference(
                context, reference_id
            )
        except SkillLoadError as exc:
            raise SequentialAnalysisLoopError(
                exc.code,
                str(exc),
                state=state,
            ) from exc
        state = state.model_copy(
            update={
                "loaded_skill_references": (
                    *state.loaded_skill_references,
                    reference_id,
                )
            }
        )
        self._save_checkpoint(
            "skill_loaded",
            package,
            access_scope,
            context,
            state,
            evidence_bundles,
        )
        return context, state

    def _execute_validated_action(
        self,
        validated,
        package,
        access_scope,
        context,
        state,
        evidence_bundles,
    ):
        outcome = self._action_boundary.execute(
            validated,
            package,
            access_scope,
        )
        if isinstance(outcome, EvidenceProduced):
            state = self._reduce(
                state,
                lambda: self._state_reducer.apply_evidence_outcome(
                    state, outcome
                ),
            )
            evidence_bundles.append(outcome.evidence)
            self._save_checkpoint(
                "evidence_recorded",
                package,
                access_scope,
                context,
                state,
                evidence_bundles,
            )
            return state

        state = self._reduce(
            state,
            lambda: self._state_reducer.record_tool_failure(state, outcome),
        )
        raise SequentialAnalysisLoopError(
            outcome.error_code,
            outcome.message,
            state=state,
            outcome=outcome,
        )

    def _load_initial_skill(
        self, observation: AgentObservation
    ) -> ReportAnalysisSkillContext:
        try:
            return self._skill_loader.load_initial(
                observation.report_context.test_type
            )
        except SkillLoadError as exc:
            raise SequentialAnalysisLoopError(
                exc.code,
                str(exc),
                state=SequentialAnalysisState(),
            ) from exc

    def _load_skill_reference(
        self,
        decision: LoadSkillResource,
        context: ReportAnalysisSkillContext,
        state: SequentialAnalysisState,
    ) -> tuple[
        ReportAnalysisSkillContext,
        SequentialAnalysisState,
        bool,
    ]:
        try:
            self._action_validator.validate_skill_resource(
                decision,
                loaded_skill_references=frozenset(
                    state.loaded_skill_references
                ),
                remaining_skill_reference_loads=(
                    MAX_SKILL_REFERENCE_LOADS
                    - len(state.loaded_skill_references)
                ),
            )
            context = self._skill_loader.load_reference(
                context, decision.reference_id
            )
        except (ActionValidationError, SkillLoadError) as exc:
            try:
                state, correction_allowed = (
                    self._state_reducer.record_skill_rejection(
                        state, decision, exc.code
                    )
                )
            except AnalysisStateReductionError as reduction_error:
                raise SequentialAnalysisLoopError(
                    reduction_error.code,
                    str(reduction_error),
                    state=state,
                ) from reduction_error
            if correction_allowed:
                return context, state, False
            raise SequentialAnalysisLoopError(
                exc.code, str(exc), state=state
            ) from exc
        state = self._reduce(
            state,
            lambda: self._state_reducer.record_skill_resource(
                state, decision
            ),
        )
        return context, state, True

    def _reduce(self, state, transition):
        try:
            return transition()
        except AnalysisStateReductionError as exc:
            raise SequentialAnalysisLoopError(
                exc.code,
                str(exc),
                state=state,
            ) from exc

    def _restore_checkpoint(
        self,
        checkpoint,
        observation,
        package,
        access_scope,
    ):
        expected = {
            "session_id": package.metadata.session_id,
            "package_digest": package.metadata.package_digest,
            "data_access_scope": access_scope,
            "observation_builder_version": OBSERVATION_BUILDER_VERSION,
            "analysis_tool_registry_version": ANALYSIS_TOOL_REGISTRY_VERSION,
            "analysis_method_registry_version": ANALYSIS_METHOD_REGISTRY_VERSION,
            "kernel_version": KERNEL_VERSION,
        }
        if self._prompt_content_digest is not None:
            expected["prompt_content_digest"] = (
                self._prompt_content_digest
            )
        for field_name, expected_value in expected.items():
            if getattr(checkpoint, field_name) != expected_value:
                raise SequentialAnalysisLoopError(
                    "checkpoint_identity_mismatch",
                    f"Checkpoint {field_name} does not match the current run",
                    state=checkpoint.state,
                )
        context = self._load_initial_skill(observation)
        for reference_id in checkpoint.state.loaded_skill_references:
            if reference_id not in context.loaded_reference_ids:
                try:
                    context = self._skill_loader.load_reference(
                        context, reference_id
                    )
                except SkillLoadError as exc:
                    raise SequentialAnalysisLoopError(
                        exc.code,
                        str(exc),
                        state=checkpoint.state,
                    ) from exc
        if (
            context.skill_version != checkpoint.skill_version
            or context.content_digest != checkpoint.skill_content_digest
        ):
            raise SequentialAnalysisLoopError(
                "checkpoint_skill_mismatch",
                "Checkpoint Skill version or content does not match",
                state=checkpoint.state,
            )
        return context, checkpoint.state, list(checkpoint.evidence)

    def _save_checkpoint(
        self,
        phase,
        package,
        access_scope,
        context,
        state,
        evidence_bundles,
        *,
        pending_action=None,
    ):
        if self._checkpoint_sink is None:
            return
        self._checkpoint_sink.save(
            SequentialLoopCheckpoint(
                phase=phase,
                session_id=package.metadata.session_id,
                package_digest=package.metadata.package_digest,
                data_access_scope=access_scope,
                state=state,
                evidence=tuple(evidence_bundles),
                pending_action=pending_action,
                skill_version=context.skill_version,
                skill_content_digest=context.content_digest,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
                prompt_content_digest=self._prompt_content_digest,
            )
        )


__all__ = ["SequentialAnalysisLoop", "SequentialAnalysisLoopError"]
