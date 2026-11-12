"""Positive/negative acceptance paths for limitations and merged report actions."""

from dataclasses import replace

import pytest

from agent.report.service import ReportAnalysisService
from config.test_config import default_jump_config
from data.subject_store import SubjectStore
from knowledge.action_matching import UNSUPPORTED_FINDINGS, action_candidates, verified_finding_evidence
from knowledge.integration import build_report_rag_context
from knowledge.models import Citation, RAGResult, ValidatedRecommendationPackage
from knowledge.pipeline import degraded_rag_result
from knowledge.recommendations import build_data_followups
from reporting.analysis_html import analysis_html
from reporting.models import (
    AnalysisNode, AnalysisQuestion, AnalysisState, DataAccessScope, DraftAnalysisClaim, DraftAnalysisPackage,
    QualityFlag, SmallAnalysisPlan,
)
from reporting.renderer import AnalysisRenderer
from reporting.repository import ReportRepository
from reporting.validators import ClaimValidator
from tests.reporting_fixtures import make_jump_package, make_jump_report, make_treadmill_package
from tests.test_analysis_kernel import _run
from tests.test_knowledge_action_quality import StructuredReportAgent, computed_report


def limitation_context(*, quality=False):
    package = make_jump_package([.2]*4 if not quality else [.2]*12)
    if quality:
        package = package.model_copy(update={"quality_flags": (QualityFlag(
            quality_flag_id="qf-1", code="quality_invalidation", severity="error",
            scope="report", source_ref=package.metadata.package_id,
            invalidates_metric_codes=() if quality == "report" else ("contact_time_s",),
            invalidates_report=quality == "report",
        ),)})
    if quality == "report":
        from reporting.validators import PlanValidator
        from agent.report.tools import AnalysisToolGateway
        plan = SmallAnalysisPlan(questions=(AnalysisQuestion(question_id="q1",description="质量检查",
            dimensions=("quality",),metric_codes=(),reason="质量标记",stop_condition="完成检查"),),
            nodes=(AnalysisNode(node_id="n1",question_id="q1",tool_name="analyze_current_session",
                analysis_method="quality_scope_check",inputs={},purpose="质量检查"),))
        checked = PlanValidator().validate(plan,package,DataAccessScope())
        bundle = AnalysisToolGateway().execute_plan(package,checked,DataAccessScope())
    else:
        bundle = _run(package, "verify_temporal_change", ["contact_time_s"])
    fact = next(f for f in package.scalar_facts if f.metric_code == "contact_time_s" and f.statistic == "mean")
    draft = DraftAnalysisPackage(summary="", claims=(DraftAnalysisClaim(
        claim_id="mean", claim_type="descriptive", text_template="触地时间统计。", fact_refs=(fact.fact_id,),
    ),))
    validated = ClaimValidator().validate(draft, package, (bundle,), DataAccessScope())
    return build_report_rag_context(package, validated, (bundle,)), package, validated, bundle


@pytest.mark.parametrize("quality,phrase", [(False,"有效样本不足"),(True,"质量失效记录"),("report","报告质量标记使分析失效")])
def test_trusted_limitation_generates_without_change_predicate(quality, phrase):
    context, package, validated, bundle = limitation_context(quality=quality)
    assert context.claims[0].finding_type == "measurement_limitation"
    assert context.claims[0].evidence[0].analysis_status == ("conclusive" if quality == "report" else "inconclusive")
    assert context.claims[0].evidence[0].predicates == ()
    actions = build_data_followups(context)
    assert len(actions) == 1
    assert actions[0].action_id == "explain_limitation"
    assert phrase in actions[0].text
    assert "变化" not in actions[0].text
    assert actions[0].data_evidence_refs == (bundle.items[0].evidence_id,)
    assert actions[0].citation_refs == ()
    rendered = AnalysisRenderer().render(validated, analysis_run_id="test", package=package,
        access_scope=DataAccessScope(), state=AnalysisState(), model_name="test", prompt_version="test",
        evidence=(bundle,), data_followups=actions)
    assert rendered.recommendations == actions
    assert phrase in analysis_html(rendered.model_dump(mode="json"))


@pytest.mark.parametrize("damage", ["assessment", "digest", "status", "counts", "method", "limitation", "quality_source"])
def test_unbacked_limitation_is_rejected(damage):
    context, _, _, _ = limitation_context(quality=damage == "quality_source")
    claim = context.claims[0]
    item = claim.evidence[0]
    if damage == "quality_source":
        context = context.model_copy(update={"quality_evidence": ()})
    elif damage == "limitation":
        claim = claim.model_copy(update={"limitations": ()})
    else:
        updates = {"assessment": {"limitation_assessments": ()}, "digest": {"package_digest":"other"},
                   "status": {"analysis_status":"unverified"}, "counts": {"sample_counts":{"first_half":99,"second_half":99}},
                   "method": {"analysis_method":"invented_method"}}
        claim = claim.model_copy(update={"evidence":(item.model_copy(update=updates[damage]),)})
    assert build_data_followups(context.model_copy(update={"claims":(claim,)})) == ()


def test_limitations_do_not_echo_unverified_extra_reasons():
    context, _, _, _ = limitation_context()
    claim = context.claims[0].model_copy(update={"limitations": ("insufficient_sample_size", "quality_invalidation")})
    actions = build_data_followups(context.model_copy(update={"claims": (claim,)}))
    assert "有效样本不足" in actions[0].text
    assert "质量失效" not in actions[0].text


def test_side_specific_sample_limitation_keeps_its_side():
    package = make_treadmill_package([.2]*4,[.3]*8)
    bundle = _run(package,"verify_side_segment_difference",["contact_time_s"])
    fact = next(f for f in package.scalar_facts if f.metric_code == "contact_time_s" and f.statistic == "mean")
    validated = ClaimValidator().validate(DraftAnalysisPackage(summary="",claims=(DraftAnalysisClaim(
        claim_id="mean",claim_type="descriptive",text_template="触地时间统计。",fact_refs=(fact.fact_id,),
    ),)),package,(bundle,),DataAccessScope())
    context = build_report_rag_context(package,validated,(bundle,))
    action = build_data_followups(context)[0]
    assert "左侧有效样本不足" in action.text
    assert "右侧有效样本不足" not in action.text


def test_limitation_is_reachable_from_normal_report_service(tmp_path):
    class DescriptiveAgent(StructuredReportAgent):
        def synthesize(self, observation, state, evidence):
            fact = next(f for f in observation.authoritative_facts
                        if f.metric_code == "contact_time_s" and f.statistic == "mean")
            return DraftAnalysisPackage(summary="", claims=(DraftAnalysisClaim(
                claim_id="mean", claim_type="descriptive", text_template="本次触地时间统计。", fact_refs=(fact.fact_id,),
            ),))

    store = SubjectStore(tmp_path / "limited.sqlite3")
    report = make_jump_report([.2, .3, .2, .3])
    session = store.record_session(None, replace(default_jump_config(), number_of_jumps=4), report)
    result = ReportAnalysisService(ReportRepository(store), agent=DescriptiveAgent(
        "contact_time_s", "verify_temporal_change")).analyze(session, DataAccessScope())
    assert result.recommendations[0].action_id == "explain_limitation"
    assert result.recommendations[0].data_evidence_refs == (result.evidence[0].items[0].evidence_id,)


@pytest.mark.parametrize("kind", ["side_difference", "variability"])
def test_unimplemented_findings_are_explicitly_unavailable(kind):
    context, _, _, _ = limitation_context()
    claim = context.claims[0].model_copy(update={"finding_type": kind})
    assert kind in UNSUPPORTED_FINDINGS
    assert action_candidates(context, claim) == ()
    assert verified_finding_evidence(context, claim, "contact_time_s") == ()


def render_mixed(tmp_path, data_actions, literature_actions, *, references=()):
    context, answer, repository, _ = computed_report(tmp_path, "run")
    package = repository.get_package(answer.session_id)
    original = answer.claims[0]
    ids = list(dict.fromkeys(ref for r in (*data_actions, *literature_actions) for ref in r.claim_refs))
    validated = ClaimValidator().validate(DraftAnalysisPackage(summary="", claims=tuple(DraftAnalysisClaim(
        claim_id=ref, claim_type="derived", text_template="步频变化。", evidence_refs=original.evidence_refs,
        tool_run_ids=original.tool_run_ids, predicate_bindings=original.predicate_bindings,
    ) for ref in ids)), package, answer.evidence, DataAccessScope())
    rag = RAGResult(package=ValidatedRecommendationPackage(recommendations=tuple(literature_actions), citations=references),
                    audit=degraded_rag_result(package.metadata.package_digest,"fixture").audit)
    return AnalysisRenderer().render(validated, analysis_run_id="mixed", package=package,
        access_scope=DataAccessScope(), state=AnalysisState(), model_name="test", prompt_version="test",
        evidence=answer.evidence, data_followups=data_actions, rag_result=rag)


def test_global_arbitration_prefers_direct_support_and_caps_total_at_three(tmp_path):
    from knowledge.models import Recommendation
    def action(index, basis):
        return Recommendation(recommendation_id=f"{basis}-{index}", category="retest", text=f"行动{index}",
            claim_refs=(f"claim-{index}",), evidence_refs=(f"lit-{index}",) if basis == "literature" else (),
            metric_code="cadence_steps_per_s", action_id="check_repeatability" if basis == "literature" else "track_change",
            basis=basis, citation_refs=(f"cite-{index}",) if basis == "literature" else (),
            evidence_matches=({"applicability":"reviewed_direct_action_support"},) if basis == "literature" else (),
            data_evidence_refs=("data",))
    data = tuple(action(i,"data") for i in range(4))
    literature = tuple(action(i,"literature") for i in (0,1)) + (action(0,"literature"),)
    cites = tuple(Citation(citation_id=f"cite-{i}", evidence_id=f"lit-{i}", source_id="source", document_id="doc",
                          chunk_id=f"chunk-{i}", title="Test reviewed source", url="https://example.org/paper") for i in (0,1,9))
    result = render_mixed(tmp_path,data,literature,references=cites)
    assert len(result.recommendations) == 3
    assert {item.recommendation_id for item in result.recommendations} == {"literature-0","literature-1","data-2"}
    keys = [(ref,item.metric_code) for item in result.recommendations for ref in item.claim_refs]
    assert len(keys) == len(set(keys))
    assert {cite.citation_id for cite in result.references} == {"cite-0","cite-1"}
    assert "chunk-9" not in result.references_markdown


def test_limitation_priority_wins_and_unreviewed_literature_does_not_displace_data(tmp_path):
    from knowledge.models import Recommendation
    data = Recommendation(recommendation_id="data",category="measurement_review",text="存在具体限制。",
        claim_refs=("claim",), evidence_refs=(),metric_code="cadence_steps_per_s",action_id="explain_limitation",
        basis="data",data_evidence_refs=("assessment",))
    literature = data.model_copy(update={"recommendation_id":"lit","basis":"literature","action_id":"check_repeatability",
        "evidence_refs":("lit",),"citation_refs":("cite",),"evidence_matches":({"applicability":"reviewed_direct_action_support"},)})
    result = render_mixed(tmp_path,(data,),(literature,))
    assert result.recommendations == (data,)
    normal = data.model_copy(update={"action_id":"track_change"})
    unreviewed = literature.model_copy(update={"evidence_matches":()})
    result = render_mixed(tmp_path,(normal,),(unreviewed,))
    assert result.recommendations == (normal,)


def test_service_merges_real_validated_data_and_reviewed_literature_actions(tmp_path):
    from knowledge.recommendations import (RecommendationAction, RecommendationActions,
        RecommendationValidator, render_recommendation_actions)
    from tests.knowledge_fixtures import reviewed_support
    from tests.test_knowledge_action_quality import literature
    from tests.test_knowledge_recommendations import _source

    class ReviewedPipeline:
        def run(self, context):
            metric = "cadence_steps_per_s"
            quote = "Repeat the step rate test under the same treadmill conditions to assess test-retest consistency."
            metadata = reviewed_support(metric, quote, "treadmill_run")
            metadata["reviewed_action_support"][0]["action_id"] = "check_repeatability"
            ev = literature(quote, metadata=metadata)
            draft = render_recommendation_actions(RecommendationActions(recommendations=(RecommendationAction(
                action_id="check_repeatability",claim_id="claim",metric_code=metric,evidence_refs=(ev.evidence_id,),
            ),)),context,(ev,))
            source = _source().model_copy(update={"domains":("run",),"metric_codes":(metric,)})
            validated, _ = RecommendationValidator((source,)).validate(draft,context,(ev,))
            assert len(validated.recommendations) == 1
            return RAGResult(evidence=(ev,),package=validated,
                audit=degraded_rag_result(context.package_digest,"fixture").audit.model_copy(update={"status":"ok","error_code":None}))

    context, answer, repository, _ = computed_report(tmp_path,"run",rag_pipeline=ReviewedPipeline())
    assert len(answer.recommendations) == 1
    assert answer.recommendations[0].basis == "literature"
    assert answer.recommendations[0].action_id == "check_repeatability"
    assert answer.recommendations[0].citation_refs == tuple(ref.citation_id for ref in answer.references)
    saved = repository.get_validated_analysis(answer.analysis_run_id,answer.session_id,DataAccessScope(),answer.package_digest)
    assert len(saved["recommendations"]) == 1
