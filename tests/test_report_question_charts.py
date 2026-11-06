"""Changing a chart style retains the analysis groups of the selected finding."""

from reporting.models import DraftAnalysisPackage
from tests.test_report_questions import request, setup_question_service


def test_chart_only_question_reproduces_parent_groups(tmp_path, monkeypatch):
    service, repository, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"intent": "chart", "chart_type": "segment_comparison"}
    monkeypatch.setattr(
        agent, "synthesize_sequential",
        lambda *args: DraftAnalysisPackage(summary="", claims=()),
    )
    answer = service.ask(request(original, "只改成分组均值图", selected_claim_id="c1"))

    chart = answer.presentation.charts[0]
    assert chart.chart_type == "segment_comparison"
    assert chart.groups == original.presentation.charts[0].groups
    assert [group.group_id for group in chart.groups] == ["first_half", "second_half"]
    assert answer.evidence[0].items[0].analysis_method == "verify_temporal_change"
    assert answer.question_context.intent == "chart"
    assert answer.analysis_run_id != original.analysis_run_id
    saved = repository.get_validated_analysis(
        answer.analysis_run_id, answer.session_id, answer.data_access_scope,
        answer.package_digest,
    )
    assert saved["presentation"] == answer.presentation.model_dump(mode="json")


def test_chart_question_with_changed_scope_does_not_reuse_full_report_groups(tmp_path):
    service, _, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {
        "intent": "analyze", "chart_type": "segment_comparison",
        "segment": "second_half",
    }
    answer = service.ask(request(original, "画后半程的均值图", selected_claim_id="c1"))
    chart = answer.presentation.charts[0]
    assert [group.group_id for group in chart.groups] == ["selected"]
    assert len(chart.groups[0].points) == 12
    assert answer.evidence[0].items[0].analysis_method == "summarize_records"


def test_chart_only_does_not_reapply_inherited_half_and_side_filters(tmp_path):
    service, _, agent, original = setup_question_service(tmp_path)
    agent.plan_options = {"segment": "second_half", "side": "right"}
    previous = service.ask(request(original, "后半程右侧触地时间"))
    agent.plan_options = {
        "intent": "chart", "chart_type": "segment_comparison",
        "scope_basis": "previous", "segment": "second_half", "side": "right",
    }
    answer = service.ask(request(previous, "只把这张图改成分组均值图"))
    assert answer.question_context.selection == previous.question_context.selection
    assert answer.presentation.charts[0].groups == previous.presentation.charts[0].groups
    assert len(answer.presentation.charts[0].groups[0].points) == 6
