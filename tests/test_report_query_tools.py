"""Selected-record analysis preserves scope, chronology and numeric provenance."""

import pytest

from agent.report.tools import AnalysisToolGateway
from reporting.charts import build_evidence_charts
from reporting.models import (
    AnalysisState, DataAccessScope, DraftAnalysisClaim, DraftAnalysisPackage,
    HypothesisTarget, NextAnalysisAction, NumericBinding, PredicateBinding, ReportSelection,
)
from reporting.renderer import AnalysisRenderer
from reporting.validators import ActionValidationError, ActionValidator, ClaimRepairValidator, ClaimValidator, PlanValidationError
from tests.reporting_fixtures import make_jump_package, make_treadmill_package
from tests.test_analysis_kernel import _run


def test_summary_sample_count_can_be_bound_and_repaired_as_numeric_evidence():
    package = make_jump_package([.2, .4])
    bundle = _run(package, "summarize_records", ["contact_time_s"])
    item = bundle.items[0]
    claim = DraftAnalysisClaim(
        claim_id="c1", claim_type="derived", text_template="样本量为{count}。",
        evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
        predicate_bindings=(PredicateBinding(
            predicate="comparison_supported",
            predicate_evidence_ref=item.predicates[0].predicate_evidence_id,
        ),),
        numeric_bindings=(NumericBinding(
            binding_id="count", source_type="evidence",
            source_ref=item.evidence_id, value_key="selected",
        ),),
    )
    draft = DraftAnalysisPackage(summary="", claims=(claim,))
    result = ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())
    assert result.claims[0].numeric_bindings[0].value == 2
    assert result.claims[0].numeric_bindings[0].unit == "count"
    unbound = draft.model_copy(update={"claims": (claim.model_copy(update={
        "text_template": "样本量为2 count。", "numeric_bindings": (),
    }),)})
    ClaimRepairValidator().validate(unbound, draft, "unbound_numeric_literal", package, (bundle,))


def _action(package, method="summarize_records", metrics=("contact_time_s",), **inputs):
    return NextAnalysisAction(
        action_id="a1",
        hypothesis=HypothesisTarget(
            hypothesis_id="h1", statement="查看所选记录", dimensions=("descriptive",),
            metric_codes=metrics, target_predicate="comparison_supported",
            reason="用户追问", success_condition="取得范围统计",
        ),
        tool_name="analyze_current_session", analysis_method=method,
        inputs={"record_set_id": package.record_sets[0].record_set_id, "metric_codes": list(metrics), **inputs},
        purpose="查看选中范围",
    )


def _selection(package, records, metrics=("contact_time_s",)):
    return ReportSelection(
        record_set_id=package.record_sets[0].record_set_id,
        metric_codes=metrics, record_refs=tuple(record.record_id for record in records),
        label="后半记录",
    )


def test_summary_uses_only_selected_records_and_returns_population_std():
    package = make_jump_package([.1] * 6 + [.2, .4])
    refs = [record.record_id for record in package.record_sets[0].records[-2:]]
    bundle = _run(package, "summarize_records", ["contact_time_s"], record_refs=refs)
    item = bundle.items[0]
    assert item.analysis_status == "conclusive"
    assert item.sample_counts == {"selected": 2}
    assert item.numeric_values == pytest.approx({
        "contact_time_s_mean": .3, "contact_time_s_min": .2,
        "contact_time_s_max": .4, "contact_time_s_std": .1,
    })
    assert item.record_groups == {"selected": tuple(refs)}
    chart = build_evidence_charts(package, item, bundle.tool_runs[0])[0]
    assert chart.groups[0].mean == pytest.approx(.3)
    assert [point.record_ref for point in chart.groups[0].points] == refs
    assert chart.grouping == "所选有效记录"


def test_single_record_is_a_valid_summary_and_empty_selection_is_inconclusive():
    package = make_jump_package([.2, .3])
    ref = package.record_sets[0].records[0].record_id
    item = _run(package, "summarize_records", ["contact_time_s"], record_refs=[ref]).items[0]
    assert item.numeric_values["contact_time_s_std"] == 0
    assert item.analysis_status == "conclusive"
    empty = _run(package, "summarize_records", ["contact_time_s"], record_refs=[])
    assert empty.items[0].analysis_status == "inconclusive"
    assert empty.items[0].sample_counts == {"selected": 0}
    assert build_evidence_charts(package, empty.items[0], empty.tool_runs[0]) == ()


def test_two_metric_summary_uses_aligned_available_values():
    from dataclasses import replace
    from config.treadmill_report import summarize
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from tests.reporting_fixtures import make_treadmill_report

    report = make_treadmill_report([.2, .3], [.4, .5], [70, 71], [72, 74])
    rows = list(report.per_step_results)
    rows[2] = replace(rows[2], step_length_cm=None)
    report = replace(report, per_step_results=tuple(rows), metric_summaries={
        **report.metric_summaries, "step_length_cm": summarize((70, 72, 74)),
    })
    package = ReportDataPackageBuilder().build(report, ReportContextInput(session_id=2, test_type="Treadmill Gait Test"))
    bundle = _run(package, "summarize_records", ["contact_time_s", "step_length_cm"])
    item = bundle.items[0]
    assert item.sample_counts == {"selected": 3}
    assert item.numeric_values["contact_time_s_mean"] == pytest.approx((.2 + .4 + .5) / 3)
    assert item.numeric_values["step_length_cm_mean"] == 72
    charts = build_evidence_charts(package, item, bundle.tool_runs[0])
    assert [p.record_ref for p in charts[0].groups[0].points] == [p.record_ref for p in charts[1].groups[0].points]


def test_record_filter_applies_before_temporal_splitting():
    package = make_jump_package([.9] * 6 + [.2] * 3 + [.4] * 3)
    records = package.record_sets[0].records[6:]
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"], record_refs=[record.record_id for record in records])
    item = bundle.items[0]
    assert item.sample_counts == {"first_half": 3, "second_half": 3}
    assert item.numeric_values["difference"] == pytest.approx(.2)
    assert item.record_groups["first_half"] == tuple(record.record_id for record in records[:3])


def test_record_filter_applies_to_side_cochange_and_exclusion_methods():
    package = make_treadmill_package([.9]*3+[.2]*3+[.4]*3, [.8]*3+[.2]*3+[.25]*3,
                                     [90]*3+[72]*3+[66]*3, [90]*3+[72]*3+[66]*3)
    records = package.record_sets[0].records[6:]
    refs = [record.record_id for record in records]
    side = _run(package, "verify_side_segment_difference", ["contact_time_s"], record_refs=refs).items[0]
    assert side.numeric_values["left_change"] == pytest.approx(.2)
    cochange = _run(package, "verify_cross_metric_cochange", ["contact_time_s", "step_length_cm"], record_refs=refs).items[0]
    assert cochange.numeric_values["step_length_cm_difference"] == pytest.approx(-6)
    robustness = _run(package, "verify_exclusion_robustness", ["contact_time_s"], record_refs=refs).items[0]
    assert set(robustness.record_refs) == set(refs)
    assert robustness.numeric_values["included_difference"] == pytest.approx(.125)


@pytest.mark.parametrize("refs,error", [(["unknown"], "record_not_in_record_set"), ([1], "invalid_record_refs"), (None, "invalid_record_refs")])
def test_bad_record_references_are_rejected(refs, error):
    package = make_jump_package([.2] * 6)
    with pytest.raises(PlanValidationError) as exc:
        _run(package, "summarize_records", ["contact_time_s"], record_refs=refs)
    assert exc.value.code == error


def test_duplicate_and_other_record_set_references_are_rejected():
    package = make_jump_package([.2] * 6)
    ref = package.record_sets[0].records[0].record_id
    with pytest.raises(PlanValidationError, match="unique"):
        _run(package, "summarize_records", ["contact_time_s"], record_refs=[ref, ref])
    another = make_treadmill_package([.2] * 6, [.3] * 6).record_sets[0].records[0].record_id
    with pytest.raises(PlanValidationError) as exc:
        _run(package, "summarize_records", ["contact_time_s"], record_refs=[another])
    assert exc.value.code == "record_not_in_record_set"


def test_action_injects_selection_and_normalizes_order_before_hashing():
    package = make_jump_package([.2] * 6 + [.3] * 6)
    selected = _selection(package, package.record_sets[0].records[6:])
    validator = ActionValidator(selection=selected)
    injected = validator.validate_action(_action(package), package, DataAccessScope())
    reordered = validator.validate_action(_action(package, record_refs=list(reversed(selected.record_refs))), package, DataAccessScope())
    assert injected.action.inputs == injected.node.inputs
    assert injected.node.inputs["record_refs"] == list(selected.record_refs)
    assert injected.request_hash == reordered.request_hash
    bundle = AnalysisToolGateway().execute_action(package, injected, DataAccessScope())
    assert bundle.items[0].record_refs == selected.record_refs


def test_selection_rejects_escape_to_other_records_metrics_or_methods():
    package = make_jump_package([.2] * 6 + [.3] * 6)
    selection = _selection(package, package.record_sets[0].records[6:])
    validator = ActionValidator(selection=selection)
    attempts = [
        (_action(package, record_refs=[record.record_id for record in package.record_sets[0].records]), "selection_record_refs_mismatch"),
        (_action(package, metrics=("air_time_s",)), "selection_metric_mismatch"),
        (_action(package, method="quality_scope_check"), "selection_method_mismatch"),
        (_action(package, record_set_id="another"), "selection_record_set_mismatch"),
    ]
    for action, error in attempts:
        with pytest.raises(ActionValidationError) as exc:
            validator.validate_action(action, package, DataAccessScope())
        assert exc.value.code == error


def test_selected_records_and_side_filter_intersect():
    package = make_treadmill_package([.1]*3+[.2]*3, [.8]*3+[.9]*3)
    selection = _selection(package, package.record_sets[0].records[6:])
    validated = ActionValidator(selection=selection).validate_action(_action(package, side="left"), package, DataAccessScope())
    item = AnalysisToolGateway().execute_action(package, validated, DataAccessScope()).items[0]
    assert item.sample_counts["selected"] == 3
    assert item.numeric_values["contact_time_s_mean"] == pytest.approx(.2)


def test_followup_cannot_verify_exclusion_robustness_after_excluded_records_are_removed():
    from reporting.models import ReportQuestionPlan
    from reporting.questions import resolve_question_selection

    package = make_jump_package(
        [5.0] * 6 + [.2] * 6 + [.3] * 6,
        included=[False] * 6 + [True] * 12,
    )
    record_set = package.record_sets[0]
    item = _run(package, "verify_exclusion_robustness", ["contact_time_s"]).items[0]
    assert item.numeric_values["all_difference"] < 0
    assert item.numeric_values["included_difference"] > 0
    assert not next(predicate for predicate in item.predicates
                    if predicate.predicate == "remains_after_exclusion").supported

    selection = resolve_question_selection(package, ReportQuestionPlan(
        record_set_id=record_set.record_set_id, metric_codes=("contact_time_s",),
    ), {})
    assert len(selection.record_refs) == 12
    action = _action(package, method="verify_exclusion_robustness")
    with pytest.raises(ActionValidationError) as error:
        ActionValidator(selection=selection).validate_action(action, package, DataAccessScope())
    assert error.value.code == "selection_method_mismatch"


def test_summary_can_be_a_highlight_with_evidence_derived_wording():
    package = make_jump_package([.2, .4])
    bundle = _run(package, "summarize_records", ["contact_time_s"])
    item = bundle.items[0]
    predicate = item.predicates[0]
    draft = DraftAnalysisPackage(summary="draft", claims=(DraftAnalysisClaim(
        claim_id="c1", claim_type="derived", text_template="用户所选记录。",
        evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
        predicate_bindings=(PredicateBinding(predicate="comparison_supported", predicate_evidence_ref=predicate.predicate_evidence_id),),
    ),))
    validated = ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())
    result = AnalysisRenderer().render(validated, analysis_run_id="query", package=package,
                                      access_scope=DataAccessScope(), state=AnalysisState(),
                                      model_name="test", prompt_version="test", evidence=(bundle,))
    assert result.presentation.headline_claim_ids == ("c1",)
    assert "均值 0.3 s" in result.claims[0].text
    assert "有效样本 2 条" in result.claims[0].text
    assert len(result.presentation.charts) == 1
