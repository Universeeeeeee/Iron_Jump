"""End-to-end question scope, persistence, retry and request validation."""

import pytest
from pydantic import ValidationError

from agent.report.agent import ReportAgentCallTimeout
from agent.report.models import ReportFollowupRequest
from agent.report.service import ReportAnalysisService, ReportAnalysisError
from config.treadmill_config import TreadmillGaitConfig
from data.subject_store import SubjectStore
from reporting.models import (
    DataAccessScope, DraftAnalysisClaim, DraftAnalysisPackage, NumericBinding,
    PredicateBinding, ReportQuestionPlan, StopAnalysis,
)
from reporting.questions import ReportQuestionError, resolve_question_selection
from reporting.repository import ReportRepository
from tests.reporting_fixtures import make_treadmill_report, make_jump_package
from tests.test_report_analysis_service import _ServiceFakeAgent


class QuestionAgent:
    model_name = "question-test"
    sequential_prompt_version = "question-test/1"

    def __init__(self):
        self.plan_options = {}
        self.observations = []
        self.fail_synthesis = False
        self.global_fact = None

    def plan_question(self, observation, question, parent_context):
        self.observations.append((question, parent_context))
        return ReportQuestionPlan(
            record_set_id=observation.report_manifest.record_sets[0].record_set_id,
            metric_codes=("contact_time_s",), **self.plan_options,
        )

    def decide(self, observation, state, evidence, skill_context):
        assert observation.question_context
        assert observation.authoritative_facts == ()
        return StopAnalysis(reason_code="evidence_sufficient", reason="范围统计已回答问题")

    def synthesize_sequential(self, observation, state, evidence, skill_context):
        if self.fail_synthesis:
            raise ReportAgentCallTimeout("synthesis")
        item = evidence[0].items[0]
        predicate = next(p for p in item.predicates if p.predicate == "comparison_supported")
        if self.global_fact:
            claim = DraftAnalysisClaim(claim_id="c1", claim_type="descriptive", text_template="均值为{mean}。",
                fact_refs=(self.global_fact,), numeric_bindings=(NumericBinding(binding_id="mean", source_type="fact", source_ref=self.global_fact),))
        else:
            claim = DraftAnalysisClaim(claim_id="c1", claim_type="derived", text_template="所选均值为{mean}。",
                evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
                predicate_bindings=(PredicateBinding(predicate="comparison_supported", predicate_evidence_ref=predicate.predicate_evidence_id),),
                numeric_bindings=(NumericBinding(binding_id="mean", source_type="evidence", source_ref=item.evidence_id, value_key="contact_time_s_mean"),))
        return DraftAnalysisPackage(summary="范围统计", claims=(claim,))


def setup_question_service(tmp_path):
    store = SubjectStore(tmp_path / "questions.sqlite3")
    report = make_treadmill_report([.2]*6+[.4]*6, [.3]*6+[.5]*6)
    session_id = store.record_session(None, TreadmillGaitConfig(stop_type='End of Time', test_length='01:00'), report)
    repository = ReportRepository(store)
    original = ReportAnalysisService(repository, agent=_ServiceFakeAgent()).analyze(session_id, DataAccessScope())
    agent = QuestionAgent()
    return ReportAnalysisService(repository, agent=agent), repository, agent, original


def request(parent, question="触地时间怎么样", **changes):
    return ReportFollowupRequest(session_id=parent.session_id, data_access_scope=DataAccessScope(),
        question=question, parent_analysis_run_id=parent.analysis_run_id, **changes)


def test_followup_half_then_side_inherits_records_and_preserves_default_latest(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"scope_basis": "report", "segment": "second_half"}
    half = service.ask(request(original, "只看后半程"))
    assert half.request_digest
    assert len(half.question_context.selection.record_refs) == 12
    assert half.evidence[0].items[0].numeric_values['contact_time_s_mean'] == pytest.approx(.45)
    agent.plan_options = {"scope_basis": "previous", "side": "left"}
    left = service.ask(request(half, "其中左侧呢", selected_claim_id="c1"))
    assert len(left.question_context.selection.record_refs) == 6
    assert set(left.question_context.selection.record_refs) < set(half.question_context.selection.record_refs)
    assert left.evidence[0].items[0].numeric_values['contact_time_s_mean'] == pytest.approx(.4)
    assert service.get_latest(original.session_id, DataAccessScope())['analysis_run_id'] == original.analysis_run_id
    saved = repository.get_validated_analysis(left.analysis_run_id, left.session_id, DataAccessScope(), left.package_digest)
    assert saved['question_context']['question'] == '其中左侧呢'
    assert saved['request_digest'] != half.request_digest


def test_repeated_report_half_does_not_keep_halving_previous_selection(tmp_path):
    service, _, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"scope_basis": "report", "segment": "second_half"}
    first = service.ask(request(original, "后半程"))
    second = service.ask(request(first, "还是后半程"))
    assert second.question_context.selection.record_refs == first.question_context.selection.record_refs


def test_switching_sides_rebuilds_the_same_report_half(tmp_path):
    service, _, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"scope_basis": "report", "segment": "second_half"}
    half = service.ask(request(original, "只看后半程"))
    agent.plan_options = {"side": "left"}
    left = service.ask(request(half, "其中左侧呢"))
    agent.plan_options = {"scope_basis": "report", "segment": "second_half", "side": "right"}
    right = service.ask(request(left, "那右侧呢"))
    left_refs = set(left.question_context.selection.record_refs)
    right_refs = set(right.question_context.selection.record_refs)
    assert not left_refs.intersection(right_refs)
    assert left_refs.union(right_refs) == set(half.question_context.selection.record_refs)
    assert right.evidence[0].items[0].numeric_values["contact_time_s_mean"] == pytest.approx(.5)


@pytest.mark.parametrize("bounds, ordinals", [
    ({"start_record": 2, "end_record": 4}, (1, 2, 3)),
    ({"start_time_s": .6, "end_time_s": 1.8}, (1, 2, 3)),
    ({"start_record": 3}, (2, 3, 4, 5)),
    ({"end_time_s": 0}, (0,)),
])
def test_question_range_bounds_are_inclusive(bounds, ordinals):
    package = make_jump_package([.2] * 6)
    record_set = package.record_sets[0]
    plan = ReportQuestionPlan(
        record_set_id=record_set.record_set_id,
        metric_codes=("contact_time_s",), **bounds,
    )
    selection = resolve_question_selection(package, plan, {})
    assert selection.record_refs == tuple(record_set.records[i].record_id for i in ordinals)


@pytest.mark.parametrize("options, code", [
    ({"end_record": 7}, "invalid_question_selection"),
    ({"start_time_s": 10}, "empty_selection"),
    ({"side": "left"}, "empty_selection"),
    ({"metric_codes": ("unavailable_metric",)}, "invalid_question_selection"),
])
def test_unavailable_question_ranges_are_rejected(options, code):
    package = make_jump_package([.2] * 6)
    plan = ReportQuestionPlan.model_validate({
        "record_set_id": package.record_sets[0].record_set_id,
        "metric_codes": ("contact_time_s",), **options,
    })
    with pytest.raises(ReportQuestionError) as error:
        resolve_question_selection(package, plan, {})
    assert error.value.code == code


def test_question_chart_type_is_applied_to_answer(tmp_path):
    service, _, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"chart_type": "segment_comparison"}
    answer = service.ask(request(original, "画分组均值图"))
    assert answer.presentation.charts[0].chart_type == 'segment_comparison'
    assert '完整有效记录' in answer.presentation.charts[0].grouping


def test_question_limitations_come_from_evidence_instead_of_generic_disclaimers(tmp_path, monkeypatch):
    service, _, agent, original = setup_question_service(tmp_path)
    synthesize = agent.synthesize_sequential

    def with_disclaimers(*args):
        draft = synthesize(*args)
        claim = draft.claims[0].model_copy(update={
            "limitations": ("未与其他范围比较。",),
        })
        return draft.model_copy(update={
            "claims": (claim,), "overall_limitations": ("未查询历史记录。",),
        })

    monkeypatch.setattr(agent, "synthesize_sequential", with_disclaimers)
    answer = service.ask(request(original))
    assert answer.claims[0].limitations == answer.evidence[0].items[0].limitations
    assert answer.overall_limitations == ()


def test_wrong_parent_is_rejected_before_planning(tmp_path):
    service, _, agent, original = setup_question_service(tmp_path)
    invalid = request(original).model_copy(update={'parent_analysis_run_id': 'missing-run'})
    with pytest.raises(ReportAnalysisError, match='不匹配'):
        service.ask(invalid)
    assert agent.observations == []


def test_scoped_question_cannot_use_global_fact(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    package = repository.get_package(original.session_id)
    agent.global_fact = next(f.fact_id for f in package.scalar_facts if f.metric_code == 'contact_time_s' and f.statistic == 'mean')
    agent.plan_options = {"segment": "second_half"}
    with pytest.raises(ReportAnalysisError) as error:
        service.ask(request(original))
    assert error.value.code == 'fact_outside_question_scope'


def test_inspection_answer_uses_verified_range_statistics_even_if_model_draft_is_invalid(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    package = repository.get_package(original.session_id)
    agent.global_fact = next(f.fact_id for f in package.scalar_facts if f.metric_code == 'contact_time_s' and f.statistic == 'mean')
    agent.plan_options = {"intent": "inspect", "segment": "second_half"}
    answer = service.ask(request(original, "后半程触地时间均值是多少？"))
    assert answer.claims[0].fact_refs == ()
    assert answer.claims[0].evidence_refs == (answer.evidence[0].items[0].evidence_id,)
    assert "均值 0.45 s" in answer.claims[0].text


def test_synthesis_timeout_retry_creates_new_run_for_same_selection(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {'segment': 'second_half'}
    agent.fail_synthesis = True
    query = request(original, '后半程的均值')
    with pytest.raises(ReportAnalysisError) as error:
        service.ask(query)
    assert error.value.code == 'analysis_timeout'
    run_id = error.value.analysis_run_id
    agent.fail_synthesis = False
    answer = service.ask(query)
    assert answer.analysis_run_id != run_id
    assert answer.evidence[0].items[0].sample_counts['selected'] == 12


def test_interrupted_question_resumes_without_repeating_summary(tmp_path, monkeypatch):
    service, repository, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {'segment': 'second_half'}
    query = request(original, '后半程的均值')
    synthesize = agent.synthesize_sequential

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(agent, 'synthesize_sequential', interrupt)
    with pytest.raises(KeyboardInterrupt):
        service.ask(query)
    with repository._connect() as conn:
        run_id = conn.execute(
            "SELECT analysis_run_id FROM report_analyses WHERE status = 'running'"
        ).fetchone()[0]
    monkeypatch.setattr(agent, 'synthesize_sequential', synthesize)
    answer = service.ask(query)
    assert answer.analysis_run_id == run_id
    assert len(answer.evidence) == 1
    assert answer.evidence[0].items[0].sample_counts['selected'] == 12


def test_old_selected_claim_without_evidence_requests_new_scope(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    legacy = original.model_dump(mode='json')
    legacy.pop('evidence')
    run_id = repository.create_analysis_run(original.session_id, DataAccessScope(), original.package_digest, model_name='old', prompt_version='old')
    legacy['analysis_run_id'] = run_id
    repository.finalize_analysis_run(run_id, 'validated', legacy)
    with pytest.raises(ReportQuestionError) as error:
        service.ask(request(original).model_copy(update={'parent_analysis_run_id':run_id, 'selected_claim_id':original.claims[0].claim_id}))
    assert error.value.code == 'legacy_evidence_unavailable'
    assert not agent.observations


def test_clarification_does_not_require_fake_record_or_metric():
    plan = ReportQuestionPlan(intent='clarify', clarification='请指定要查看的指标。')
    with pytest.raises(ReportQuestionError) as error:
        resolve_question_selection(make_jump_package([.2]*12), plan, {})
    assert error.value.code == 'question_needs_clarification'


@pytest.mark.parametrize('changes', [{'question':'   '}, {'question':'x'*2001}, {'selected_claim_id':'c1'}])
def test_invalid_question_request_rejected(changes):
    data = dict(session_id=1, data_access_scope={}, question='你好')
    data.update(changes)
    with pytest.raises(ValidationError):
        ReportFollowupRequest.model_validate(data)
