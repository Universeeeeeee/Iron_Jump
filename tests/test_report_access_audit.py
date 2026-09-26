"""Frozen current-session data-access audit across production failure modes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent.report.service as report_service_module
from agent.report.deadline import ReportAnalysisDeadlinePolicy
from agent.report.service import ReportAnalysisError, ReportAnalysisService
from agent.report.tools import (
    AnalysisToolGateway,
    TransientAnalysisToolError,
)
from config.test_config import default_jump_config
from data.subject_store import SubjectStore
from reporting.models import DataAccessScope
from reporting.repository import ReportRepository
from tests.reporting_fixtures import make_jump_report
from tests.test_report_analysis_service import (
    _DeadlineStopAgent,
    _FakeClock,
    _ProcessInterrupted,
    _SequentialFailsAfterEvidence,
    _SequentialRepairingAgent,
    _SequentialServiceFakeAgent,
    _SynthesisTimeoutAgent,
)


AUDIT_PATH = (
    Path(__file__).resolve().parents[1]
    / "benchmark_results"
    / "report_agent_access_audit_20260824.json"
)


class _SubjectStoreSpy:
    def __init__(self, store, contract):
        self._store = store
        self.db_path = store.db_path
        self.calls = []
        self.violations = []
        self._allowed = set(contract["authorized_subject_store_reads"])
        self._forbidden = set(contract["forbidden_subject_store_reads"])

    def __getattr__(self, name):
        target = getattr(self._store, name)
        if not callable(target):
            return target

        def audited(*args, **kwargs):
            self.calls.append(name)
            if name in self._forbidden or name not in self._allowed:
                self.violations.append(name)
                raise AssertionError(f"unauthorized SubjectStore read: {name}")
            return target(*args, **kwargs)

        return audited


class _RepositorySpy:
    def __init__(self, repository, contract):
        self._repository = repository
        self.calls = []
        self.violations = []
        self._allowed = set(contract["authorized_repository_calls"])
        self._forbidden = set(contract["forbidden_repository_calls"])

    def __getattr__(self, name):
        target = getattr(self._repository, name)
        if not callable(target):
            return target

        def audited(*args, **kwargs):
            self.calls.append(name)
            if name in self._forbidden or name not in self._allowed:
                self.violations.append(name)
                raise AssertionError(f"unauthorized ReportRepository call: {name}")
            return target(*args, **kwargs)

        return audited


class _FailingTool:
    def __init__(self, *, transient):
        self.transient = transient

    def execute(self, package, node, spec, dependency_evidence):
        if self.transient:
            raise TransientAnalysisToolError("temporary Tool failure")
        raise RuntimeError("hard Tool failure")


class _FailingRAG:
    def run(self, context):
        raise RuntimeError("RAG unavailable")


def _audited_service(tmp_path, contract, agent, **service_kwargs):
    store = SubjectStore(tmp_path / "access-audit.sqlite3")
    team_id = store.create_team("审计团队")
    subject_id = store.create_subject(
        "目标运动员",
        2000,
        team_id=team_id,
    )
    decoy_id = store.create_subject("干扰运动员", 1999, team_id=team_id)
    report = make_jump_report([0.2] * 6 + [0.3] * 6)
    config = default_jump_config()
    target_session_id = store.record_session(
        subject_id,
        config,
        report,
        subject_snapshot={"id": subject_id, "display_name": "目标运动员"},
        team_id=team_id,
        team_snapshot={"id": team_id, "name": "审计团队"},
    )
    store.record_session(
        decoy_id,
        config,
        report,
        subject_snapshot={"id": decoy_id, "display_name": "干扰运动员"},
        team_id=team_id,
        team_snapshot={"id": team_id, "name": "审计团队"},
    )
    store_spy = _SubjectStoreSpy(store, contract)
    repository_spy = _RepositorySpy(ReportRepository(store_spy), contract)
    service = ReportAnalysisService(
        repository_spy,
        agent=agent,
        **service_kwargs,
    )
    return target_session_id, store_spy, repository_spy, service


@pytest.mark.parametrize(
    "scenario",
    (
        "normal_sequential",
        "model_failure_after_evidence",
        "hard_tool_failure",
        "transient_tool_retry_exhausted",
        "rag_degraded",
        "investigation_deadline_stop",
        "synthesis_timeout",
    ),
)
def test_current_session_access_audit_failure_matrix(
    tmp_path, monkeypatch, scenario
):
    contract = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    clock = None
    service_kwargs = {}
    if scenario == "model_failure_after_evidence":
        agent = _SequentialFailsAfterEvidence()
    elif scenario == "investigation_deadline_stop":
        clock = _FakeClock()
        agent = _DeadlineStopAgent(clock)
    elif scenario == "synthesis_timeout":
        clock = _FakeClock()
        agent = _SynthesisTimeoutAgent(clock)
    else:
        agent = _SequentialServiceFakeAgent()
    if scenario in {"investigation_deadline_stop", "synthesis_timeout"}:
        service_kwargs.update(
            deadline_policy=ReportAnalysisDeadlinePolicy(
                total_seconds=3,
                synthesis_reserve_seconds=1,
                max_model_request_seconds=1,
            ),
            clock=clock,
        )
    if scenario == "rag_degraded":
        service_kwargs["rag_pipeline"] = _FailingRAG()
    if scenario in {"hard_tool_failure", "transient_tool_retry_exhausted"}:
        gateway = AnalysisToolGateway(
            tool_implementations={
                "analyze_current_session": _FailingTool(
                    transient=scenario == "transient_tool_retry_exhausted"
                )
            }
        )
        monkeypatch.setattr(
            report_service_module,
            "AnalysisToolGateway",
            lambda **kwargs: gateway,
        )

    session_id, store_spy, repository_spy, service = _audited_service(
        tmp_path, contract, agent, **service_kwargs
    )
    if scenario in {
        "model_failure_after_evidence",
        "hard_tool_failure",
        "transient_tool_retry_exhausted",
        "synthesis_timeout",
    }:
        with pytest.raises(ReportAnalysisError):
            service.analyze(session_id, DataAccessScope())
    else:
        service.analyze(session_id, DataAccessScope())

    assert store_spy.violations == []
    assert repository_spy.violations == []
    assert set(store_spy.calls) == set(
        contract["authorized_subject_store_reads"]
    )
    assert set(repository_spy.calls).issubset(
        set(contract["authorized_repository_calls"])
    )


@pytest.mark.parametrize(
    "phase,agent",
    (
        ("action_accepted", _SequentialServiceFakeAgent()),
        ("evidence_recorded", _SequentialServiceFakeAgent()),
        ("claim_repair_pending", _SequentialRepairingAgent()),
    ),
)
def test_checkpoint_resume_keeps_access_within_current_session(
    tmp_path, phase, agent
):
    contract = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    session_id, store_spy, repository_spy, service = _audited_service(
        tmp_path, contract, agent
    )
    repository_spy._repository.interrupt_phase = phase

    original_save = repository_spy._repository.save_analysis_checkpoint

    def interrupting_save(run_id, checkpoint):
        original_save(run_id, checkpoint)
        if checkpoint.phase == repository_spy._repository.interrupt_phase:
            repository_spy._repository.interrupt_phase = None
            raise _ProcessInterrupted(phase)

    repository_spy._repository.save_analysis_checkpoint = interrupting_save
    with pytest.raises(_ProcessInterrupted):
        service.analyze(session_id, DataAccessScope())

    service.analyze(session_id, DataAccessScope())

    assert store_spy.violations == []
    assert repository_spy.violations == []
    assert set(store_spy.calls) == set(
        contract["authorized_subject_store_reads"]
    )
