"""Presentation regressions using real deterministic evidence and saved schemas."""

import pytest

from reporting.models import (
    AnalysisPackage, AnalysisState, DataAccessScope, DraftAnalysisClaim,
    DraftAnalysisPackage, NumericBinding, PredicateBinding,
)
from reporting.renderer import AnalysisRenderer
from reporting.validators import ClaimValidator
from tests.reporting_fixtures import make_jump_package, make_treadmill_package
from tests.test_analysis_kernel import _run


def render(package, bundles, *, text="后半程触地时间减少，差值为{delta}。", duplicate=False):
    item = bundles[0].items[0]
    predicate = next(p for p in item.predicates if p.predicate == "increase")
    claim = DraftAnalysisClaim(
        claim_id="c1", claim_type="derived", text_template=text,
        evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
        predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=predicate.predicate_evidence_id),),
        numeric_bindings=(NumericBinding(binding_id="delta", source_type="evidence", source_ref=item.evidence_id, value_key="difference"),),
    )
    claims = (claim, claim.model_copy(update={"claim_id": "c2"})) if duplicate else (claim,)
    validated = ClaimValidator().validate(
        DraftAnalysisPackage(summary="无依据的总结", claims=claims), package, bundles, DataAccessScope(),
    )
    return AnalysisRenderer().render(
        validated, analysis_run_id="test-run", package=package,
        access_scope=DataAccessScope(), state=AnalysisState(), model_name="fake",
        prompt_version="test", evidence=bundles,
    )


def test_headline_and_claim_direction_come_from_evidence_not_model_text():
    package = make_jump_package([.2] * 6 + [.3] * 6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    result = render(package, (bundle,))
    assert "增加" in result.summary
    assert "减少" not in result.claims[0].text
    assert "0.1 s" in result.claims[0].text
    assert result.presentation.headline_claim_ids == ("c1",)
    assert result.evidence == (bundle,)


def test_duplicate_findings_share_a_single_highlight_and_chart():
    package = make_jump_package([.2] * 6 + [.3] * 6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    result = render(package, (bundle,), duplicate=True)
    assert len(result.presentation.insight_cards) == 1
    assert len(result.presentation.charts) == 1


def test_groups_use_record_membership_with_missing_values_and_exclusions():
    package = make_jump_package([.2] * 6 + [.3] * 6, included=[True, False] + [True] * 10)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    result = render(package, (bundle,))
    chart = result.presentation.charts[0]
    assert [len(g.points) for g in chart.groups] == [5, 6]
    assert [g.mean for g in chart.groups] == pytest.approx([.2, .3])
    assert {p.record_ref for g in chart.groups for p in g.points} == set(bundle.items[0].record_refs)
    restored = AnalysisPackage.model_validate_json(result.model_dump_json())
    assert restored.presentation == result.presentation


def test_cross_metric_chart_preserves_paired_sample_membership():
    from reporting.charts import build_evidence_charts

    package = make_treadmill_package([.2]*3+[.3]*3, [.2]*3+[.3]*3, [72]*3+[66]*3, [72]*3+[66]*3)
    bundle = _run(package, "verify_cross_metric_cochange", ["contact_time_s", "step_length_cm"])
    charts = build_evidence_charts(package, bundle.items[0], bundle.tool_runs[0])
    assert len(charts) == 2
    assert charts[0].groups[0].mean == pytest.approx(.2)
    assert charts[1].groups[0].mean == pytest.approx(72)
    assert [p.record_ref for p in charts[0].groups[0].points] == [p.record_ref for p in charts[1].groups[0].points]


def test_legacy_analysis_does_not_require_presentation_or_evidence():
    package = make_jump_package([.2] * 6 + [.3] * 6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    saved = render(package, (bundle,)).model_dump(mode="json")
    saved.pop("presentation")
    saved.pop("evidence")
    saved["analysis_schema_version"] = "analysis-schema/4.0"
    restored = AnalysisPackage.model_validate(saved)
    assert restored.presentation is None
    assert restored.evidence == ()


def test_no_claims_produces_no_fabricated_highlights():
    package = make_jump_package([.2] * 4)
    validated = ClaimValidator().validate(DraftAnalysisPackage(summary="表现很好", claims=()), package, (), DataAccessScope())
    result = AnalysisRenderer().render(validated, analysis_run_id="empty", package=package, access_scope=DataAccessScope(), state=AnalysisState(), model_name="fake", prompt_version="test", evidence=())
    assert result.presentation.headline_claim_ids == ()
    assert result.presentation.charts == ()
    assert "表现很好" not in result.summary


def test_uneven_timestamps_keep_count_based_analysis_groups():
    from dataclasses import replace
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from tests.reporting_fixtures import make_jump_report

    source = make_jump_report([.3]*6 + [.6]*3 + [.2]*3)
    times = [0, 1, 2, 3, 4, 5, 6, 7, 8, 100, 101, 102]
    source = replace(source, jump_results=tuple(replace(row, lift_time_s=t, touch_time_s=t+.4) for row, t in zip(source.jump_results, times)))
    package = ReportDataPackageBuilder().build(source, ReportContextInput(session_id=1, test_type="Jump Test"))
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    chart = render(package, (bundle,)).presentation.charts[0]
    assert [len(g.points) for g in chart.groups] == [6, 6]
    assert chart.groups[1].mean - chart.groups[0].mean == pytest.approx(.1)
    assert chart.groups[1].points[-1].timestamp_s >= 102


def test_recommendation_is_displayed_under_its_referenced_finding():
    from reporting.analysis_html import analysis_html

    package = make_jump_package([.2]*6 + [.3]*6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    saved = render(package, (bundle,)).model_dump(mode="json")
    saved["recommendations"] = [{"recommendation_id": "r1", "claim_refs": ["c1"], "text": "复测同一测试。"}]
    saved["presentation"]["insight_cards"][0]["recommendation_ids"] = ["r1"]
    text = analysis_html(saved)
    assert "关联行动建议" in text
    assert text.count("复测同一测试") == 1
    assert "analysis-chart:0" in text


@pytest.mark.parametrize("chart_sources", [None, {}])
def test_followup_html_displays_escaped_question_and_selected_scope(chart_sources):
    from reporting.analysis_html import analysis_html

    analysis = {
        "question_context": {"question": "只看 <左侧> & 后半程", "selection_label": "后半有效记录 · 左侧"},
        "claims": [{"text": "触地时间均值 0.3 s。"}],
    }
    text = analysis_html(analysis, chart_sources=chart_sources)
    assert "本次提问" in text
    assert "只看 &lt;左侧&gt; &amp; 后半程" in text
    assert text.count("后半有效记录 · 左侧") == 1
    assert text.index("分析范围") < text.index("触地时间均值")


@pytest.mark.parametrize("detailed", [False, True])
def test_followup_pdf_content_keeps_question_and_scope(detailed):
    from reporting.pdf import report_html
    from tests.reporting_fixtures import make_jump_report

    text = report_html(
        make_jump_report([.2, .3]), title="纵跳测试", stats=[], reason="手动结束", detailed=detailed,
        analysis={"question_context": {"question": "只看后半程", "selection_label": "后半有效记录"},
                  "claims": [{"text": "触地时间均值 0.3 s。"}]},
    )
    assert "只看后半程" in text
    assert "后半有效记录" in text
    assert "触地时间均值 0.3 s。" in text


def test_default_analysis_html_omits_followup_labels():
    from reporting.analysis_html import analysis_html

    text = analysis_html({"question_context": None, "claims": [{"text": "完整报告发现。"}]})
    assert "本次提问" not in text
    assert "分析范围" not in text
    assert "完整报告发现。" in text


def test_chart_point_locates_exact_record_and_report_switch_clears_charts(qtbot):
    from ui.views.report_view import ReportView
    from tests.reporting_fixtures import make_jump_report

    package = make_jump_package([.2]*6 + [.3]*6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    analysis = render(package, (bundle,))
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(make_jump_report([.2]*6 + [.3]*6), 1)
    view.show_validated_analysis(analysis.model_dump(mode="json"))
    assert len(view._evidence_charts) == 1
    widget = view._evidence_charts[0]
    scatter = next(i for i in widget.plot.items() if hasattr(i, 'sigClicked') and hasattr(i, 'points') and len(i.points()))
    point = scatter.points()[0]
    widget.select_point(scatter, [point])
    row = widget.table.currentRow()
    assert widget.rows[row] == point.data()
    widget.kind.setCurrentIndex(2)
    assert widget.chart == analysis.presentation.charts[0]
    view.load_report(make_jump_report([.4]*6), 2)
    assert view._evidence_charts == []
    assert view._analysis_data is None


def test_saved_result_includes_evidence_after_repository_reload(tmp_path):
    from tests.test_report_analysis_service import _service, _ServiceFakeAgent

    _, session_id, repository, service = _service(tmp_path, _ServiceFakeAgent())
    result = service.analyze(session_id, DataAccessScope())
    cached = repository.get_latest_validated_analysis(session_id, DataAccessScope(), result.package_digest)
    assert AnalysisPackage.model_validate(cached).presentation == result.presentation
    assert cached['evidence'][0]['items'][0]['record_groups']


def test_chart_rejects_swapped_side_groups():
    from reporting.charts import build_evidence_charts

    package = make_treadmill_package([.2]*6+[.32]*6, [.2]*6+[.22]*6)
    bundle = _run(package, "verify_side_segment_difference", ["contact_time_s"])
    item = bundle.items[0]
    groups = dict(item.record_groups)
    groups['left_first'], groups['left_second'] = groups['left_second'], groups['left_first']
    with pytest.raises(ValueError, match='difference'):
        build_evidence_charts(package, item.model_copy(update={'record_groups': groups}), bundle.tool_runs[0])


def test_export_uses_selected_chart_type_without_mutating_saved_analysis(qtbot, monkeypatch, tmp_path):
    from ui.views.report_view import ReportView, QFileDialog, QMessageBox
    import ui.report_pdf
    from tests.reporting_fixtures import make_jump_report

    package = make_jump_package([.2]*6 + [.3]*6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    analysis = render(package, (bundle,)).model_dump(mode='json')
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(make_jump_report([.2]*6 + [.3]*6), 1)
    view.show_validated_analysis(analysis)
    view._evidence_charts[0].kind.setCurrentIndex(2)
    captured = {}
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path/'report.pdf'), ''))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(ui.report_pdf, 'write_report_pdf', lambda path, report, **options: captured.update(options))
    view._on_export_pdf()
    assert captured['analysis']['presentation']['charts'][0]['chart_type'] == 'segment_comparison'
    assert analysis['presentation']['charts'][0]['chart_type'] == 'time_series'


def test_merged_highlight_keeps_recommendations_for_duplicate_claims():
    from reporting.presentation import build_presentation
    from knowledge.models import Recommendation

    package = make_jump_package([.2]*6 + [.3]*6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    result = render(package, (bundle,), duplicate=True)
    recommendation = Recommendation(recommendation_id='r1', category='retest', text='同条件复测。', claim_refs=('c2',), evidence_refs=('literature1',))
    presentation = build_presentation(result.claims, package, (bundle,), (recommendation,))
    assert presentation.insight_cards[0].related_claim_ids == ('c2',)
    assert presentation.insight_cards[0].recommendation_ids == ('r1',)
