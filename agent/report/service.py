"""Application service coordinating one trusted report-analysis run."""

from __future__ import annotations

import time
from types import SimpleNamespace

from reporting.builders import ReportManifestBuilder
from reporting.kernel import (
    ANALYSIS_METHOD_REGISTRY_VERSION,
    KERNEL_VERSION,
    AnalysisMethodRegistry,
)
from reporting.models import (
    AnalysisPackage,
    AnalysisRunMetrics,
    DataAccessScope,
    DataScopeAvailability,
    DraftAnalysisClaim,
    PredicateBinding,
    SequentialLoopCheckpoint,
    SequentialLoopResult,
    HypothesisTarget,
    NextAnalysisAction,
)
from reporting.observation import (
    OBSERVATION_BUILDER_VERSION,
    ObservationBuilder,
    estimate_observation_tokens,
    serialize_observation,
)
from reporting.renderer import AnalysisRenderer
from reporting.repository import ReportRepository
from reporting.longitudinal import LongitudinalAnalysisTool, build_longitudinal_context, comparison_action
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION, AnalysisToolRegistry
from reporting.validators import (
    ActionValidator,
    ClaimRepairValidationError,
    ClaimRepairValidator,
    ClaimValidationError,
    ClaimValidator,
    PlanValidator,
)
from knowledge.integration import build_report_rag_context
from knowledge.pipeline import degraded_rag_result
from reporting.questions import (
    chart_source_action,
    parent_question_context,
    resolve_question_selection,
    question_context,
    question_digest,
)

from .agent import ReportAgent, ReportAgentCallTimeout
from .analysis_loop import AnalysisLoop, AnalysisLoopError
from .checkpoint import RepositoryCheckpointSink
from .execution import SequentialActionBoundary
from .deadline import (
    AnalysisDeadlineExceeded,
    ReportAnalysisDeadline,
    ReportAnalysisDeadlinePolicy,
    call_with_optional_timeout,
)
from .sequential_loop import (
    SequentialAnalysisLoop,
    SequentialAnalysisLoopError,
)
from .skill_loader import ReportAnalysisSkillLoader, SkillLoadError
from .tools import AnalysisToolGateway


class ReportAnalysisError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        analysis_run_id: str | None = None,
        timeout_stage: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.analysis_run_id = analysis_run_id
        self.timeout_stage = timeout_stage


class ReportAnalysisService:
    def __init__(
        self,
        repository: ReportRepository,
        *,
        agent=None,
        tool_registry: AnalysisToolRegistry | None = None,
        method_registry: AnalysisMethodRegistry | None = None,
        observation_builder: ObservationBuilder | None = None,
        claim_validator: ClaimValidator | None = None,
        claim_repair_validator: ClaimRepairValidator | None = None,
        renderer: AnalysisRenderer | None = None,
        max_replans: int = 0,
        skill_loader: ReportAnalysisSkillLoader | None = None,
        rag_pipeline=None,
        rag_unavailable_error_code: str | None = None,
        deadline_policy: ReportAnalysisDeadlinePolicy | None = None,
        clock=time.monotonic,
    ):
        self._repository = repository
        self._agent = agent or ReportAgent()
        self._tool_registry = tool_registry or AnalysisToolRegistry()
        self._method_registry = method_registry or AnalysisMethodRegistry()
        self._observation_builder = observation_builder or ObservationBuilder(
            include_analysis_sketch=True,
            include_compact_series=True,
            include_screening_cues=False,
        )
        self._claim_validator = claim_validator or ClaimValidator()
        self._claim_repair_validator = (
            claim_repair_validator or ClaimRepairValidator()
        )
        self._renderer = renderer or AnalysisRenderer()
        self._max_replans = max_replans
        self._skill_loader = skill_loader or ReportAnalysisSkillLoader()
        self._rag_pipeline = rag_pipeline
        self._rag_unavailable_error_code = rag_unavailable_error_code
        self._deadline_policy = (
            deadline_policy
            if deadline_policy is not None
            else ReportAnalysisDeadlinePolicy.from_environment()
        )
        self._clock = clock

    def analyze(
        self,
        session_id: int,
        access_scope: DataAccessScope,
    ) -> AnalysisPackage:
        return self._analyze(session_id, access_scope)

    def _build_observation(self, package, access_scope, *, scoped=False, longitudinal=False):
        manifest = ReportManifestBuilder().build(package)
        availability = (
            DataScopeAvailability(longitudinal_candidates=1, longitudinal_available=True)
            if longitudinal else DataScopeAvailability(reasons=("external_scope_not_requested",))
        )
        capabilities = self._tool_registry.list_capabilities(
            package, access_scope, self._method_registry
        )
        if scoped:
            capabilities = [tool.model_copy(update={
                "available_methods": tuple(
                    method for method in tool.available_methods
                    if method.analysis_method not in {"verify_exclusion_robustness", "quality_scope_check"}
                ),
            }) for tool in capabilities]
        if not longitudinal:
            capabilities = [tool.model_copy(update={"enabled": False, "available_methods": (),
                "unavailable_reason": "historical_question_required"})
                if tool.tool_name == "compare_longitudinal" else tool for tool in capabilities]
        return self._observation_builder.build(
            package, manifest, availability, access_scope, capabilities
        )

    def ask(self, request) -> AnalysisPackage:
        if not callable(getattr(self._agent, "decide", None)) or not callable(
            getattr(self._agent, "plan_question", None)
        ):
            raise ReportAnalysisError("question_agent_unavailable", "当前分析服务尚未启用报告追问。")
        if request.data_access_scope.cohort:
            raise ReportAnalysisError("external_scope_not_implemented", "当前追问支持本次报告及最近一次同协议个人测试。")
        if not request.data_access_scope.current_session:
            raise ReportAnalysisError("scope_not_authorized", "本次报告数据尚未获准使用。")
        deadline = ReportAnalysisDeadline(self._deadline_policy, clock=self._clock)
        package = self._repository.get_package(request.session_id)
        parent = None
        if request.parent_analysis_run_id:
            saved = self._repository.get_validated_analysis(
                request.parent_analysis_run_id, request.session_id,
                request.data_access_scope, package.metadata.package_digest,
                include_current_scope=request.data_access_scope.longitudinal,
            )
            if saved is None:
                raise ReportAnalysisError("invalid_parent_analysis", "上一条分析与当前报告版本不匹配，请重新打开报告。")
            parent = AnalysisPackage.model_validate(saved)
        context_input = parent_question_context(parent, request.selected_claim_id)
        previous_match = None
        if request.data_access_scope.longitudinal and not package.context.is_temporary and package.context.subject_id:
            previous_match = self._repository.get_previous_package(request.session_id)
        context_input["history_availability"] = (
            "available" if previous_match else "guest" if package.context.is_temporary or not package.context.subject_id
            else "no_previous" if request.data_access_scope.longitudinal else "not_authorized"
        )
        if previous_match:
            previous, _ = previous_match
            context_input["previous_test"] = {
                "started_at": previous.context.started_at,
                "record_sets": [{"record_type": r.record_type, "metric_codes": r.metric_codes}
                                for r in previous.record_sets],
            }
        observation = self._build_observation(package, request.data_access_scope, scoped=True)
        try:
            plan = call_with_optional_timeout(
                self._agent.plan_question, observation, request.question, context_input,
                timeout_s=deadline.model_timeout_seconds("decision"),
            )
            deadline.require_total_time("question_planning")
        except (ReportAgentCallTimeout, AnalysisDeadlineExceeded) as exc:
            raise ReportAnalysisError("analysis_timeout", str(exc), timeout_stage="question_planning") from exc
        selection = resolve_question_selection(package, plan, context_input)
        context = question_context(request, selection, plan, context_input)
        previous = None
        if plan.comparison == "previous":
            if previous_match is None:
                raise ReportAnalysisError("history_unavailable", "当前报告没有可用于比较的此前同协议测试。")
            previous, protocol = previous_match
            longitudinal = build_longitudinal_context(package, previous, plan, selection, protocol, parent)
            context = context.model_copy(update={
                "longitudinal": longitudinal,
                "selection_label": f"两次同协议测试 · {selection.label}",
            })
        return self._analyze(
            request.session_id, request.data_access_scope,
            question=context, package=package, deadline=deadline,
            initial_action=comparison_action(context) if previous else chart_source_action(parent, context),
            previous=previous,
        )

    def _analyze(
        self, session_id, access_scope, *, question=None, package=None,
        deadline=None, initial_action=None, previous=None,
    ):
        request_digest = question_digest(question) if question else ""
        selection = question.selection if question else None
        if selection and initial_action is None:
            initial_action = NextAnalysisAction(
                action_id="question_summary",
                tool_name="analyze_current_session",
                analysis_method="summarize_records",
                inputs={
                    "record_set_id": selection.record_set_id,
                    "metric_codes": list(selection.metric_codes),
                },
                purpose="汇总用户所选范围",
                hypothesis=HypothesisTarget(
                    hypothesis_id="question_scope", statement=question.question,
                    dimensions=("descriptive",), metric_codes=selection.metric_codes,
                    target_predicate="comparison_supported", reason="用户指定的报告范围",
                    success_condition="取得该范围的有效记录和统计结果",
                ),
            )
        deadline = deadline or ReportAnalysisDeadline(
            self._deadline_policy,
            clock=self._clock,
        )
        started = self._clock()
        if access_scope.cohort or (access_scope.longitudinal and question is None):
            raise ReportAnalysisError(
                "external_scope_not_implemented",
                "Use report questions for previous-session comparisons; cohort analysis is unavailable",
            )
        package = package or self._repository.get_package(session_id)
        observation = self._build_observation(
            package, access_scope, scoped=question is not None, longitudinal=previous is not None,
        )
        if question:
            observation = observation.model_copy(update={
                "question_context": question, "authoritative_facts": (),
            })
        model_name = getattr(self._agent, "model_name", "unknown")
        use_sequential_loop = callable(getattr(self._agent, "decide", None))
        prompt_version = getattr(
            self._agent,
            "sequential_prompt_version"
            if use_sequential_loop
            else "prompt_version",
            "unknown",
        )
        prompt_content_digest = getattr(
            self._agent,
            "sequential_prompt_content_digest"
            if use_sequential_loop
            else "prompt_content_digest",
            None,
        )
        resume_from = None
        run_id = None
        if use_sequential_loop:
            try:
                skill_context = self._skill_loader.load_initial(
                    package.context.test_type
                )
            except SkillLoadError as exc:
                raise ReportAnalysisError(exc.code, str(exc)) from exc
            resumable = self._repository.get_resumable_analysis_checkpoint(
                session_id,
                access_scope,
                package.metadata.package_digest,
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_content_digest=prompt_content_digest,
                skill_version=skill_context.skill_version,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
                request_digest=request_digest,
            )
            if resumable is not None and self._checkpoint_skill_matches(
                resumable.checkpoint, package.context.test_type
            ):
                run_id = resumable.analysis_run_id
                resume_from = resumable.checkpoint
        if run_id is None:
            run_id = self._repository.create_analysis_run(
                session_id,
                access_scope,
                package.metadata.package_digest,
                model_name=model_name,
                prompt_version=prompt_version,
                request_digest=request_digest,
            )
        result = None
        checkpoint_sink = None
        claim_repair_count = 0
        timeout_stage = None
        resumed_from_checkpoint = resume_from is not None
        try:
            gateway = AnalysisToolGateway(
                tool_registry=self._tool_registry,
                method_registry=self._method_registry,
                longitudinal_tool=LongitudinalAnalysisTool(previous, question.longitudinal) if previous else None,
            )
            if use_sequential_loop:
                checkpoint_sink = RepositoryCheckpointSink(
                    self._repository, run_id, request_digest=request_digest
                )
                action_validator = ActionValidator(
                    self._tool_registry, self._method_registry, selection=selection,
                    longitudinal_context=question.longitudinal if question else None,
                )
                loop = SequentialAnalysisLoop(
                    self._agent,
                    skill_loader=self._skill_loader,
                    action_validator=action_validator,
                    action_boundary=SequentialActionBoundary(
                        action_validator=action_validator,
                        tool_gateway=gateway,
                    ),
                    checkpoint_sink=checkpoint_sink,
                    prompt_content_digest=prompt_content_digest,
                    request_digest=request_digest,
                    initial_action=initial_action,
                )
                if resume_from is not None and resume_from.phase in {
                    "draft_generated",
                    "claim_repair_pending",
                }:
                    result = SequentialLoopResult(
                        state=resume_from.state,
                        evidence=resume_from.evidence,
                        draft=resume_from.draft,
                        skill_version=resume_from.skill_version,
                        skill_content_digest=resume_from.skill_content_digest,
                    )
                    claim_repair_count = resume_from.claim_repair_count
                else:
                    result = loop.run(
                        observation,
                        package,
                        access_scope,
                        resume_from=resume_from,
                        deadline=deadline,
                    )
                    self._save_claim_checkpoint(
                        checkpoint_sink,
                        "draft_generated",
                        package,
                        access_scope,
                        result,
                        prompt_content_digest=prompt_content_digest,
                    )
            else:
                loop = AnalysisLoop(
                    self._agent,
                    plan_validator=PlanValidator(
                        self._tool_registry, self._method_registry
                    ),
                    tool_gateway=gateway,
                    max_replans=self._max_replans,
                )
                result = loop.run(
                    observation,
                    package,
                    access_scope,
                    deadline=deadline,
                )
            historical_refs = {
                item.evidence_id for bundle in result.evidence for item in bundle.items if item.longitudinal
            }
            needs_comparison = previous is not None and not any(
                historical_refs.intersection(claim.evidence_refs) for claim in result.draft.claims
            )
            if question and (not result.draft.claims or needs_comparison):
                summary = next((
                    (item, predicate)
                    for bundle in result.evidence
                    for item in bundle.items
                    if item.analysis_method == initial_action.analysis_method
                    and item.analysis_status == "conclusive"
                    for predicate in item.predicates
                    if predicate.predicate == initial_action.hypothesis.target_predicate
                    and predicate.supported
                ), None)
                if summary is None:
                    raise ClaimValidationError(
                        "question_summary_unavailable", "所选范围缺少有效统计证据，无法生成回答。"
                    )
                item, predicate = summary
                claim = DraftAnalysisClaim(
                    claim_id="question_summary", claim_type="derived",
                    text_template="所选范围的证据分析。",
                    evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
                    predicate_bindings=(PredicateBinding(
                        predicate=predicate.predicate,
                        predicate_evidence_ref=predicate.predicate_evidence_id,
                    ),),
                )
                result = result.model_copy(update={
                    "draft": result.draft.model_copy(update={"claims": (
                        *result.draft.claims,
                        claim.model_copy(update={"claim_id": "question_summary_" + item.evidence_id}),
                    )}),
                })
                self._save_claim_checkpoint(
                    checkpoint_sink, "draft_generated", package, access_scope, result,
                    claim_repair_count=claim_repair_count,
                    prompt_content_digest=prompt_content_digest,
                )
            validation_options = {"allowed_fact_refs": frozenset()} if question else {}
            if previous:
                validation_options["longitudinal_source"] = (previous, question.longitudinal)
            try:
                deadline.require_total_time("claim_validation")
                validated = self._claim_validator.validate(
                    result.draft,
                    package,
                    result.evidence,
                    access_scope,
                    **validation_options,
                )
            except ClaimValidationError as first_error:
                repair = getattr(self._agent, "repair_synthesis", None)
                if (
                    not callable(repair)
                    or claim_repair_count >= 1
                    or not self._claim_repair_validator.can_repair(
                        first_error.code
                    )
                ):
                    raise
                if use_sequential_loop:
                    self._save_claim_checkpoint(
                        checkpoint_sink,
                        "claim_repair_pending",
                        package,
                        access_scope,
                        result,
                        error_code=first_error.code,
                        error_message=str(first_error),
                        claim_repair_count=claim_repair_count,
                        prompt_content_digest=prompt_content_digest,
                    )
                try:
                    repaired_draft = call_with_optional_timeout(
                        repair,
                        observation,
                        result.state,
                        result.evidence,
                        result.draft,
                        first_error.code,
                        str(first_error),
                        timeout_s=deadline.model_timeout_seconds(
                            "claim_repair"
                        ),
                    )
                    deadline.require_total_time("claim_repair")
                except ReportAgentCallTimeout as exc:
                    raise AnalysisDeadlineExceeded("claim_repair") from exc
                try:
                    self._claim_repair_validator.validate(
                        result.draft,
                        repaired_draft,
                        first_error.code,
                        package,
                        result.evidence,
                    )
                except ClaimRepairValidationError as repair_error:
                    raise ClaimValidationError(
                        repair_error.code, str(repair_error)
                    ) from repair_error
                claim_repair_count += 1
                result = result.model_copy(update={"draft": repaired_draft})
                if use_sequential_loop:
                    self._save_claim_checkpoint(
                        checkpoint_sink,
                        "draft_generated",
                        package,
                        access_scope,
                        result,
                        claim_repair_count=claim_repair_count,
                        prompt_content_digest=prompt_content_digest,
                    )
                validated = self._claim_validator.validate(
                    repaired_draft,
                    package,
                    result.evidence,
                    access_scope,
                    **validation_options,
                )
            deadline.require_total_time("claim_validation")
            runtime_limitations = tuple(
                limitation
                for limitation in getattr(result.state, "limitations", ())
                if limitation in {
                    "investigation_deadline_reached",
                    "decision_request_timeout",
                }
            )
            if runtime_limitations:
                validated = validated.model_copy(
                    update={
                        "overall_limitations": tuple(
                            dict.fromkeys(
                                (
                                    *validated.overall_limitations,
                                    *runtime_limitations,
                                )
                            )
                        )
                    }
                )
            rag_result = None
            if self._rag_pipeline is not None:
                if deadline.remaining_total_seconds() <= 0:
                    rag_result = degraded_rag_result(
                        package.metadata.package_digest,
                        "analysis_deadline_insufficient_for_rag",
                    )
                else:
                    try:
                        rag_context = build_report_rag_context(
                            package, validated, result.evidence
                        )
                        rag_result = self._rag_pipeline.run(rag_context)
                        if deadline.remaining_total_seconds() <= 0:
                            rag_result = degraded_rag_result(
                                package.metadata.package_digest,
                                "analysis_deadline_exceeded_during_rag",
                            )
                    except Exception:
                        rag_result = degraded_rag_result(
                            package.metadata.package_digest,
                            "rag_integration_failed",
                        )
            elif self._rag_unavailable_error_code is not None:
                rag_result = degraded_rag_result(
                    package.metadata.package_digest,
                    self._rag_unavailable_error_code,
                )
            rendered = self._renderer.render(
                validated,
                analysis_run_id=run_id,
                package=package,
                access_scope=access_scope,
                state=result.state,
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_content_digest=prompt_content_digest,
                rag_result=rag_result,
                evidence=result.evidence,
                request_digest=request_digest,
                question_context=question,
                source_packages={previous.metadata.session_id: previous} if previous else None,
            )
            if previous and not self._repository.longitudinal_is_current(rendered.model_dump(mode="json")):
                raise ClaimValidationError("stale_history", "比较期间测试记录发生更新，请重新提问。")
            self._record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                result,
                claim_repair_count=claim_repair_count,
                resumed_from_checkpoint=resumed_from_checkpoint,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "validated",
                rendered.model_dump(mode="json"),
            )
            return rendered
        except AnalysisDeadlineExceeded as exc:
            timeout_stage = exc.stage
            metrics_result = self._metrics_result(
                result, exc, checkpoint_sink
            )
            self._safe_record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                metrics_result,
                claim_repair_count=claim_repair_count,
                timeout_stage=timeout_stage,
                resumed_from_checkpoint=resumed_from_checkpoint,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "failed",
                None,
                "analysis_timeout",
            )
            raise ReportAnalysisError(
                "analysis_timeout",
                str(exc),
                analysis_run_id=run_id,
                timeout_stage=timeout_stage,
            ) from exc
        except (
            AnalysisLoopError,
            SequentialAnalysisLoopError,
            ClaimValidationError,
        ) as exc:
            if exc.code == "analysis_timeout":
                timeout_stage = getattr(exc, "timeout_stage", None)
                metrics_result = self._metrics_result(
                    result, exc, checkpoint_sink
                )
                self._safe_record_metrics(
                    run_id,
                    package.metadata.package_digest,
                    observation,
                    model_name,
                    prompt_version,
                    prompt_content_digest,
                    started,
                    metrics_result,
                    claim_repair_count=claim_repair_count,
                    timeout_stage=timeout_stage,
                    resumed_from_checkpoint=resumed_from_checkpoint,
                )
                self._repository.finalize_analysis_run(
                    run_id, "failed", None, "analysis_timeout"
                )
                raise ReportAnalysisError(
                    "analysis_timeout",
                    str(exc),
                    analysis_run_id=run_id,
                    timeout_stage=timeout_stage,
                ) from exc
            metrics_result = self._metrics_result(
                result, exc, checkpoint_sink
            )
            self._record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                metrics_result,
                claim_repair_count=claim_repair_count,
                resumed_from_checkpoint=resumed_from_checkpoint,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "rejected",
                None,
                exc.code,
            )
            raise ReportAnalysisError(exc.code, str(exc)) from exc
        except Exception as exc:
            metrics_result = self._metrics_result(
                result, exc, checkpoint_sink
            )
            self._safe_record_metrics(
                run_id,
                package.metadata.package_digest,
                observation,
                model_name,
                prompt_version,
                prompt_content_digest,
                started,
                metrics_result,
                claim_repair_count=claim_repair_count,
                resumed_from_checkpoint=resumed_from_checkpoint,
            )
            self._repository.finalize_analysis_run(
                run_id,
                "failed",
                None,
                "analysis_failed",
            )
            raise ReportAnalysisError("analysis_failed", str(exc)) from exc

    def _save_claim_checkpoint(
        self,
        checkpoint_sink,
        phase,
        package,
        access_scope,
        result,
        *,
        error_code=None,
        error_message=None,
        claim_repair_count=0,
        prompt_content_digest=None,
    ) -> None:
        checkpoint_sink.save(
            SequentialLoopCheckpoint(
                phase=phase,
                session_id=package.metadata.session_id,
                package_digest=package.metadata.package_digest,
                data_access_scope=access_scope,
                state=result.state,
                evidence=result.evidence,
                draft=result.draft,
                claim_validation_error_code=error_code,
                claim_validation_error_message=error_message,
                claim_repair_count=claim_repair_count,
                skill_version=result.skill_version,
                skill_content_digest=result.skill_content_digest,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
                prompt_content_digest=prompt_content_digest,
            )
        )

    def _metrics_result(self, result, exc, checkpoint_sink):
        if result is not None:
            return result
        checkpoint = (
            checkpoint_sink.latest_checkpoint
            if checkpoint_sink is not None
            else None
        )
        state = getattr(exc, "state", None)
        if state is None and checkpoint is not None:
            state = checkpoint.state
        if state is None:
            return None
        evidence = getattr(exc, "evidence", ())
        if checkpoint is not None and len(checkpoint.evidence) > len(evidence):
            evidence = checkpoint.evidence
        return SimpleNamespace(
            state=state,
            evidence=evidence,
            investigation_elapsed_ms=getattr(
                exc, "investigation_elapsed_ms", 0
            ),
            synthesis_elapsed_ms=getattr(exc, "synthesis_elapsed_ms", 0),
        )

    def _checkpoint_skill_matches(self, checkpoint, test_type) -> bool:
        try:
            context = self._skill_loader.load_initial(test_type)
            for reference_id in checkpoint.state.loaded_skill_references:
                if reference_id not in context.loaded_reference_ids:
                    context = self._skill_loader.load_reference(
                        context, reference_id
                    )
        except SkillLoadError:
            return False
        return (
            context.skill_version == checkpoint.skill_version
            and context.content_digest == checkpoint.skill_content_digest
        )

    def get_latest(
        self,
        session_id: int,
        access_scope: DataAccessScope,
    ) -> dict | None:
        package = self._repository.get_package(session_id)
        return self._repository.get_latest_validated_analysis(
            session_id,
            access_scope,
            package.metadata.package_digest,
        )

    def get_history(self, session_id, access_scope):
        package = self._repository.get_package(session_id)
        return self._repository.list_validated_analyses(
            session_id, access_scope, package.metadata.package_digest,
            include_current_scope=access_scope.longitudinal,
        )

    def get_annotations(self, request):
        from reporting.annotations import read_annotations
        return read_annotations(self._repository, request)

    def save_annotation(self, request):
        from reporting.annotations import save_annotation
        return save_annotation(self._repository, request)

    def compare_previous(self, session_id, access_scope):
        if not access_scope.longitudinal:
            raise ReportAnalysisError("scope_not_authorized", "历史对比需要使用该用户的历史测试记录。")
        return self._repository.compare_previous_session(session_id)

    def get_saved(self, session_id, access_scope, analysis_run_id):
        package = self._repository.get_package(session_id)
        analysis = self._repository.get_validated_analysis(
            analysis_run_id, session_id, access_scope, package.metadata.package_digest,
            include_current_scope=access_scope.longitudinal,
        )
        if analysis is None:
            raise ReportAnalysisError("invalid_parent_analysis", "该回答与当前报告版本不匹配。")
        return analysis

    def _record_metrics(
        self,
        run_id,
        package_digest,
        observation,
        model_name,
        prompt_version,
        prompt_content_digest,
        started,
        result,
        *,
        claim_repair_count=0,
        timeout_stage=None,
        resumed_from_checkpoint=False,
    ):
        serialized = serialize_observation(observation)
        evidence = result.evidence if result is not None else ()
        self._repository.update_analysis_run_metrics(
            run_id,
            AnalysisRunMetrics(
                model_name=model_name,
                prompt_version=prompt_version,
                prompt_content_digest=prompt_content_digest,
                observation_builder_version=OBSERVATION_BUILDER_VERSION,
                analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
                analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
                kernel_version=KERNEL_VERSION,
                package_digest=package_digest,
                cycle_count=(
                    getattr(
                        result.state,
                        "cycle_count",
                        getattr(result.state, "tool_call_count", 0),
                    )
                    if result is not None
                    else 0
                ),
                replan_count=(
                    getattr(result.state, "replan_count", 0)
                    if result is not None
                    else 0
                ),
                agent_level_node_count=sum(len(bundle.items) for bundle in evidence),
                tool_run_count=sum(len(bundle.tool_runs) for bundle in evidence),
                duplicate_request_count=0,
                observation_size=len(serialized.encode("utf-8")),
                estimated_tokens=estimate_observation_tokens(serialized),
                elapsed_ms=max(0, round((self._clock() - started) * 1000)),
                decision_count=(
                    getattr(result.state, "decision_count", 0)
                    if result is not None
                    else 0
                ),
                tool_call_count=(
                    getattr(result.state, "tool_call_count", 0)
                    if result is not None
                    else 0
                ),
                skill_reference_load_count=(
                    len(getattr(result.state, "loaded_skill_references", ()))
                    if result is not None
                    else 0
                ),
                investigation_elapsed_ms=(
                    getattr(result, "investigation_elapsed_ms", 0)
                    if result is not None
                    else 0
                ),
                synthesis_elapsed_ms=(
                    getattr(result, "synthesis_elapsed_ms", 0)
                    if result is not None
                    else 0
                ),
                claim_repair_count=claim_repair_count,
                stop_reason_code=(
                    getattr(result.state, "stop_reason_code", None)
                    if result is not None
                    else None
                ),
                timeout_stage=timeout_stage,
                resumed_from_checkpoint=resumed_from_checkpoint,
            ),
        )

    def _safe_record_metrics(self, *args, **kwargs) -> None:
        try:
            self._record_metrics(*args, **kwargs)
        except Exception:
            # The original failure remains authoritative; the run is still finalized.
            pass
