"""Application-service tests for success, rejection and model failure paths."""

import sqlite3
import json

import pytest

from agent.report.service import ReportAnalysisError, ReportAnalysisService
from agent.report.agent import ReportAgentCallTimeout
from agent.report.deadline import (
    ReportAnalysisDeadlineConfigurationError,
    ReportAnalysisDeadlinePolicy,
)
from knowledge.pipeline import degraded_rag_result
from agent.report.skill_loader import ReportAnalysisSkillLoader, SkillLoadError
from agent.report.state import AnalysisStateReducer
from config.test_config import default_jump_config
from data.subject_store import SubjectStore
from reporting.models import (
    AnalysisNode,
    AnalysisQuestion,
    DataAccessScope,
    DraftAnalysisClaim,
    DraftAnalysisPackage,
    EvidenceReviewDecision,
    InvestigationDecision,
    HypothesisTarget,
    NextAnalysisAction,
    NumericBinding,
    PredicateBinding,
    SmallAnalysisPlan,
    SequentialAnalysisState,
    SequentialLoopCheckpoint,
    StopAnalysis,
)
from reporting.repository import ReportRepository
from reporting.kernel import ANALYSIS_METHOD_REGISTRY_VERSION, KERNEL_VERSION
from reporting.observation import OBSERVATION_BUILDER_VERSION
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION
from reporting.validators import ActionValidator
from tests.reporting_fixtures import make_jump_report


class _ServiceFakeAgent:
    model_name = "fake-model"
    prompt_version = "fake-prompt/1"

    def __init__(self, *, fail=False, invalid_claim=False):
        self.fail = fail
        self.invalid_claim = invalid_claim

    def propose_plan(self, observation, state):
        if self.fail:
            raise RuntimeError("model unavailable")
        record_set_id = observation.report_manifest.record_sets[0].record_set_id
        return InvestigationDecision(
            rationale="test",
            plan=SmallAnalysisPlan(
                questions=(
                    AnalysisQuestion(
                        question_id="q1",
                        description="temporal",
                        dimensions=("temporal",),
                        metric_codes=("contact_time_s",),
                        reason="synthetic",
                        stop_condition="verified",
                    ),
                ),
                nodes=(
                    AnalysisNode(
                        node_id="n1",
                        tool_name="analyze_current_session",
                        analysis_method="verify_temporal_change",
                        inputs={"record_set_id": record_set_id, "metric_codes": ["contact_time_s"]},
                        question_id="q1",
                        purpose="verify",
                    ),
                ),
            ),
        )

    def review_evidence(self, observation, state, evidence):
        return EvidenceReviewDecision(evidence_sufficient=True, rationale="enough")

    def synthesize(self, observation, state, evidence):
        item = evidence[0].items[0]
        predicate_ref = next(
            predicate.predicate_evidence_id
            for predicate in item.predicates
            if predicate.predicate == "increase"
        )
        return DraftAnalysisPackage(
            summary="draft",
            claims=(
                DraftAnalysisClaim(
                    claim_id="c1",
                    claim_type="derived",
                    text_template=(
                        "后半程触地时间增加了0.1秒。"
                        if self.invalid_claim
                        else "后半程触地时间增加，前后差值为{difference}。"
                    ),
                    evidence_refs=(item.evidence_id,),
                    tool_run_ids=(item.tool_run_id,),
                    predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=predicate_ref),),
                    numeric_bindings=(
                        NumericBinding(binding_id="difference", source_type="evidence", source_ref=item.evidence_id, value_key="difference"),
                    ) if not self.invalid_claim else (),
                ),
            ),
        )


class _RepairingAgent(_ServiceFakeAgent):
    def __init__(self):
        super().__init__(invalid_claim=True)
        self.repair_calls = 0

    def repair_synthesis(
        self,
        observation,
        state,
        evidence,
        draft,
        error_code,
        error_message,
    ):
        self.repair_calls += 1
        item = evidence[0].items[0]
        repaired_claim = draft.claims[0].model_copy(
            update={
                "text_template": "后半程触地时间增加了{difference}。",
                "numeric_bindings": (
                    NumericBinding(
                        binding_id="difference",
                        source_type="evidence",
                        source_ref=item.evidence_id,
                        value_key="difference",
                    ),
                ),
            }
        )
        return draft.model_copy(update={"claims": (repaired_claim,)})


class _LegacyFailsAfterEvidence(_ServiceFakeAgent):
    def synthesize(self, observation, state, evidence):
        raise RuntimeError("synthesis unavailable")


class _ContentDigestAgent(_ServiceFakeAgent):
    prompt_content_digest = "f" * 64


class _SequentialServiceFakeAgent(_ServiceFakeAgent):
    sequential_prompt_version = "fake-sequential-prompt/1"

    def decide(self, observation, state, evidence, skill_context):
        if state.tool_call_count:
            return StopAnalysis(
                reason_code="evidence_sufficient",
                reason="证据充分",
            )
        record_set_id = observation.report_manifest.record_sets[0].record_set_id
        return NextAnalysisAction(
            action_id="a1",
            hypothesis=HypothesisTarget(
                hypothesis_id="h1",
                statement="触地时间是否增加",
                dimensions=("temporal",),
                metric_codes=("contact_time_s",),
                target_predicate="increase",
                reason="观察到候选变化",
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

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        return self.synthesize(observation, state, evidence)


class _SequentialRepairingAgent(_SequentialServiceFakeAgent):
    def __init__(self):
        super().__init__(invalid_claim=True)
        self.synthesis_calls = 0
        self.repair_calls = 0

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        self.synthesis_calls += 1
        return self.synthesize(observation, state, evidence)

    def repair_synthesis(
        self,
        observation,
        state,
        evidence,
        draft,
        error_code,
        error_message,
    ):
        return _RepairingAgent.repair_synthesis(
            self,
            observation,
            state,
            evidence,
            draft,
            error_code,
            error_message,
        )


class _SequentialFailsAfterEvidence(_SequentialServiceFakeAgent):
    def decide(self, observation, state, evidence, skill_context):
        if state.tool_call_count:
            raise RuntimeError("failure after completed Tool call")
        return super().decide(observation, state, evidence, skill_context)


class _MaliciousRepairingAgent(_RepairingAgent):
    def repair_synthesis(
        self,
        observation,
        state,
        evidence,
        draft,
        error_code,
        error_message,
    ):
        repaired = super().repair_synthesis(
            observation,
            state,
            evidence,
            draft,
            error_code,
            error_message,
        )
        claim = repaired.claims[0].model_copy(
            update={"text_template": "完全不同的发现为{difference}。"}
        )
        return repaired.model_copy(update={"claims": (claim,)})


class _ProcessInterrupted(BaseException):
    pass


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class _DeadlineStopAgent(_SequentialServiceFakeAgent):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.synthesis_calls = 0

    def decide(self, observation, state, evidence, skill_context):
        self.clock.advance(2.1)
        return StopAnalysis(reason_code="evidence_sufficient", reason="late")

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        self.synthesis_calls += 1
        return DraftAnalysisPackage(summary="受限分析", claims=())


class _SynthesisTimeoutAgent(_DeadlineStopAgent):
    def __init__(self, clock):
        super().__init__(clock)
        self.fail_synthesis = True

    def decide(self, observation, state, evidence, skill_context):
        return StopAnalysis(reason_code="evidence_sufficient", reason="done")

    def synthesize_sequential(
        self, observation, state, evidence, skill_context
    ):
        self.synthesis_calls += 1
        if self.fail_synthesis:
            raise ReportAgentCallTimeout("synthesis")
        return DraftAnalysisPackage(summary="重试成功", claims=())


class _RepairTimeoutAgent(_SequentialRepairingAgent):
    def repair_synthesis(self, *args, **kwargs):
        raise ReportAgentCallTimeout("claim_repair")


class _InterruptingRepository(ReportRepository):
    interrupt_phase = None

    def save_analysis_checkpoint(self, run_id, checkpoint):
        super().save_analysis_checkpoint(run_id, checkpoint)
        if checkpoint.phase == self.interrupt_phase:
            self.interrupt_phase = None
            raise _ProcessInterrupted(checkpoint.phase)


def _service(tmp_path, agent, **service_kwargs):
    store = SubjectStore(tmp_path / "service.sqlite3")
    session_id = store.record_session(
        None,
        default_jump_config(),
        make_jump_report([0.2] * 6 + [0.3] * 6),
    )
    repository = ReportRepository(store)
    return store, session_id, repository, ReportAnalysisService(
        repository, agent=agent, **service_kwargs
    )


class _FakeRAGPipeline:
    def __init__(self):
        self.contexts = []

    def run(self, context):
        self.contexts.append(context)
        return degraded_rag_result(context.package_digest, "fixture_degraded")


def _statuses(store):
    with sqlite3.connect(store.db_path) as conn:
        return [row[0] for row in conn.execute("SELECT status FROM report_analyses ORDER BY id")]


def _metrics_rows(store):
    with sqlite3.connect(store.db_path) as conn:
        return [row[0] for row in conn.execute("SELECT run_metrics_json FROM report_analyses ORDER BY id")]


def test_service_returns_only_validated_rendered_analysis(tmp_path):
    store, session_id, repository, service = _service(tmp_path, _ServiceFakeAgent())

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert result.cycle_count == 1
    assert _statuses(store) == ["validated"]
    assert _metrics_rows(store)[0] is not None
    metrics = json.loads(_metrics_rows(store)[0])
    assert metrics["analysis_tool_registry_version"] == "analysis-tool-registry/1.0"
    assert metrics["analysis_method_registry_version"] == "analysis-method-registry/1.0"
    assert metrics["kernel_version"] == "analysis-kernel/1.0"
    assert "operator_registry_version" not in metrics
    assert repository.get_latest_validated_analysis(
        session_id,
        DataAccessScope(),
        result.package_digest,
    )["analysis_run_id"] == result.analysis_run_id


def test_service_runs_rag_only_after_claim_validation_and_degrades_independently(tmp_path):
    rag_pipeline = _FakeRAGPipeline()
    store, session_id, _, service = _service(
        tmp_path,
        _ServiceFakeAgent(),
        rag_pipeline=rag_pipeline,
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.analysis_schema_version == "analysis-schema/4.0"
    assert result.claims[0].text.endswith("0.1 s。")
    assert rag_pipeline.contexts[0].claims[0].claim_id == "c1"
    assert rag_pipeline.contexts[0].claims[0].metric_codes == ("contact_time_s",)
    assert rag_pipeline.contexts[0].claims[0].text.endswith("0.1 s。")
    assert "{" not in rag_pipeline.contexts[0].claims[0].text
    assert result.rag_audit.status == "degraded"
    assert result.rag_audit.error_code == "fixture_degraded"
    assert _statuses(store) == ["validated"]


def test_service_reports_rag_initialization_degradation_without_pipeline(tmp_path):
    store, session_id, _, service = _service(
        tmp_path,
        _ServiceFakeAgent(),
        rag_unavailable_error_code="rag_initialization_failed",
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert result.rag_audit.status == "degraded"
    assert result.rag_audit.error_code == "rag_initialization_failed"
    assert _statuses(store) == ["validated"]


def test_service_uses_sequential_loop_for_agent_with_decide(tmp_path):
    store, session_id, _, service = _service(
        tmp_path, _SequentialServiceFakeAgent()
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert result.cycle_count == 1
    assert result.replan_count == 0
    assert result.prompt_version == "fake-sequential-prompt/1"
    assert _statuses(store) == ["validated"]
    with sqlite3.connect(store.db_path) as conn:
        checkpoint_count = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]
    assert checkpoint_count >= 4


def test_service_resumes_matching_running_action_checkpoint(tmp_path):
    agent = _SequentialServiceFakeAgent()
    store, session_id, repository, service = _service(tmp_path, agent)
    package = repository.get_package(session_id)
    record_set_id = package.record_sets[0].record_set_id
    action = NextAnalysisAction(
        action_id="a1",
        hypothesis=HypothesisTarget(
            hypothesis_id="h1",
            statement="触地时间是否增加",
            dimensions=("temporal",),
            metric_codes=("contact_time_s",),
            target_predicate="increase",
            reason="观察到候选变化",
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
    validated = ActionValidator().validate_action(
        action, package, DataAccessScope()
    )
    context = ReportAnalysisSkillLoader().load_initial("Jump Test")
    state = AnalysisStateReducer().begin_action(
        SequentialAnalysisState(
            loaded_skill_references=context.loaded_reference_ids
        ),
        validated,
    )
    run_id = repository.create_analysis_run(
        session_id,
        DataAccessScope(),
        package.metadata.package_digest,
        model_name=agent.model_name,
        prompt_version=agent.sequential_prompt_version,
    )
    repository.save_analysis_checkpoint(
        run_id,
        SequentialLoopCheckpoint(
            phase="action_accepted",
            session_id=session_id,
            package_digest=package.metadata.package_digest,
            data_access_scope=DataAccessScope(),
            state=state,
            pending_action=validated,
            skill_version=context.skill_version,
            skill_content_digest=context.content_digest,
            observation_builder_version=OBSERVATION_BUILDER_VERSION,
            analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
            analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
            kernel_version=KERNEL_VERSION,
        ),
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.analysis_run_id == run_id
    assert result.claims[0].text.endswith("0.1 s。")
    assert _statuses(store) == ["validated"]
    with sqlite3.connect(store.db_path) as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM report_analyses"
        ).fetchone()[0]
    assert run_count == 1


def test_service_resumes_claim_repair_without_repeating_synthesis_or_tools(
    tmp_path,
):
    store = SubjectStore(tmp_path / "claim-repair-resume.sqlite3")
    session_id = store.record_session(
        None,
        default_jump_config(),
        make_jump_report([0.2] * 6 + [0.3] * 6),
    )
    repository = _InterruptingRepository(store)
    repository.interrupt_phase = "claim_repair_pending"
    agent = _SequentialRepairingAgent()
    service = ReportAnalysisService(repository, agent=agent)

    with pytest.raises(_ProcessInterrupted):
        service.analyze(session_id, DataAccessScope())

    assert _statuses(store) == ["running"]
    assert agent.synthesis_calls == 1
    assert agent.repair_calls == 0
    with sqlite3.connect(store.db_path) as conn:
        tool_runs_before = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims[0].text.endswith("0.1 s。")
    assert agent.synthesis_calls == 1
    assert agent.repair_calls == 1
    assert _statuses(store) == ["validated"]
    with sqlite3.connect(store.db_path) as conn:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM report_analyses"
        ).fetchone()[0]
        checkpoint_count = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]
    assert run_count == 1
    assert checkpoint_count > tool_runs_before


def test_service_allows_one_validator_guided_synthesis_repair(tmp_path):
    agent = _RepairingAgent()
    store, session_id, _, service = _service(tmp_path, agent)

    result = service.analyze(session_id, DataAccessScope())

    assert agent.repair_calls == 1
    assert result.claims[0].text.endswith("0.1 s。")
    assert _statuses(store) == ["validated"]


def test_service_rejects_repair_that_rewrites_claim_semantics(tmp_path):
    agent = _MaliciousRepairingAgent()
    store, session_id, _, service = _service(tmp_path, agent)

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope())

    assert exc_info.value.code == "repair_scope_violation"
    assert _statuses(store) == ["rejected"]


def test_failed_sequential_run_records_completed_tool_work(tmp_path):
    store, session_id, _, service = _service(
        tmp_path, _SequentialFailsAfterEvidence()
    )

    with pytest.raises(ReportAnalysisError):
        service.analyze(session_id, DataAccessScope())

    metrics = json.loads(_metrics_rows(store)[0])
    assert _statuses(store) == ["failed"]
    assert metrics["cycle_count"] == 1
    assert metrics["agent_level_node_count"] == 1
    assert metrics["tool_run_count"] == 1


def test_failed_legacy_run_records_completed_tool_work(tmp_path):
    store, session_id, _, service = _service(
        tmp_path, _LegacyFailsAfterEvidence()
    )

    with pytest.raises(ReportAnalysisError):
        service.analyze(session_id, DataAccessScope())

    metrics = json.loads(_metrics_rows(store)[0])
    assert _statuses(store) == ["failed"]
    assert metrics["cycle_count"] == 1
    assert metrics["agent_level_node_count"] == 1
    assert metrics["tool_run_count"] == 1


def test_analysis_package_exposes_full_prompt_content_digest(tmp_path):
    _, session_id, _, service = _service(tmp_path, _ContentDigestAgent())

    result = service.analyze(session_id, DataAccessScope())

    assert result.prompt_content_digest == "f" * 64


@pytest.mark.parametrize(
    "agent,expected_status,expected_code",
    [
        (_ServiceFakeAgent(fail=True), "failed", "analysis_failed"),
        (_ServiceFakeAgent(invalid_claim=True), "rejected", "unbound_numeric_literal"),
    ],
)
def test_service_never_persists_partial_text_on_failure(
    tmp_path, agent, expected_status, expected_code
):
    store, session_id, _, service = _service(tmp_path, agent)

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope())

    assert exc_info.value.code == expected_code
    assert _statuses(store) == [expected_status]
    assert _metrics_rows(store)[0] is not None


def test_service_rejects_external_scope_before_any_analysis_run(tmp_path):
    store, session_id, _, service = _service(tmp_path, _ServiceFakeAgent())

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope(longitudinal=True))

    assert exc_info.value.code == "external_scope_not_implemented"
    assert _statuses(store) == []


def test_initial_skill_failure_is_converted_to_report_analysis_error(tmp_path):
    class _FailingSkillLoader:
        def load_initial(self, test_type):
            raise SkillLoadError("skill_missing", "skill unavailable")

    store, session_id, _, service = _service(
        tmp_path,
        _SequentialServiceFakeAgent(),
        skill_loader=_FailingSkillLoader(),
    )

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope())

    assert exc_info.value.code == "skill_missing"
    assert _statuses(store) == []


def test_disabled_external_tool_is_rejected_before_repository_detail_read():
    class _RepositorySpy:
        def __init__(self):
            self.package_reads = 0

        def get_package(self, session_id):
            self.package_reads += 1
            raise AssertionError("report detail must not be read")

    repository = _RepositorySpy()
    service = ReportAnalysisService(repository, agent=_ServiceFakeAgent())

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(1, DataAccessScope(longitudinal=True))

    assert exc_info.value.code == "external_scope_not_implemented"
    assert repository.package_reads == 0


def test_current_session_analysis_does_not_probe_external_scope(tmp_path):
    store = SubjectStore(tmp_path / "repository-spy.sqlite3")
    session_id = store.record_session(
        None,
        default_jump_config(),
        make_jump_report([0.2] * 6 + [0.3] * 6),
    )
    wrapped = ReportRepository(store)

    class _RepositorySpy:
        def __init__(self, repository):
            self.repository = repository
            self.external_scope_reads = 0

        def get_scope_availability(self, target_session_id):
            self.external_scope_reads += 1
            raise AssertionError("current-session analysis must not probe history")

        def __getattr__(self, name):
            return getattr(self.repository, name)

    spy = _RepositorySpy(wrapped)
    service = ReportAnalysisService(spy, agent=_ServiceFakeAgent())

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims
    assert spy.external_scope_reads == 0


def test_service_defaults_to_ablation_b_execution_policy(tmp_path):
    _, _, _, service = _service(tmp_path, _ServiceFakeAgent())

    assert service._max_replans == 0
    assert service._observation_builder._include_analysis_sketch is True
    assert service._observation_builder._include_compact_series is True
    assert service._observation_builder._include_screening_cues is False


def test_investigation_deadline_stops_new_decisions_and_still_synthesizes(
    tmp_path,
):
    clock = _FakeClock()
    agent = _DeadlineStopAgent(clock)
    store, session_id, _, service = _service(
        tmp_path,
        agent,
        deadline_policy=ReportAnalysisDeadlinePolicy(
            total_seconds=3,
            synthesis_reserve_seconds=1,
            max_model_request_seconds=1,
        ),
        clock=clock,
    )

    result = service.analyze(session_id, DataAccessScope())

    assert result.claims == ()
    assert "investigation_deadline_reached" in result.overall_limitations
    assert agent.synthesis_calls == 1
    assert _statuses(store) == ["validated"]
    metrics = json.loads(_metrics_rows(store)[0])
    assert metrics["stop_reason_code"] == "investigation_deadline_reached"
    assert metrics["investigation_elapsed_ms"] == 2100


def test_synthesis_timeout_is_failed_non_resumable_and_retry_creates_new_run(
    tmp_path,
):
    clock = _FakeClock()
    agent = _SynthesisTimeoutAgent(clock)
    store, session_id, _, service = _service(
        tmp_path,
        agent,
        deadline_policy=ReportAnalysisDeadlinePolicy(
            total_seconds=3,
            synthesis_reserve_seconds=1,
            max_model_request_seconds=1,
        ),
        clock=clock,
    )

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope())

    assert exc_info.value.code == "analysis_timeout"
    assert exc_info.value.timeout_stage == "synthesis"
    first_run_id = exc_info.value.analysis_run_id
    assert _statuses(store) == ["failed"]
    metrics = json.loads(_metrics_rows(store)[0])
    assert metrics["timeout_stage"] == "synthesis"

    agent.fail_synthesis = False
    result = service.analyze(session_id, DataAccessScope())

    assert result.analysis_run_id != first_run_id
    assert _statuses(store) == ["failed", "validated"]


def test_claim_repair_timeout_is_reported_without_partial_package(tmp_path):
    clock = _FakeClock()
    store, session_id, _, service = _service(
        tmp_path,
        _RepairTimeoutAgent(),
        deadline_policy=ReportAnalysisDeadlinePolicy(
            total_seconds=3,
            synthesis_reserve_seconds=1,
            max_model_request_seconds=1,
        ),
        clock=clock,
    )

    with pytest.raises(ReportAnalysisError) as exc_info:
        service.analyze(session_id, DataAccessScope())

    assert exc_info.value.code == "analysis_timeout"
    assert exc_info.value.timeout_stage == "claim_repair"
    assert _statuses(store) == ["failed"]
    with sqlite3.connect(store.db_path) as conn:
        package = conn.execute(
            "SELECT analysis_package_json FROM report_analyses"
        ).fetchone()[0]
    assert package is None


def test_invalid_deadline_environment_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("REPORT_ANALYSIS_DEADLINE_SECONDS", "20")
    store = SubjectStore(tmp_path / "deadline-config.sqlite3")

    with pytest.raises(ReportAnalysisDeadlineConfigurationError):
        ReportAnalysisService(
            ReportRepository(store), agent=_SequentialServiceFakeAgent()
        )
