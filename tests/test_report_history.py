"""Saved answers remain snapshot-bound and support branching after restoration."""

import pytest

from agent.report.service import ReportAnalysisError
from reporting.models import AnalysisPackage, DataAccessScope
from tests.test_report_questions import request, setup_question_service


def test_history_restores_exact_answer_and_branches_from_selected_parent(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"segment": "second_half"}
    half = service.ask(request(original, "只看后半程"))
    agent.plan_options = {"side": "left"}
    left = service.ask(request(half, "其中左侧呢"))
    history = service.get_history(original.session_id, DataAccessScope())
    assert [item["analysis_run_id"] for item in history] == [
        left.analysis_run_id, half.analysis_run_id, original.analysis_run_id,
    ]
    assert history[0]["parent_analysis_run_id"] == half.analysis_run_id
    assert history[1]["question"] == "只看后半程"
    assert "evidence" not in history[0]
    restored = AnalysisPackage.model_validate(service.get_saved(
        half.session_id, DataAccessScope(), half.analysis_run_id,
    ))
    assert restored == half
    agent.plan_options = {"side": "right"}
    right = service.ask(request(restored, "其中右侧呢"))
    assert right.question_context.parent_analysis_run_id == half.analysis_run_id
    assert right.evidence[0].items[0].numeric_values["contact_time_s_mean"] == pytest.approx(.5)
    assert repository.list_validated_analyses(half.session_id, DataAccessScope(), "old-snapshot") == []
    assert repository.list_validated_analyses(half.session_id + 1, DataAccessScope(), half.package_digest) == []
    assert service.get_history(half.session_id, DataAccessScope(longitudinal=True)) == []


def test_history_omits_unfinished_and_failed_runs_and_rejects_scope_mismatch(tmp_path):
    service, repository, agent, original = setup_question_service(tmp_path)
    for status in ("running", "failed", "rejected"):
        run_id = repository.create_analysis_run(
            original.session_id, DataAccessScope(), original.package_digest,
            model_name="test", prompt_version="test", request_digest="question",
        )
        if status != "running":
            repository.finalize_analysis_run(run_id, status, None)
        with pytest.raises(ReportAnalysisError, match="不匹配"):
            service.get_saved(original.session_id, DataAccessScope(), run_id)
    assert len(service.get_history(original.session_id, DataAccessScope())) == 1
    with pytest.raises(ReportAnalysisError):
        service.get_saved(original.session_id, DataAccessScope(longitudinal=True), original.analysis_run_id)
