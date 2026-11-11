"""Historical questions execute against two snapshots and invalidate stale answers."""

import json

import pytest

from agent.report.models import ReportFollowupRequest
from agent.report.service import ReportAnalysisError, ReportAnalysisService
from config.treadmill_config import TreadmillGaitConfig
from data.subject_store import SubjectStore
from reporting.models import DataAccessScope, DraftAnalysisPackage, ReportQuestionPlan, StopAnalysis
from reporting.validators import ClaimValidationError, ClaimValidator
from reporting.repository import ReportRepository
from tests.reporting_fixtures import make_treadmill_report


class HistoryAgent:
    model_name = "history-test"
    sequential_prompt_version = "history-test/1"

    def __init__(self):
        self.options = {"comparison": "previous", "scope_basis": "report"}
        self.synthesis_calls = 0

    def plan_question(self, observation, question, parent_context):
        return ReportQuestionPlan(
            record_set_id=observation.report_manifest.record_sets[0].record_set_id,
            metric_codes=("contact_time_s",), **self.options,
        )

    def decide(self, observation, state, evidence, skill_context):
        assert evidence[0].items[0].longitudinal
        return StopAnalysis(reason_code="evidence_sufficient", reason="比较完成")

    def synthesize_sequential(self, *args):
        self.synthesis_calls += 1
        return DraftAnalysisPackage(summary="", claims=())


def setup_history(tmp_path, *, guest=False):
    store = SubjectStore(tmp_path / "history.sqlite3")
    subject = None if guest else store.create_subject("Runner", 1990)
    config = TreadmillGaitConfig(stop_type="End of Time", test_length="01:00")
    previous = store.record_session(subject, config, make_treadmill_report([.2]*6+[.3]*6, [.2]*6+[.4]*6))
    current = store.record_session(subject, config, make_treadmill_report([.2]*6+[.5]*6, [.2]*6+[.6]*6))
    repository = ReportRepository(store)
    agent = HistoryAgent()
    service = ReportAnalysisService(repository, agent=agent)
    query = ReportFollowupRequest(session_id=current, data_access_scope=DataAccessScope(longitudinal=True), question="比上次怎样")
    return store, repository, service, agent, query, previous


def test_history_question_binds_both_snapshots_and_preserves_ranges_through_chart_change(tmp_path):
    store, repository, service, agent, query, previous = setup_history(tmp_path)
    agent.options.update(segment="second_half")
    half = service.ask(query)
    item = half.evidence[0].items[0]
    assert item.sample_counts == {"previous": 12, "current": 12}
    assert item.numeric_values["contact_time_s_difference"] == pytest.approx(.2)
    assert item.longitudinal.previous.session_id == previous
    assert "本次减上次 0.2 s" in half.claims[0].text
    assert half.evidence[0].tool_runs[0].data_scope == "longitudinal"
    agent.options = {"comparison": "previous", "scope_basis": "previous", "side": "left"}
    left = service.ask(query.model_copy(update={"parent_analysis_run_id": half.analysis_run_id, "question": "其中左侧呢"}))
    assert left.evidence[0].items[0].sample_counts == {"previous": 6, "current": 6}
    assert left.evidence[0].items[0].numeric_values["contact_time_s_previous_mean"] == pytest.approx(.3)
    chart = left.presentation.charts[0]
    assert [group.mean for group in chart.groups] == pytest.approx([.3, .5])
    assert {p.session_id for group in chart.groups for p in group.points} == {previous, query.session_id}
    agent.options = {"comparison": "previous", "intent": "chart", "side": "left", "segment": "second_half", "chart_type": "side_distribution"}
    switched = service.ask(query.model_copy(update={"parent_analysis_run_id": left.analysis_run_id, "question": "换成分布图"}))
    assert switched.presentation.charts[0].groups == chart.groups
    assert switched.presentation.charts[0].chart_type == "side_distribution"
    assert service.get_saved(query.session_id, query.data_access_scope, switched.analysis_run_id)
    assert service.get_history(query.session_id, DataAccessScope()) == []


@pytest.mark.parametrize("change", ["edit", "delete", "insert_closer"])
def test_saved_historical_answers_invalidate_when_previous_snapshot_changes(tmp_path, change):
    store, repository, service, agent, query, previous = setup_history(tmp_path)
    answer = service.ask(query)
    with store._connect() as conn:
        if change == "edit":
            payload = json.loads(conn.execute("SELECT report_detail_json FROM test_sessions WHERE id = ?", (previous,)).fetchone()[0])
            payload["report_config_snapshot"] = {"algorithm": "new"}
            conn.execute("UPDATE test_sessions SET report_detail_json = ? WHERE id = ?", (json.dumps(payload), previous))
        elif change == "delete":
            conn.execute("DELETE FROM test_sessions WHERE id = ?", (previous,))
        else:
            conn.execute("UPDATE test_sessions SET started_at = '2026-01-01T00:00:00' WHERE id = ?", (previous,))
    if change == "insert_closer":
        store.record_session(1, TreadmillGaitConfig(stop_type="End of Time", test_length="01:00"),
                             make_treadmill_report([.2]*12, [.2]*12), started_at="2026-02-01T00:00:00")
    assert service.get_history(query.session_id, query.data_access_scope) == []
    with pytest.raises(ReportAnalysisError):
        service.get_saved(query.session_id, query.data_access_scope, answer.analysis_run_id)
    with pytest.raises(ReportAnalysisError):
        service.ask(query.model_copy(update={"parent_analysis_run_id": answer.analysis_run_id}))


@pytest.mark.parametrize("guest,authorized", [(True, True), (False, False)])
def test_guest_or_unauthorized_question_cannot_read_history(tmp_path, monkeypatch, guest, authorized):
    store, repository, service, agent, query, previous = setup_history(tmp_path, guest=guest)
    monkeypatch.setattr(repository, "get_previous_package", lambda *args: pytest.fail("history read"))
    query = query.model_copy(update={"data_access_scope": DataAccessScope(longitudinal=authorized)})
    with pytest.raises(ReportAnalysisError) as error:
        service.ask(query)
    assert error.value.code == "history_unavailable"


def test_interrupted_historical_answer_resumes_the_same_snapshot(tmp_path, monkeypatch):
    store, repository, service, agent, query, previous = setup_history(tmp_path)
    synthesize = agent.synthesize_sequential
    monkeypatch.setattr(agent, "synthesize_sequential", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        service.ask(query)
    with repository._connect() as conn:
        run_id = conn.execute("SELECT analysis_run_id FROM report_analyses WHERE status='running'").fetchone()[0]
    monkeypatch.setattr(agent, "synthesize_sequential", synthesize)
    answer = service.ask(query)
    assert answer.analysis_run_id == run_id
    assert len(answer.evidence) == 1


@pytest.mark.parametrize("tamper", ["value", "records", "predicate", "audit"])
def test_validator_recomputes_historical_evidence_against_both_snapshots(tmp_path, tamper):
    store, repository, service, agent, query, previous = setup_history(tmp_path)
    answer = service.ask(query)
    bundle = answer.evidence[0]
    item = bundle.items[0]
    if tamper == "value":
        item = item.model_copy(update={"numeric_values": dict(item.numeric_values, contact_time_s_difference=99)})
    elif tamper == "records":
        item = item.model_copy(update={"record_refs": item.record_refs[1:]})
    elif tamper == "predicate":
        item = item.model_copy(update={"predicates": (item.predicates[0].model_copy(update={"supported": False}),)})
    else:
        bundle = bundle.model_copy(update={"tool_runs": (bundle.tool_runs[0].model_copy(update={"output_digest": "forged"}),)})
    bundle = bundle.model_copy(update={"items": (item,)})
    with pytest.raises(ClaimValidationError) as error:
        ClaimValidator().validate(
            DraftAnalysisPackage(summary="", claims=()), repository.get_package(query.session_id),
            (bundle,), query.data_access_scope,
            longitudinal_source=(repository.get_package(previous), answer.question_context.longitudinal),
        )
    assert error.value.code == "historical_evidence_mismatch"


def test_modified_historical_values_invalidate_completed_and_interrupted_results(tmp_path, monkeypatch):
    store, repository, service, agent, query, previous = setup_history(tmp_path)
    completed = service.ask(query)
    synthesize = agent.synthesize_sequential
    monkeypatch.setattr(agent, "synthesize_sequential", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        service.ask(query)
    with store._connect() as conn:
        interrupted = conn.execute("SELECT analysis_run_id FROM report_analyses WHERE status='running'").fetchone()[0]
        payload = json.loads(conn.execute("SELECT report_detail_json FROM test_sessions WHERE id=?", (previous,)).fetchone()[0])
        for record in payload["per_step_results"]:
            record["contact_time_s"] = .1
        conn.execute("UPDATE test_sessions SET report_detail_json=? WHERE id=?", (json.dumps(payload), previous))
    monkeypatch.setattr(agent, "synthesize_sequential", synthesize)
    updated = service.ask(query)
    assert updated.analysis_run_id not in {completed.analysis_run_id, interrupted}
    assert updated.evidence[0].items[0].numeric_values["contact_time_s_previous_mean"] == pytest.approx(.1)
    assert updated.request_digest != completed.request_digest
    assert [row["analysis_run_id"] for row in service.get_history(query.session_id, query.data_access_scope)] == [updated.analysis_run_id]


def test_previous_update_during_synthesis_prevents_publishing(tmp_path, monkeypatch):
    store, repository, service, agent, query, previous = setup_history(tmp_path)

    def delete_previous(*args):
        with store._connect() as conn:
            conn.execute("DELETE FROM test_sessions WHERE id=?", (previous,))
        return DraftAnalysisPackage(summary="", claims=())

    monkeypatch.setattr(agent, "synthesize_sequential", delete_previous)
    with pytest.raises(ReportAnalysisError) as error:
        service.ask(query)
    assert error.value.code == "stale_history"
    assert service.get_history(query.session_id, query.data_access_scope) == []
