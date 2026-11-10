"""Previous-test comparisons use saved means and exact subject/protocol boundaries."""

from dataclasses import replace

import pytest

from agent.report.service import ReportAnalysisError, ReportAnalysisService
from config.treadmill_config import TreadmillGaitConfig
from data.subject_store import SubjectStore
from reporting.comparison import comparison_html
from reporting.models import DataAccessScope
from reporting.repository import ReportRepository
from tests.reporting_fixtures import make_treadmill_report


def test_previous_comparison_selects_latest_compatible_past_test_and_binds_facts(tmp_path):
    store = SubjectStore(tmp_path / "comparison.sqlite3")
    subject = store.create_subject("Runner", 1990)
    other = store.create_subject("Other runner", 1990)
    config = TreadmillGaitConfig(stop_type="End of Time", test_length="01:00", treadmill_speed=5)
    first_report = make_treadmill_report([.2]*6, [.3]*6)
    current_report = make_treadmill_report([.4]*6, [.5]*6)
    first = store.record_session(subject, config, first_report, started_at="2026-11-01T12:00:00")
    store.record_session(subject, replace(config, treadmill_speed=6), first_report, started_at="2026-11-02T12:00:00")
    store.record_session(other, config, first_report, started_at="2026-11-03T12:00:00")
    store.record_session(subject, config, first_report, started_at="2026-12-01T12:00:00")
    current = store.record_session(subject, replace(config, treadmill_speed=5.0), current_report, started_at="2026-11-04T12:00:00")
    repository = ReportRepository(store)
    result = repository.compare_previous_session(current)
    assert result["previous_session_id"] == first
    assert result["current_session_id"] == current
    row = next(row for row in result["metrics"] if row["metric_code"] == "contact_time_s")
    assert row["previous"] == pytest.approx(.25)
    assert row["current"] == pytest.approx(.45)
    assert row["difference"] == pytest.approx(.2)
    assert row["previous_count"] == row["current_count"] == 12
    assert repository.get_package(current).resolve_ref(row["current_fact_ref"]).value == row["current"]
    assert repository.get_package(first).resolve_ref(row["previous_fact_ref"]).value == row["previous"]
    assert "0.2 s" in comparison_html(result)
    from reporting.pdf import report_html
    exported = report_html(current_report, title="报告", stats=[], reason="完成", comparison=result)
    assert "完整测试与上次同协议记录对比" in exported
    assert "0.2 s" in exported


def test_guest_comparison_stops_before_loading_report_or_history(tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "guest.sqlite3")
    config = TreadmillGaitConfig(stop_type="End of Time", test_length="01:00")
    session = store.record_session(None, config, make_treadmill_report([.2]*6, [.3]*6))
    repository = ReportRepository(store)
    from data.subject_store import SessionRecord
    monkeypatch.setattr(SessionRecord, "report", property(lambda self: pytest.fail("guest report/history read")))
    assert repository.compare_previous_session(session) == {"status": "guest"}
    assert comparison_html({"status": "guest"}) == ""


def test_protocol_versions_and_team_context_must_match(tmp_path):
    store = SubjectStore(tmp_path / "protocol.sqlite3")
    team = store.create_team("Team")
    subject = store.create_subject("Runner", 1990, team_id=team)
    config = TreadmillGaitConfig(stop_type="End of Time", test_length="01:00")
    report = make_treadmill_report([.2]*6, [.3]*6)
    store.record_session(subject, config, report, team_id=team, team_snapshot={"id": team, "name": "Team"})
    versioned = replace(report, report_config_snapshot={"algorithm": "v2"})
    store.record_session(subject, config, versioned)
    current = store.record_session(subject, config, report)
    repository = ReportRepository(store)
    assert repository.compare_previous_session(current)["status"] == "no_previous"
    service = ReportAnalysisService(repository)
    with pytest.raises(ReportAnalysisError) as error:
        service.compare_previous(current, DataAccessScope())
    assert error.value.code == "scope_not_authorized"
    assert service.compare_previous(current, DataAccessScope(longitudinal=True))["status"] == "no_previous"


def test_no_common_valid_metric_has_an_explicit_result(tmp_path):
    store = SubjectStore(tmp_path / "empty.sqlite3")
    subject = store.create_subject("Runner", 1990)
    config = TreadmillGaitConfig(stop_type="End of Time", test_length="01:00")
    store.record_session(subject, config, make_treadmill_report([], []))
    current = store.record_session(subject, config, make_treadmill_report([.2]*6, [.3]*6))
    result = ReportRepository(store).compare_previous_session(current)
    assert result["status"] == "no_common_metrics"
    assert result["metrics"] == []
