"""Separate session-backed follow-ups from directly supported literature actions."""

from copy import deepcopy
from dataclasses import replace
import pytest

from agent.report.service import ReportAnalysisService
from config.test_config import default_jump_config
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from config.treadmill_report import TreadmillRunningReport
from data.subject_store import SubjectStore
from knowledge.action_matching import evidence_action_match, verified_finding_evidence
from knowledge.integration import build_report_rag_context
from knowledge.live_benchmark import benchmark_contexts
from knowledge.models import DraftRecommendationPackage, LiteratureEvidence, RecommendationClaim, ReportRAGContext
from knowledge.recommendations import (
    RecommendationAction, RecommendationActions, RecommendationValidator,
    build_data_followups, render_recommendation_actions,
)
from reporting.analysis_html import analysis_html
from reporting.models import (AnalysisNode, AnalysisQuestion, DataAccessScope, DraftAnalysisClaim,
    DraftAnalysisPackage, InvestigationDecision, PredicateBinding, SmallAnalysisPlan, EvidenceReviewDecision)
from reporting.repository import ReportRepository
from reporting.validators import ClaimValidator
from tests.knowledge_fixtures import verified_context, reviewed_support
from tests.reporting_fixtures import make_jump_report, make_treadmill_report
from tests.test_knowledge_recommendations import _source


class StructuredReportAgent:
    model_name = "scripted-finding-agent"
    prompt_version = "structured-followup-test/1"

    def __init__(self, metric, method):
        self.metric, self.method = metric, method
        self.draft = None

    def propose_plan(self, observation, state):
        return InvestigationDecision(rationale="验证固定合成记录的变化", plan=SmallAnalysisPlan(
            questions=(AnalysisQuestion(question_id="q1", description="验证变化", dimensions=("temporal",),
                metric_codes=(self.metric,), reason="合成验收", stop_condition="证据完成"),),
            nodes=(AnalysisNode(node_id="n1", tool_name="analyze_current_session", analysis_method=self.method,
                inputs={"record_set_id": observation.report_manifest.record_sets[0].record_set_id,
                        "metric_codes": [self.metric]}, question_id="q1", purpose="验证"),),
        ))

    def review_evidence(self, *args):
        return EvidenceReviewDecision(evidence_sufficient=True, rationale="证据完成")

    def synthesize(self, observation, state, evidence):
        item = evidence[0].items[0]
        name = "concentrated_on_side" if self.method == "verify_side_segment_difference" else "increase"
        predicate = next(p for p in item.predicates if p.predicate == name)
        self.draft = DraftAnalysisPackage(summary="", claims=(DraftAnalysisClaim(
            claim_id="claim", claim_type="derived", text_template="比较完成。",
            evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
            predicate_bindings=(PredicateBinding(predicate=name, predicate_evidence_ref=predicate.predicate_evidence_id),),
        ),))
        return self.draft


def structured_report_case(mode):
    if mode == "jump":
        report = make_jump_report([.2]*12)
        report = replace(report, jump_results=tuple(replace(r, jump_height_m=.2 if i<6 else .3)
            for i,r in enumerate(report.jump_results)), avg_jump_height=.25, max_jump_height=.3)
        config = replace(default_jump_config(), number_of_jumps=len(report.jump_results))
        metric, method = "jump_height_m", "verify_temporal_change"
    elif mode == "walk":
        report = make_treadmill_report([.2]*12,[.2]*12,[70]*6+[80]*6,[70]*6+[72]*6)
        config = TreadmillGaitConfig(stop_type="End of Time", test_length="01:00")
        metric, method = "step_length_cm", "verify_side_segment_difference"
    else:
        base = make_treadmill_report([.2]*12,[.2]*12)
        report = TreadmillRunningReport(**{k:getattr(base,k) for k,f in base.__dataclass_fields__.items() if f.init})
        report = replace(report, per_step_results=tuple(replace(r,cadence_steps_per_s=2.7 if i<12 else 3.)
            for i,r in enumerate(report.per_step_results)))
        config = TreadmillRunningConfig(stop_type="End of Time", test_length="01:00")
        metric, method = "cadence_steps_per_s", "verify_temporal_change"
    return report, config, metric, method


def computed_report(tmp_path, mode, rag_pipeline=None):
    store = SubjectStore(tmp_path / f"{mode}.sqlite3")
    report, config, metric, method = structured_report_case(mode)
    session = store.record_session(None, config, report)
    repository = ReportRepository(store)
    agent = StructuredReportAgent(metric, method)
    package = repository.get_package(session)
    before = package.model_dump()
    # Exercise the ordinary report service with literature disabled.
    answer = ReportAnalysisService(repository, agent=agent, rag_pipeline=rag_pipeline).analyze(session, DataAccessScope())
    validated = ClaimValidator().validate(agent.draft, package, answer.evidence, DataAccessScope())
    context = build_report_rag_context(package, validated, answer.evidence)
    assert repository.get_package(session).model_dump() == before
    if mode == "jump":
        assert package.context.config_snapshot["number_of_jumps"] == len(report.jump_results) == 12
    return context, answer, repository, report


def literature(text, metric="cadence_steps_per_s", metadata=None):
    return LiteratureEvidence(evidence_id="lit1", query_id="q1", chunk_id="chunk1", document_id="s1", source_id="s1",
        domain="run", metric_codes=(metric,), populations=("general",), support_types=("method",),
        recommendation_allowed=True, locator="Results ¶1", excerpt=text, content_digest="b"*64, score=.03,
        metadata=metadata or {"protocol":"treadmill_run"})


@pytest.mark.parametrize("mode,expected", [
    ("jump", ("前半均值 0.2 m", "后半均值 0.3 m", "后减前 0.1 m")),
    ("walk", ("左侧后减前 10 cm", "右侧后减前 2 cm", "两侧变化幅度的差别")),
    ("run", ("前半均值 2.7 steps/s", "后半均值 3 steps/s", "后减前 0.3 steps/s")),
])
def test_three_modes_run_through_service_storage_and_data_followup_without_literature(tmp_path, mode, expected):
    context, answer, repository, report = computed_report(tmp_path, mode)
    assert len(answer.recommendations) == 1
    action = answer.recommendations[0]
    assert action.basis == "data"
    assert action.evidence_refs == action.citation_refs == ()
    assert action.data_evidence_refs == answer.claims[0].evidence_refs
    assert all(text in action.text for text in expected)
    assert "后续同协议测试" in action.text
    assert "复核" not in action.text
    assert answer.references == ()
    assert answer.rag_audit is None
    html = analysis_html(answer.model_dump(mode="json"))
    assert "后续观察" in html and "文献建议</b>" not in html
    assert repository.get_validated_analysis(answer.analysis_run_id, answer.session_id,
        DataAccessScope(), answer.package_digest)["recommendations"][0]["basis"] == "data"
    if mode == "walk":
        assert context.claims[0].finding_type == "side_temporal_change"
        assert action.action_id == "track_side_changes"
        assert "不对称" not in action.text and "水平差异" not in action.text


@pytest.mark.parametrize("text", [
    "Step rate demonstrated excellent agreement between OptoGait and the instrumented treadmill (ICC 0.99).",
    "Contact time was overestimated by OptoGait compared with a force treadmill.",
    "Flight time was measured to estimate jump height, with systematic measurement error.",
])
def test_agreement_or_metric_relatedness_cannot_authorize_segment_action(tmp_path, text):
    context, answer, _, _ = computed_report(tmp_path, "run")
    ev = literature(text)
    assert evidence_action_match(context, context.claims[0], "cadence_steps_per_s", "track_change", ev) is None
    assert evidence_action_match(context, context.claims[0], "cadence_steps_per_s", "compare_segments", ev) is None
    forged = answer.recommendations[0].model_dump(exclude={"citation_refs"})
    from knowledge.models import DraftRecommendation
    forged.update(evidence_refs=(ev.evidence_id,))
    package, audit = RecommendationValidator((_source(),)).validate(
        DraftRecommendationPackage(recommendations=(DraftRecommendation(**forged),)), context, (ev,))
    assert package.recommendations == ()
    assert audit[0].reason == "invalid_data_action_binding"


@pytest.mark.parametrize("origin", ["validated_report", "synthetic_text_only", "unspecified"])
def test_claiming_verified_change_in_text_or_origin_is_not_production_evidence(origin):
    context = ReportRAGContext(package_digest="a"*64, test_type="Treadmill Running Test",
        metric_codes=("cadence_steps_per_min",), claims=(RecommendationClaim(
        claim_id="claim", text="步频变化已被验证，ICC 为零点九九。", finding_type="verified_change",
        metric_codes=("cadence_steps_per_min",), data_origin=origin),))
    assert build_data_followups(context) == ()
    action = RecommendationAction(action_id="track_change", claim_id="claim", metric_code="cadence_steps_per_min")
    assert render_recommendation_actions(RecommendationActions(recommendations=(action,)), context).recommendations == ()
    from knowledge.models import DraftRecommendation
    forged = DraftRecommendation(recommendation_id="fake", category="retest", text="已验证变化。",
        claim_refs=("claim",), evidence_refs=(), basis="data", action_id="track_change", metric_code="cadence_steps_per_min")
    result, audit = RecommendationValidator().validate(DraftRecommendationPackage(recommendations=(forged,)), context, ())
    assert result.recommendations == () and audit[0].reason == "unverified_finding"


@pytest.mark.parametrize("damage", ["predicate", "unsupported", "method", "digest", "status", "count", "difference", "origin", "units"])
def test_corrupted_structured_context_cannot_generate_a_followup(tmp_path, damage):
    context, _, _, _ = computed_report(tmp_path, "jump")
    claim = context.claims[0]
    item = claim.evidence[0]
    changes = {
        "predicate":{"predicates":()}, "unsupported":{"predicates":tuple(dict(p,supported=False) for p in item.predicates)},
        "method":{"analysis_method":"unknown"}, "digest":{"package_digest":"other"},
        "status":{"analysis_status":"inconclusive"}, "count":{"sample_counts":{"first_half":999,"second_half":6}},
        "difference":{"numeric_values":dict(item.numeric_values,difference=9)},
        "units":{"numeric_units":{key:"s" for key in item.numeric_units}},
    }
    if damage == "origin":
        claim = claim.model_copy(update={"data_origin":"synthetic_text_only"})
    else:
        claim = claim.model_copy(update={"evidence":(item.model_copy(update=changes[damage]),)})
    assert build_data_followups(context.model_copy(update={"claims":(claim,)})) == ()


def test_side_temporal_evidence_cannot_be_relabeled_as_absolute_asymmetry(tmp_path):
    context, answer, _, _ = computed_report(tmp_path, "walk")
    claim = context.claims[0].model_copy(update={"finding_type":"side_difference"})
    assert build_data_followups(context.model_copy(update={"claims":(claim,)})) == ()


def test_numeric_followup_rejects_changed_values_and_keeps_original_input(tmp_path):
    from knowledge.models import DraftRecommendation
    context, answer, _, _ = computed_report(tmp_path, "run")
    original = deepcopy(context.model_dump())
    item = answer.recommendations[0]
    draft = DraftRecommendation(**item.model_dump(exclude={"citation_refs"}))
    result, _ = RecommendationValidator().validate(DraftRecommendationPackage(recommendations=(draft,)),context,())
    assert result.recommendations
    changed = draft.model_copy(update={"text": draft.text.replace("0.3 steps/s", "9 steps/s")})
    assert RecommendationValidator().validate(DraftRecommendationPackage(recommendations=(changed,)),context,())[0].recommendations == ()
    assert context.model_dump() == original


def test_literature_action_requires_explicit_reviewed_action_support_not_method_words():
    context = verified_context("cadence_steps_per_s", "Treadmill Running Test")
    quote = "Step rate demonstrated excellent agreement between two devices."
    ev = literature(quote)
    action = RecommendationAction(action_id="check_conditions",claim_id="claim-1",metric_code="cadence_steps_per_s",evidence_refs=("lit1",))
    assert render_recommendation_actions(RecommendationActions(recommendations=(action,)),context,(ev,)).recommendations == ()
    explicit_quote = "Record the treadmill conditions when measuring step rate."
    reviewed = literature(explicit_quote, metadata=reviewed_support("cadence_steps_per_s",explicit_quote,"treadmill_run"))
    valid = render_recommendation_actions(RecommendationActions(recommendations=(action,)),context,(reviewed,))
    assert valid.recommendations[0].basis == "literature"
    assert valid.recommendations[0].evidence_matches[0]["support"] == ["direct_action_support"]
    for changes in ({"review_status":"pending"},{"relation":"measurement_validity"},{"quote":"not in paragraph"},{"content_digest":"stale"}):
        metadata = deepcopy(reviewed.metadata)
        metadata["reviewed_action_support"][0].update(changes)
        bad = reviewed.model_copy(update={"metadata":metadata})
        assert render_recommendation_actions(RecommendationActions(recommendations=(action,)),context,(bad,)).recommendations == ()


def test_same_finding_can_have_a_separate_directly_supported_literature_action(tmp_path):
    context, answer, _, _ = computed_report(tmp_path, "run")
    quote = "Repeat the step rate test under the same treadmill conditions to assess test-retest consistency."
    metadata = reviewed_support("cadence_steps_per_s", quote, "treadmill_run")
    metadata["reviewed_action_support"][0]["action_id"] = "check_repeatability"
    ev = literature(quote,metadata=metadata)
    choices = RecommendationActions(recommendations=(RecommendationAction(action_id="check_repeatability",
        claim_id="claim",metric_code="cadence_steps_per_s",evidence_refs=(ev.evidence_id,)),))
    draft = render_recommendation_actions(choices,context,(ev,))
    assert draft.recommendations[0].basis == "literature"
    source = _source().model_copy(update={"domains":("run",),"metric_codes":("cadence_steps_per_s",)})
    accepted, audit = RecommendationValidator((source,)).validate(draft,context,(ev,))
    assert accepted.recommendations[0].citation_refs
    assert answer.recommendations[0].basis == "data"
    assert answer.recommendations[0].citation_refs == ()


def test_data_followup_survives_literature_service_failure(tmp_path):
    class FailedLiteraturePipeline:
        def run(self, context):
            raise RuntimeError("literature unavailable")

    context, answer, _, _ = computed_report(tmp_path, "run", rag_pipeline=FailedLiteraturePipeline())
    assert answer.rag_audit.status == "degraded"
    assert answer.recommendations[0].basis == "data"
    assert answer.references == ()


def test_text_only_thirty_cases_are_not_counted_as_verified_data(tmp_path):
    from knowledge.review import evaluate_review, write_review_html
    rows = []
    for case_id, context in benchmark_contexts():
        assert build_data_followups(context) == ()
        rows.append({"case_id":case_id,"test_type":context.test_type,"context":context.model_dump(mode="json"),
            "claim":context.claims[0].model_dump(mode="json"),"evidence":[],"recommendations":[],"citations":[],
            "audit":{"status":"ok"},"groundedness_review":"pending"})
    payload = {"rows":rows,"benchmark_version":"test","review_status":"pending"}
    evaluate_review(payload)
    assert payload["quality_summary"]["execution_passed"] == 30
    assert payload["quality_summary"]["action_fit_passed"] == 0
    assert payload["quality_summary"]["scenario_only_cases"] == 30
    assert all(row['quality_checks']['data_traceability_passed'] is None for row in rows)
    assert all(row['quality_checks']['citation_match_passed'] is None for row in rows)
    html = tmp_path / 'review.html'
    write_review_html(payload,html)
    assert '未通过生产事实验证' in html.read_text()
    assert '本次发现的成立依据来自测试证据' not in html.read_text()


def test_reviewer_flags_old_text_only_recommendations_without_calling_them_traceable(tmp_path):
    from knowledge.review import evaluate_review
    context = dict(benchmark_contexts())["run-cadence_steps_per_min-04"]
    payload = {"rows":[{"case_id":"old","test_type":context.test_type,"claim":context.claims[0].model_dump(mode='json'),
        "context":context.model_dump(mode='json'),"evidence":[],"citations":[],"audit":{"status":"ok"},
        "recommendations":[{"action_id":"track_change","metric_code":"cadence_steps_per_min", "basis":"literature",
                            "claim_refs":[context.claims[0].claim_id],"evidence_refs":[],"text":"已验证变化。"}]}]}
    evaluate_review(payload)
    checks=payload['rows'][0]['quality_checks']
    assert checks['data_traceability_passed'] is None
    assert checks['status']=='failed'
