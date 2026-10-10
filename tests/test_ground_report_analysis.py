"""Ground analysis preserves producer semantics through storage, tools and UI."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from agent.report.service import ReportAnalysisService
from agent.report.skill_loader import ReportAnalysisSkillLoader
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from data.subject_store import SubjectStore
from reporting.builders import ReportDataPackageBuilder, ReportManifestBuilder
from reporting.kernel import AnalysisMethodRegistry
from reporting.models import DataAccessScope, DraftAnalysisPackage, ReportContextInput, ReportDataPackage
from reporting.repository import ReportRepository
from reporting.tools import AnalysisToolRegistry
from tests.report_export_fixtures import export_reports
from tests.test_analysis_kernel import _run
from tests.test_report_analysis_service import _SequentialServiceFakeAgent


TYPES = {"walking": "Sprint and Gait Test", "overground_running": "Overground Running Test"}


@pytest.fixture(scope="module")
def reports():
    return export_reports()


def package(report, mode):
    return ReportDataPackageBuilder().build(report, ReportContextInput(session_id=1, test_type=TYPES[mode]))


@pytest.mark.parametrize("mode", TYPES)
def test_ground_package_preserves_snapshot_units_sources_and_serialization(reports, mode):
    report = reports[mode]
    before = deepcopy(asdict(report))
    result = package(report, mode)
    assert asdict(report) == before
    assert ReportDataPackage.model_validate_json(result.model_dump_json()) == result
    assert result.context.test_type == TYPES[mode]
    assert result.context.config_snapshot["device"] == json.loads(json.dumps(report.report_config_snapshot["device"]))
    assert result.metadata.builder_version == "report-package-builder/1.1-ground"
    assert result.payload.spatial_reference == ("contact_center" if mode == "walking" else "stable_toe_proxy")
    assert {r.record_type for r in result.record_sets} == {"ground_contact", "ground_step", "ground_cycle"}
    definitions = {d.metric_code: d for d in result.metric_definitions}
    assert definitions["step_length_m"].unit == "m"
    assert definitions["contact_time_s"].unit == "s"
    assert definitions["speed_m_s"].unit == "m/s"
    source = report.walking_summary if mode == "walking" else report.running_summary
    first = source["steps"][0]["length_m"]
    assert result.record_sets[1].records[0].values["step_length_m"].value == (first if mode == "walking" else first["value"])
    for record_set in result.record_sets:
        for record in record_set.records:
            assert record.record_id in result.payload.record_sources
            assert result.resolve_ref(record.record_id) == record
    assert any(flag.code == "beam_quality" for flag in result.quality_flags)


@pytest.mark.parametrize("mode", TYPES)
def test_unknown_identity_never_enables_anatomical_side_comparison(reports, mode):
    report = replace(reports[mode], report_config_snapshot={**reports[mode].report_config_snapshot, "starting_foot": "Not defined"})
    result = package(report, mode)
    assert all(r.side == "unknown" for rs in result.record_sets for r in rs.records)
    assert "side" not in ReportManifestBuilder().build(result).available_dimensions
    capabilities = AnalysisToolRegistry().list_capabilities(result, DataAccessScope(), AnalysisMethodRegistry())
    side = next(m for c in capabilities for m in c.available_methods if m.analysis_method == "verify_side_segment_difference")
    assert not side.enabled
    assert side.unavailable_reason == "side_dimension_unavailable"


def test_running_missing_metric_does_not_remove_other_valid_values_or_turn_into_zero(reports):
    report = deepcopy(reports["overground_running"])
    report.running_summary["steps"][0]["flight_s"] = {"value": None, "valid": False, "missing_reason": "uncertain_short_clear"}
    result = package(report, "overground_running")
    step = result.record_sets[1].records[0]
    assert step.status.inclusion == "included"
    assert step.values["step_length_m"].state == "present"
    assert step.values["flight_time_s"].value is None
    assert step.values["flight_time_s"].reason == "uncertain_short_clear"
    cycle = result.record_sets[2].records[0]
    assert cycle.values["total_double_support_s"].value == 0
    assert cycle.values["total_double_support_s"].state == "present"


@pytest.mark.parametrize('legacy', [False, True])
def test_running_speed_sample_count_uses_available_distance_time_pairs(reports, legacy):
    report = deepcopy(reports['overground_running'])
    summary = report.running_summary
    assert len(summary['steps']) > 1
    for step in summary['steps']:
        step['speed_m_s'] = {'value': None, 'valid': False, 'missing_reason': 'toe_not_observed'}
    summary['steps'][-1]['speed_m_s'] = {'value': .8, 'valid': True, 'missing_reason': None}
    summary['running_speed_m_s'] = .8
    summary['valid_step_speeds'] = 1
    if legacy:
        summary.pop('valid_step_speeds')
    speed = next(f for f in package(report, 'overground_running').scalar_facts
                 if f.source_ref == 'running_summary:speed_m_s:mean')
    assert speed.value == pytest.approx(.8) and speed.sample_count == 1


def test_walking_excluded_incomplete_and_stopped_contacts_are_retained(reports):
    report = deepcopy(reports["walking"])
    summary = report.walking_summary
    summary["contacts"][0]["exclusion"] = "ambiguous_contacts"
    summary["contacts"][1]["end"] = None
    summary["stops"] = [{"start_s": summary["contacts"][2]["start"], "end_s": summary["contacts"][2]["end"]}]
    result = package(report, "walking")
    rows = result.record_sets[0].records
    assert len(rows) == len(summary["contacts"])
    assert rows[0].status.exclusion_reason == "ambiguous_contacts"
    assert rows[0].status.validity == "invalid"
    assert rows[1].values["contact_time_s"].state == "missing"
    assert rows[1].status.inclusion == "excluded"
    assert rows[2].status.exclusion_reason == "stop_interval"
    assert rows[2].status.inclusion == "excluded"
    assert "stride_length_m" not in result.record_sets[2].metric_codes


@pytest.mark.parametrize("mode", TYPES)
def test_empty_ground_report_keeps_metrics_missing(mode):
    from tests.test_overground_walking import processor as walking_processor
    from tests.test_overground_running import processor as running_processor
    processor = walking_processor() if mode == "walking" else running_processor()
    result = package(processor.build_report("manual"), mode)
    assert all(not record_set.records for record_set in result.record_sets)
    assert all(fact.state == "missing" for fact in result.scalar_facts if fact.metric_code not in {"touch_count", "lift_count"})
    assert "side" not in ReportManifestBuilder().build(result).available_dimensions


@pytest.mark.parametrize("mode", TYPES)
def test_small_ground_passage_returns_inconclusive_evidence(reports, mode):
    bundle = _run(package(reports[mode], mode), "verify_temporal_change", ["contact_time_s"])
    assert bundle.items[0].analysis_status == "inconclusive"
    assert "insufficient_sample_size" in bundle.items[0].limitations


class GroundAgent(_SequentialServiceFakeAgent):
    def synthesize_sequential(self, observation, state, evidence, skill_context):
        assert evidence[0].items[0].analysis_status == "inconclusive"
        assert observation.report_context.test_type in TYPES.values()
        assert any("overground-" in r.resource_id for r in skill_context.resources)
        return DraftAnalysisPackage(summary="样本不足，保留原报告指标。", claims=())


@pytest.mark.parametrize("mode", TYPES)
def test_ground_service_history_and_ui_use_same_validated_snapshot(tmp_path, qtbot, monkeypatch, reports, mode):
    from ui.views.report_view import ReportView
    report = reports[mode]
    config = WalkingConfig() if mode == "walking" else OvergroundRunningConfig(starting_foot="Left")
    store = SubjectStore(tmp_path / "ground.sqlite3")
    session_id = store.record_session(None, config, report)
    repository = ReportRepository(store)
    def unauthorized(*args, **kwargs):
        pytest.fail("current-session analysis must not read other sessions")
    monkeypatch.setattr(store, "get_sessions", unauthorized)
    monkeypatch.setattr(store, "get_team_sessions", unauthorized)
    service = ReportAnalysisService(repository, agent=GroundAgent(), rag_unavailable_error_code="rag_release_gate_invalid")
    restored = repository.get_package(session_id)
    result = service.analyze(session_id, DataAccessScope())
    assert result.cycle_count == 1
    assert not result.claims
    assert result.rag_audit.status == "degraded"
    assert result.package_digest == restored.metadata.package_digest
    calls = []
    class Client:
        def get_latest_analysis(self, requested_session, scope, timeout=5):
            assert requested_session == session_id
            return repository.get_latest_validated_analysis(session_id, DataAccessScope())
        def analyze_report(self, requested_session, scope, timeout=120):
            calls.append(requested_session)
            return {"analysis": service.analyze(requested_session, DataAccessScope()).model_dump(mode="json")}
    view = ReportView(llm_client=Client())
    qtbot.addWidget(view)
    view.set_analysis_availability(True)
    view.load_report(report, session_id)
    qtbot.waitUntil(lambda: not view._analysis_workers, timeout=5000)
    assert not view._analysis_panel.isHidden()
    assert view.request_voice_analysis()
    qtbot.waitUntil(lambda: not view._analysis_workers, timeout=5000)
    assert calls == [session_id]
    assert view._analysis_button.text() == "重新分析"


@pytest.mark.parametrize("mode,reference", [("walking", "references/overground-walk.md"), ("overground_running", "references/overground-run.md")])
def test_ground_skill_only_loads_matching_domain(mode, reference):
    context = ReportAnalysisSkillLoader().load_initial(TYPES[mode])
    assert [r.resource_id for r in context.resources] == ["SKILL.md", reference]
