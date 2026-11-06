"""Empty question drafts retain verified scope statistics and checkpoint recovery."""

import json

import pytest

from agent.report.models import ReportFollowupRequest
from agent.report.service import ReportAnalysisError
from agent.report.sequential_loop import SequentialAnalysisLoop
from reporting.models import DataAccessScope, DraftAnalysisPackage, ReportQuestionPlan, StopAnalysis
from tests.test_report_analysis_service import _service, _statuses


class _EmptyQuestionAgent:
    model_name = "empty-question-test"
    sequential_prompt_version = "empty-question-test/1"

    def __init__(self):
        self.observations = []
        self.synthesis_calls = 0

    def plan_question(self, observation, question, parent_context):
        self.observations.append(observation)
        return ReportQuestionPlan(
            record_set_id=observation.report_manifest.record_sets[0].record_set_id,
            metric_codes=("contact_time_s",), scope_basis="report", segment="second_half",
        )

    def decide(self, observation, state, evidence, skill_context):
        self.observations.append(observation)
        return StopAnalysis(reason_code="evidence_sufficient", reason="范围统计已完成")

    def synthesize_sequential(self, observation, state, evidence, skill_context):
        self.observations.append(observation)
        self.synthesis_calls += 1
        return DraftAnalysisPackage(summary="", claims=())


def _request(session_id):
    return ReportFollowupRequest(
        session_id=session_id, data_access_scope=DataAccessScope(), question="后半段触地时间怎么样",
    )


def test_empty_question_draft_uses_summary_through_checkpoint_and_validator(tmp_path, monkeypatch):
    agent = _EmptyQuestionAgent()
    store, session_id, repository, service = _service(tmp_path, agent)
    validate = service._claim_validator.validate
    validated_drafts = []

    def validate_checkpointed(draft, *args, **kwargs):
        with repository._connect() as conn:
            saved = json.loads(conn.execute(
                "SELECT checkpoint_json FROM report_analysis_checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()[0])
        assert saved["draft"] == draft.model_dump(mode="json")
        assert saved["phase"] == "draft_generated"
        assert len(draft.claims) == 1
        assert kwargs["allowed_fact_refs"] == frozenset()
        validated_drafts.append(draft)
        return validate(draft, *args, **kwargs)

    monkeypatch.setattr(service._claim_validator, "validate", validate_checkpointed)
    answer = service.ask(_request(session_id))

    assert len(validated_drafts) == 1
    assert len(answer.claims) == 1
    claim = answer.claims[0]
    item = answer.evidence[0].items[0]
    assert claim.claim_type == "derived"
    assert claim.fact_refs == ()
    assert claim.evidence_refs == (item.evidence_id,)
    assert claim.tool_run_ids == (item.tool_run_id,)
    assert claim.predicate_bindings[0].predicate_evidence_ref == item.predicates[0].predicate_evidence_id
    assert "所选有效样本 6 条" in claim.text
    assert "均值 0.3 s" in claim.text
    assert "范围 0.3 s 至 0.3 s" in claim.text
    assert answer.presentation.headline_claim_ids == (claim.claim_id,)
    assert _statuses(store) == ["validated"]


def test_empty_question_draft_resumes_without_repeating_tools_or_synthesis(tmp_path, monkeypatch):
    agent = _EmptyQuestionAgent()
    store, session_id, repository, service = _service(tmp_path, agent)
    save = repository.save_analysis_checkpoint

    def interrupt_empty_draft(run_id, checkpoint):
        save(run_id, checkpoint)
        if checkpoint.phase == "draft_generated" and not checkpoint.draft.claims:
            raise KeyboardInterrupt()

    monkeypatch.setattr(repository, "save_analysis_checkpoint", interrupt_empty_draft)
    with pytest.raises(KeyboardInterrupt):
        service.ask(_request(session_id))
    assert _statuses(store) == ["running"]
    with repository._connect() as conn:
        run_id = conn.execute("SELECT analysis_run_id FROM report_analyses").fetchone()[0]
    monkeypatch.setattr(repository, "save_analysis_checkpoint", save)

    answer = service.ask(_request(session_id))

    assert answer.analysis_run_id == run_id
    assert len(answer.claims) == 1
    assert len(answer.evidence) == 1
    assert agent.synthesis_calls == 1
    assert _statuses(store) == ["validated"]


@pytest.mark.parametrize("evidence_state", ("missing", "inconclusive", "unsupported"))
def test_empty_question_draft_rejects_unusable_summary(tmp_path, monkeypatch, evidence_state):
    agent = _EmptyQuestionAgent()
    store, session_id, _, service = _service(tmp_path, agent)
    run = SequentialAnalysisLoop.run

    def run_without_summary(*args, **kwargs):
        result = run(*args, **kwargs)
        if evidence_state == "missing":
            return result.model_copy(update={"evidence": ()})
        bundle = result.evidence[0]
        item = bundle.items[0]
        if evidence_state == "inconclusive":
            item = item.model_copy(update={"analysis_status": "inconclusive"})
        else:
            predicates = tuple(predicate.model_copy(update={"supported": False}) for predicate in item.predicates)
            item = item.model_copy(update={"predicates": predicates})
        return result.model_copy(update={"evidence": (bundle.model_copy(update={"items": (item,)}),)})

    monkeypatch.setattr(SequentialAnalysisLoop, "run", run_without_summary)
    with pytest.raises(ReportAnalysisError) as error:
        service.ask(_request(session_id))

    assert error.value.code == "question_summary_unavailable"
    assert _statuses(store) == ["rejected"]


def test_question_observations_hide_methods_that_require_full_report(tmp_path):
    agent = _EmptyQuestionAgent()
    _, session_id, repository, service = _service(tmp_path, agent)
    service.ask(_request(session_id))

    for observation in agent.observations:
        methods = {method.analysis_method for tool in observation.available_analysis_capabilities
                   for method in tool.available_methods}
        assert "summarize_records" in methods
        assert not methods.intersection({"verify_exclusion_robustness", "quality_scope_check"})

    original = service._build_observation(repository.get_package(session_id), DataAccessScope())
    methods = {method.analysis_method for tool in original.available_analysis_capabilities
               for method in tool.available_methods}
    assert {"verify_exclusion_robustness", "quality_scope_check"}.issubset(methods)
