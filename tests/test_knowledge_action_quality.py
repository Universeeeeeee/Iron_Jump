"""Finding-aware actions, direct paragraph support and trusted numeric rendering."""

from copy import deepcopy
import json

import numpy as np
import pytest

from knowledge.action_matching import action_candidates, evidence_action_match
from knowledge.integration import build_report_rag_context
from knowledge.live_benchmark import benchmark_contexts
from knowledge.models import (
    KnowledgeChunk,
    LiteratureEvidence, RecommendationClaim, ReportRAGContext,
)
from knowledge.planner import QueryPlanner
from knowledge.recommendations import (
    RecommendationAction, RecommendationActions, RecommendationValidator,
    render_recommendation_actions,
)
from knowledge.retrieval import HybridRetriever
from tests.reporting_fixtures import make_jump_package, make_treadmill_package
from tests.test_analysis_kernel import _run
from tests.test_knowledge_recommendations import _source
from reporting.models import DataAccessScope, DraftAnalysisClaim, DraftAnalysisPackage, PredicateBinding
from reporting.validators import ClaimValidator


def context(kind="temporal_change", metric="contact_time_s", test_type="Treadmill Running Test", **changes):
    claim = RecommendationClaim(claim_id="claim", text="已验证发现", metric_codes=(metric,),
                                finding_type=kind, **changes)
    return ReportRAGContext(package_digest="a"*64, test_type=test_type, metric_codes=(metric,), claims=(claim,))


def evidence(text="Contact time was measured during repeated trials.", metric="contact_time_s", **changes):
    values = dict(evidence_id="e1", query_id="q1", chunk_id="chunk", document_id="s1", source_id="s1",
                  domain="run", metric_codes=(metric,), populations=("general",), support_types=("method",),
                  recommendation_allowed=True, locator="Results ¶1", excerpt=text, content_digest="b"*64,
                  score=.03, metadata={"protocol":"treadmill_run"})
    values.update(changes)
    return LiteratureEvidence(**values)


def render(ctx, ev, action_id):
    selection = RecommendationActions(recommendations=(RecommendationAction(
        action_id=action_id, claim_id=ctx.claims[0].claim_id, metric_code=ctx.metric_codes[0],
        evidence_refs=(ev.evidence_id,),
    ),))
    return render_recommendation_actions(selection, ctx, (ev,))


@pytest.mark.parametrize("kind,expected,excluded", [
    ("temporal_change", {"compare_segments", "track_change"}, {"check_conditions", "compare_sides"}),
    ("side_difference", {"compare_sides", "retest_sides"}, {"check_conditions", "compare_segments"}),
    ("variability", {"check_repeatability"}, {"track_change", "check_conditions"}),
    ("verified_change", {"track_change"}, {"check_conditions"}),
    ("measurement_limitation", set(), {"check_conditions", "explain_limitation"}),
])
def test_actions_require_the_actual_finding_and_prerequisites(kind, expected, excluded):
    ctx = context(kind)
    assert set(action_candidates(ctx, ctx.claims[0])) == expected
    assert not expected.intersection(excluded)


def test_specific_limitation_is_named_and_unavailable_detail_is_not_invented():
    ctx = context("measurement_limitation", limitations=("insufficient_sample_size",))
    draft = render(ctx, evidence(), "explain_limitation")
    assert "有效样本不足" in draft.recommendations[0].text
    assert "不足以支持对应分组比较" in draft.recommendations[0].text
    assert render(context("measurement_limitation"), evidence(), "explain_limitation").recommendations == ()


def test_running_cadence_rejects_contact_only_paragraph_despite_paper_tags():
    ctx = context("verified_change", "cadence_steps_per_min")
    bad = evidence("Contact time was overestimated because thick heel soles crossed the optical beam before the force threshold.", "cadence_steps_per_min")
    good = evidence("Step rate demonstrated excellent agreement between OptoGait and the instrumented treadmill.", "cadence_steps_per_min")
    assert evidence_action_match(ctx, ctx.claims[0], ctx.metric_codes[0], "track_change", bad) is None
    match = evidence_action_match(ctx, ctx.claims[0], ctx.metric_codes[0], "track_change", good)
    assert match["excerpt"] == good.excerpt
    assert "本次发现的成立依据来自测试证据" in match["reason"]
    assert render(ctx, bad, "track_change").recommendations == ()


@pytest.mark.parametrize("changes", [
    {"metadata":{"protocol":"overground_walk"}}, {"populations":("clinical",)},
    {"recommendation_allowed":False}, {"excerpt":"The purpose was to assess step rate agreement."},
    {"excerpt":"Increasing step rate reduced pain in patients with knee injury."},
])
def test_paper_protocol_population_and_objective_do_not_supply_applicable_action(changes):
    ctx = context("verified_change", "cadence_steps_per_min")
    ev = evidence("Step rate demonstrated excellent agreement.", "cadence_steps_per_min", **changes)
    assert render(ctx, ev, "track_change").recommendations == ()


def test_left_right_recording_transfer_is_explicit_and_cannot_transfer_thresholds():
    ctx = context("side_difference", "step_length_cm", "Treadmill Gait Test")
    ev = evidence("Left and right step length were measured separately in repeated trials.", "step_length_cm",
                  domain="walk", metadata={"protocol":"overground_walk"})
    draft = render(ctx, ev, "compare_sides")
    assert "左右侧步长" in draft.recommendations[0].text
    assert "对称性指标" not in draft.recommendations[0].text
    assert "不迁移地面步行的阈值" in draft.recommendations[0].evidence_matches[0]["reason"]
    assert render(ctx, ev, "retest_sides").recommendations == ()


def test_original_thirty_scenarios_have_types_and_no_fabricated_values():
    cases = dict(benchmark_contexts())
    assert len(cases) == 30
    assert cases["jump-jump_height_m-05"].claims[0].finding_type == "temporal_change"
    assert cases["walk-step_length_cm-05"].claims[0].finding_type == "side_difference"
    assert cases["run-cadence_steps_per_min-04"].claims[0].finding_type == "verified_change"
    for ctx in cases.values():
        assert ctx.claims[0].data_origin == "synthetic_text_only"
        assert ctx.claims[0].evidence == () and ctx.claims[0].fact_values == ()


def test_actual_treadmill_cadence_code_can_use_step_rate_literature_without_unit_conversion():
    ctx = context("verified_change", "cadence_steps_per_s")
    ev = evidence("Step rate demonstrated excellent agreement during treadmill running.", "cadence_steps_per_min")
    assert QueryPlanner().plan(ctx)
    draft = render(ctx, ev, "track_change")
    assert len(draft.recommendations) == 1
    assert draft.recommendations[0].metric_code == "cadence_steps_per_s"
    assert "60" not in draft.recommendations[0].text


def test_same_metric_different_findings_keep_distinct_evidence_requirements():
    ctx = context("temporal_change", "jump_height_m", "Jump Test")
    ctx = ctx.model_copy(update={"claims": (ctx.claims[0], ctx.claims[0].model_copy(update={
        "claim_id":"variability", "finding_type":"variability",
    }))})
    queries = QueryPlanner().plan(ctx)
    assert len(queries) == 3
    assert len({query.query_id for query in queries}) == 3
    assert any(query.metadata['action_support'] == ('repeatability',) for query in queries)


def test_upstream_evidence_survives_adapter_and_numeric_recommendation_is_revalidated():
    package = make_jump_package([.2]*6 + [.3]*6)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    item = bundle.items[0]
    predicate = next(p for p in item.predicates if p.predicate == "increase")
    validated = ClaimValidator().validate(DraftAnalysisPackage(summary="", claims=(DraftAnalysisClaim(
        claim_id="claim", claim_type="derived", text_template="触地时间发生变化。",
        evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
        predicate_bindings=(PredicateBinding(predicate="increase", predicate_evidence_ref=predicate.predicate_evidence_id),),
    ),)), package, (bundle,), DataAccessScope())
    before = deepcopy(bundle.model_dump())
    ctx = build_report_rag_context(package, validated, (bundle,))
    claim = ctx.claims[0]
    assert claim.finding_type == "temporal_change"
    assert claim.evidence[0].numeric_values == item.numeric_values
    assert claim.evidence[0].sample_counts == {"first_half":6, "second_half":6}
    assert claim.evidence[0].record_groups == item.record_groups
    ev = evidence(domain="jump", metadata={"protocol":"vertical_jump"})
    draft = render(ctx, ev, "compare_segments")
    assert "前半均值 0.2 s" in draft.recommendations[0].text
    assert "后半均值 0.3 s" in draft.recommendations[0].text
    assert "后减前 0.1 s" in draft.recommendations[0].text
    assert bundle.model_dump() == before
    validator = RecommendationValidator((_source().model_copy(update={"metric_codes":("contact_time_s",)}),))
    result, audit = validator.validate(draft, ctx, (ev,))
    assert len(result.recommendations) == 1
    forged = draft.model_copy(update={"recommendations":(draft.recommendations[0].model_copy(update={"text":draft.recommendations[0].text.replace("0.1 s", "9 s")}),)})
    assert validator.validate(forged, ctx, (ev,))[0].recommendations == ()


def test_supported_comparison_without_direction_is_not_labeled_a_change():
    package = make_jump_package([.2]*12)
    bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    item = bundle.items[0]
    predicate = next(p for p in item.predicates if p.predicate == "comparison_supported")
    draft = DraftAnalysisPackage(summary="",claims=(DraftAnalysisClaim(
        claim_id="claim",claim_type="derived",text_template="分组比较完成。",evidence_refs=(item.evidence_id,),
        tool_run_ids=(item.tool_run_id,),predicate_bindings=(PredicateBinding(predicate=predicate.predicate,
        predicate_evidence_ref=predicate.predicate_evidence_id),),
    ),))
    validated = ClaimValidator().validate(draft,package,(bundle,),DataAccessScope())
    ctx = build_report_rag_context(package,validated,(bundle,))
    assert ctx.claims[0].finding_type == "descriptive"
    assert action_candidates(ctx,ctx.claims[0]) == ()


def test_priority_selects_one_action_for_one_finding_metric():
    ctx, ev = context(), evidence()
    actions = RecommendationActions(recommendations=tuple(RecommendationAction(
        action_id=action, claim_id="claim", metric_code="contact_time_s", evidence_refs=("e1",),
    ) for action in ("track_change", "compare_segments")))
    assert [r.action_id for r in render_recommendation_actions(actions, ctx, (ev,)).recommendations] == ["compare_segments"]


def test_invalid_evidence_id_and_ordinary_change_condition_fallback_are_rejected():
    ctx, ev = context(), evidence()
    assert render(ctx, ev, "check_conditions").recommendations == ()
    action = RecommendationAction(action_id="track_change", claim_id="claim", metric_code="contact_time_s", evidence_refs=("invented",))
    assert render_recommendation_actions(RecommendationActions(recommendations=(action,)), ctx, (ev,)).recommendations == ()


def test_paper_protocol_cannot_hide_a_walking_only_sentence_for_running():
    ctx = context("verified_change", "cadence_steps_per_min")
    ev = evidence("Step rate demonstrated excellent agreement during overground walking.", "cadence_steps_per_min")
    assert render(ctx, ev, "track_change").recommendations == ()


def test_ranking_keeps_direct_results_ahead_of_contact_and_shoe_paragraphs():
    ctx = context("verified_change", "cadence_steps_per_min")
    spec = QueryPlanner().plan(ctx)[0]
    source = _source().model_copy(update={"source_id":"s1","domains":("run",),
        "metric_codes":("cadence_steps_per_min",),"metadata":{"protocol":"treadmill_run"}})
    rows = []
    for key, section, text, vector in (
        ("contact", "Discussion", "Contact time was measured using a force threshold and thick heel soles.", [1.,0.]),
        ("method", "Methods", "Step rate was calculated using cycle duration.", [1.,0.]),
        ("result", "Results", "Step rate demonstrated excellent agreement between devices during running.", [0.,1.]),
    ):
        chunk = KnowledgeChunk(chunk_id=key,source_id="s1",document_id="s1",domain="run",section=section,locator=section,
                               text=text, content_digest="c"*64,token_count=20,
                               metric_codes=("cadence_steps_per_min",),recommendation_allowed=True,
                               metadata={"protocol":"treadmill_run"})
        rows.append((chunk, source, np.array(vector)))

    class Store:
        def load_all(self, **kwargs):
            return rows

        def lexical_search(self, *args, **kwargs):
            return rows

    class Embedder:
        def embed_query(self, query):
            return np.array([1.,0.])

    found = HybridRetriever(Store(), Embedder()).retrieve(spec)
    assert found[0].chunk_id == "result"
    assert "contact" not in {item.chunk_id for item in found}


def test_actual_side_change_values_are_preserved_without_inventing_absolute_asymmetry():
    package = make_treadmill_package([.2]*6+[.4]*6,[.2]*6+[.25]*6)
    bundle = _run(package, "verify_side_segment_difference", ["contact_time_s"])
    item = bundle.items[0]
    predicate = next(p for p in item.predicates if p.predicate == "concentrated_on_side")
    validated = ClaimValidator().validate(DraftAnalysisPackage(summary="",claims=(DraftAnalysisClaim(
        claim_id="claim",claim_type="derived",text_template="左右变化不同。",evidence_refs=(item.evidence_id,),
        tool_run_ids=(item.tool_run_id,),predicate_bindings=(PredicateBinding(predicate=predicate.predicate,
        predicate_evidence_ref=predicate.predicate_evidence_id),),
    ),)),package,(bundle,),DataAccessScope())
    ctx = build_report_rag_context(package, validated, (bundle,))
    ev = evidence("Left and right contact time were measured separately.",domain="walk",metadata={"protocol":"treadmill_walk"})
    draft = render(ctx,ev,"compare_sides")
    assert "左侧后减前 0.2 s" in draft.recommendations[0].text
    assert "右侧后减前 0.05 s" in draft.recommendations[0].text
    assert "不对称率" not in draft.recommendations[0].text
    assert ctx.claims[0].evidence[0].sample_counts == item.sample_counts


def test_stability_requires_repeatability_evidence_and_does_not_invent_a_standard_deviation():
    ctx = context("variability", "jump_height_m", "Jump Test", data_origin="synthetic_text_only")
    ev = evidence("Jump height test-retest reliability was excellent.","jump_height_m",domain="jump",metadata={"protocol":"vertical_jump"})
    draft = render(ctx,ev,"check_repeatability")
    assert "离散程度" in draft.recommendations[0].text
    assert "已计算" not in draft.recommendations[0].text
    assert not any(char.isdigit() for char in draft.recommendations[0].text)


def test_review_separates_execution_from_quality_and_marks_text_only_input(tmp_path):
    from knowledge.review import replay_review
    ctx = context("verified_change", "cadence_steps_per_min", data_origin="synthetic_text_only")
    bad = evidence("Contact time was measured using force thresholds.", "cadence_steps_per_min")
    row = {
        "case_id":"run-cadence_steps_per_min-04", "test_type":ctx.test_type,
        "claim":ctx.claims[0].model_dump(mode="json"), "context":ctx.model_dump(mode="json"),
        "evidence":[bad.model_dump(mode="json")], "audit":{"status":"ok"}, "citations":[],
        "recommendations":[{"claim_refs":["claim"],"evidence_refs":["e1"],"action_id":"track_change",
                            "metric_code":"cadence_steps_per_min", "text":"不存在的事实 99 秒"}],
        "groundedness_review":"pending",
    }
    source = tmp_path / "review.json"
    source.write_text(json.dumps({"review_status":"pending","rows":[row]}))
    output = tmp_path / "after.json"
    result = replay_review(source, output)
    checks = result['rows'][0]['quality_checks']
    assert checks['execution_passed']
    assert checks['citation_match_passed'] is False
    assert checks['data_traceability_passed'] is False
    assert checks['status'] == 'failed'
    assert result['review_status'] == 'pending'
    html = output.with_suffix('.html').read_text()
    assert '无实际测试数值' in html
    assert 'finding_type' in html and 'pending' in html


def test_report_service_passes_structured_findings_to_the_existing_rag_pipeline(tmp_path):
    from tests.test_report_analysis_service import _service, _ServiceFakeAgent
    from knowledge.pipeline import degraded_rag_result

    class InspectPipeline:
        def run(self, ctx):
            claim = ctx.claims[0]
            assert claim.finding_type == 'temporal_change'
            assert claim.data_origin == 'validated_report'
            assert claim.evidence[0].numeric_values['difference'] == pytest.approx(.1)
            assert claim.evidence[0].sample_counts == {'first_half':6,'second_half':6}
            assert claim.evidence[0].predicates[0]['supported']
            assert ctx.test_conditions['test_type'] == 'Jump Test'
            return degraded_rag_result(ctx.package_digest, 'fixture')

    store, session, repository, service = _service(tmp_path, _ServiceFakeAgent(), rag_pipeline=InspectPipeline())
    answer = service.analyze(session, DataAccessScope())
    assert answer.rag_audit.error_code == 'fixture'
