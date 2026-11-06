"""Repository tests for report snapshot reconstruction and analysis audit rows."""

from __future__ import annotations

import sqlite3
import json

import pytest

from config.test_config import default_jump_config
from config.test_report import JumpResultRecord, JumpTestReport
from data.subject_store import SubjectStore
from reporting.models import DataAccessScope
from reporting.models import SequentialAnalysisState, SequentialLoopCheckpoint
from reporting.kernel import ANALYSIS_METHOD_REGISTRY_VERSION, KERNEL_VERSION
from reporting.observation import OBSERVATION_BUILDER_VERSION
from reporting.repository import (
    MissingReportSnapshotError,
    ReportRepository,
    ReportSessionNotFoundError,
)
from reporting.tools import ANALYSIS_TOOL_REGISTRY_VERSION


def _report():
    row = JumpResultRecord(
        index=1,
        lift_time_s=0.1,
        touch_time_s=0.5,
        air_time_s=0.4,
        jump_height_m=0.1962,
        contact_time_s=None,
        cycle_time_s=None,
        cadence_jumps_per_min=None,
        is_included_in_statistics=True,
    )
    return JumpTestReport(
        touch_count=1,
        lift_count=1,
        air_times=(0.4,),
        contact_times=(),
        cycle_times=(),
        avg_jump_height=0.1962,
        max_jump_height=0.1962,
        avg_air_time=0.4,
        max_air_time=0.4,
        avg_contact_time=0.0,
        avg_cadence=None,
        finish_reason="manual",
        jump_heights=(0.1962,),
        min_jump_height=0.1962,
        jump_results=(row,),
    )


@pytest.fixture
def store(tmp_path):
    return SubjectStore(tmp_path / "reporting.sqlite3")


def test_repository_rebuilds_stable_package_using_session_id_only(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)

    package_a = repository.get_package(session_id)
    package_b = repository.get_package(session_id)
    manifest = repository.get_manifest(session_id)

    assert package_a == package_b
    assert package_a.metadata.session_id == session_id
    assert package_a.context.config_snapshot["test_type"] == "Jump Test"
    assert manifest.package_digest == package_a.metadata.package_digest


def test_get_package_does_not_load_history_or_team_report_details(store, monkeypatch):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    monkeypatch.setattr(
        store,
        "get_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("history read")),
    )
    monkeypatch.setattr(
        store,
        "get_team_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("team read")),
    )

    assert repository.get_package(session_id).metadata.session_id == session_id


def test_scope_availability_counts_candidates_without_loading_details(store):
    team_id = store.create_team("A Team")
    subject_id = store.create_subject("Runner A", 1990, team_id=team_id)
    teammate_id = store.create_subject("Runner B", 1992, team_id=team_id)
    session_id = store.record_session(
        subject_id,
        default_jump_config(),
        _report(),
        team_id=team_id,
        team_snapshot={"id": team_id, "name": "A Team"},
    )
    store.record_session(
        subject_id,
        default_jump_config(),
        _report(),
        team_id=team_id,
        team_snapshot={"id": team_id, "name": "A Team"},
    )
    store.record_session(
        teammate_id,
        default_jump_config(),
        _report(),
        team_id=team_id,
        team_snapshot={"id": team_id, "name": "A Team"},
    )

    availability = ReportRepository(store).get_scope_availability(session_id)

    assert availability.longitudinal_candidates == 1
    assert availability.cohort_candidates == 1
    assert availability.longitudinal_available is True
    assert availability.cohort_available is True


def test_temporary_session_has_no_external_scope(store):
    session_id = store.record_session(None, default_jump_config(), _report())

    availability = ReportRepository(store).get_scope_availability(session_id)

    assert availability.longitudinal_available is False
    assert availability.cohort_available is False
    assert "temporary_session_has_no_external_scope" in availability.reasons


def test_analysis_runs_are_append_only_and_only_validated_result_is_reused(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    package = repository.get_package(session_id)
    scope = DataAccessScope()

    failed_run = repository.create_analysis_run(
        session_id,
        scope,
        package.metadata.package_digest,
        model_name="fake",
        prompt_version="v1",
    )
    repository.finalize_analysis_run(failed_run, "failed", None, "model_failed")
    assert repository.get_latest_validated_analysis(
        session_id, scope, package.metadata.package_digest
    ) is None

    valid_run = repository.create_analysis_run(
        session_id,
        scope,
        package.metadata.package_digest,
        model_name="fake",
        prompt_version="v1",
    )
    repository.finalize_analysis_run(
        valid_run,
        "validated",
        {"analysis_run_id": valid_run, "claims": []},
    )
    assert repository.get_latest_validated_analysis(
        session_id, scope, package.metadata.package_digest
    ) == {"analysis_run_id": valid_run, "claims": []}
    assert repository.get_latest_validated_analysis(
        session_id, scope, "different-digest"
    ) is None

    with sqlite3.connect(store.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM report_analyses").fetchone()[0]
    assert count == 2


def test_missing_session_and_missing_snapshot_have_stable_errors(store):
    repository = ReportRepository(store)
    with pytest.raises(ReportSessionNotFoundError):
        repository.get_package(999)

    session_id = store.record_session(None, default_jump_config(), _report())
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE test_sessions SET report_detail_json = NULL WHERE id = ?",
            (session_id,),
        )
    with pytest.raises(MissingReportSnapshotError):
        repository.get_package(session_id)


def _checkpoint(session_id, package_digest, scope=DataAccessScope()):
    return SequentialLoopCheckpoint(
        phase="skill_loaded",
        session_id=session_id,
        package_digest=package_digest,
        data_access_scope=scope,
        state=SequentialAnalysisState(
            loaded_skill_references=("references/jump.md",)
        ),
        skill_version="report-analysis-skill/0.5",
        skill_content_digest="a" * 64,
        observation_builder_version=OBSERVATION_BUILDER_VERSION,
        analysis_tool_registry_version=ANALYSIS_TOOL_REGISTRY_VERSION,
        analysis_method_registry_version=ANALYSIS_METHOD_REGISTRY_VERSION,
        kernel_version=KERNEL_VERSION,
    )


def test_running_checkpoint_is_append_only_and_requires_exact_versions(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    package = repository.get_package(session_id)
    scope = DataAccessScope()
    run_id = repository.create_analysis_run(
        session_id,
        scope,
        package.metadata.package_digest,
        model_name="fake",
        prompt_version="v2",
    )
    checkpoint = _checkpoint(
        session_id, package.metadata.package_digest, scope
    )

    repository.save_analysis_checkpoint(run_id, checkpoint)
    repository.save_analysis_checkpoint(run_id, checkpoint)

    expected = dict(
        model_name="fake",
        prompt_version="v2",
        skill_version=checkpoint.skill_version,
        observation_builder_version=checkpoint.observation_builder_version,
        analysis_tool_registry_version=checkpoint.analysis_tool_registry_version,
        analysis_method_registry_version=checkpoint.analysis_method_registry_version,
        kernel_version=checkpoint.kernel_version,
    )
    resumed = repository.get_resumable_analysis_checkpoint(
        session_id,
        scope,
        package.metadata.package_digest,
        **expected,
    )

    assert resumed is not None
    assert resumed.analysis_run_id == run_id
    assert resumed.checkpoint == checkpoint
    assert repository.get_resumable_analysis_checkpoint(
        session_id,
        scope,
        package.metadata.package_digest,
        **{**expected, "kernel_version": "analysis-kernel/changed"},
    ) is None

    digest_checkpoint = checkpoint.model_copy(
        update={"prompt_content_digest": "c" * 64}
    )
    repository.save_analysis_checkpoint(run_id, digest_checkpoint)
    assert repository.get_resumable_analysis_checkpoint(
        session_id,
        scope,
        package.metadata.package_digest,
        **{**expected, "prompt_content_digest": "d" * 64},
    ) is None
    assert repository.get_resumable_analysis_checkpoint(
        session_id,
        scope,
        package.metadata.package_digest,
        **{**expected, "prompt_content_digest": "c" * 64},
    ).checkpoint == digest_checkpoint
    with sqlite3.connect(store.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM report_analysis_checkpoints"
        ).fetchone()[0]
    assert count == 3

    repository.finalize_analysis_run(run_id, "failed", None, "interrupted")
    assert repository.get_resumable_analysis_checkpoint(
        session_id,
        scope,
        package.metadata.package_digest,
        **expected,
    ) is None


def test_checkpoint_cannot_be_attached_to_a_different_or_finalized_run(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    package = repository.get_package(session_id)
    run_id = repository.create_analysis_run(
        session_id,
        DataAccessScope(),
        package.metadata.package_digest,
        model_name="fake",
        prompt_version="v2",
    )
    checkpoint = _checkpoint(session_id, package.metadata.package_digest)

    with pytest.raises(ValueError, match="identity"):
        repository.save_analysis_checkpoint(
            run_id,
            checkpoint.model_copy(update={"package_digest": "b" * 64}),
        )

    repository.finalize_analysis_run(run_id, "failed", None, "stopped")
    with pytest.raises(ValueError, match="finalized"):
        repository.save_analysis_checkpoint(run_id, checkpoint)


def test_followup_results_do_not_replace_default_latest(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    digest = repository.get_package(session_id).metadata.package_digest
    scope = DataAccessScope()
    payloads = {}
    for request_digest in ("", "a" * 64, "b" * 64):
        run_id = repository.create_analysis_run(
            session_id, scope, digest, model_name="fake", prompt_version="v1",
            request_digest=request_digest,
        )
        payloads[request_digest] = {"analysis_run_id": run_id, "claims": []}
        repository.finalize_analysis_run(run_id, "validated", payloads[request_digest])

    assert repository.get_latest_validated_analysis(session_id, scope, digest) == payloads[""]
    assert repository.get_latest_validated_analysis(
        session_id, scope, digest, request_digest="a" * 64,
    ) == payloads["a" * 64]
    assert repository.get_latest_validated_analysis(
        session_id, scope, digest, request_digest="c" * 64,
    ) is None


def test_parent_result_requires_exact_run_session_scope_snapshot_and_status(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    other_session = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    digest = repository.get_package(session_id).metadata.package_digest
    scope = DataAccessScope()
    run_id = repository.create_analysis_run(
        session_id, scope, digest, model_name="fake", prompt_version="v1",
        request_digest="a" * 64,
    )
    assert repository.get_validated_analysis(run_id, session_id, scope, digest) is None
    payload = {"analysis_run_id": run_id, "claims": []}
    repository.finalize_analysis_run(run_id, "validated", payload)
    assert repository.get_validated_analysis(run_id, session_id, scope, digest) == payload
    for candidate in (
        ("missing", session_id, scope, digest),
        (run_id, other_session, scope, digest),
        (run_id, session_id, DataAccessScope(longitudinal=True), digest),
        (run_id, session_id, scope, "different-digest"),
    ):
        assert repository.get_validated_analysis(*candidate) is None
    failed_run = repository.create_analysis_run(
        session_id, scope, digest, model_name="fake", prompt_version="v1",
    )
    repository.finalize_analysis_run(failed_run, "failed", payload)
    assert repository.get_validated_analysis(failed_run, session_id, scope, digest) is None


def test_followup_checkpoints_are_isolated_by_request_digest(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    digest = repository.get_package(session_id).metadata.package_digest
    scope = DataAccessScope()
    checkpoints = {}
    run_ids = {}
    for request_digest in ("", "a" * 64, "b" * 64):
        run_id = repository.create_analysis_run(
            session_id, scope, digest, model_name="fake", prompt_version="v2",
            request_digest=request_digest,
        )
        checkpoint = _checkpoint(session_id, digest).model_copy(
            update={"request_digest": request_digest}
        )
        repository.save_analysis_checkpoint(run_id, checkpoint)
        checkpoints[request_digest] = checkpoint
        run_ids[request_digest] = run_id
    expected = dict(
        model_name="fake", prompt_version="v2",
        skill_version=checkpoint.skill_version,
        observation_builder_version=checkpoint.observation_builder_version,
        analysis_tool_registry_version=checkpoint.analysis_tool_registry_version,
        analysis_method_registry_version=checkpoint.analysis_method_registry_version,
        kernel_version=checkpoint.kernel_version,
    )
    for request_digest in run_ids:
        resumed = repository.get_resumable_analysis_checkpoint(
            session_id, scope, digest, request_digest=request_digest, **expected,
        )
        assert resumed.analysis_run_id == run_ids[request_digest]
    with pytest.raises(ValueError, match="identity"):
        repository.save_analysis_checkpoint(run_ids["a" * 64], checkpoints["b" * 64])

    # Verify checkpoint JSON independently of the matching run-row identity.
    for field, value in (
        ("request_digest", "b" * 64),
        ("session_id", session_id + 1),
        ("package_digest", "c" * 64),
        ("data_access_scope", DataAccessScope(longitudinal=True).model_dump(mode="json")),
    ):
        mismatched_json = checkpoints["a" * 64].model_dump(mode="json")
        mismatched_json[field] = value
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                "UPDATE report_analysis_checkpoints SET checkpoint_json = ? "
                "WHERE analysis_run_id = ?",
                (json.dumps(mismatched_json), run_ids["a" * 64]),
            )
        assert repository.get_resumable_analysis_checkpoint(
            session_id, scope, digest, request_digest="a" * 64, **expected,
        ) is None


def test_existing_analysis_rows_migrate_to_default_request_identity(store):
    session_id = store.record_session(None, default_jump_config(), _report())
    repository = ReportRepository(store)
    digest = repository.get_package(session_id).metadata.package_digest
    scope = DataAccessScope()
    run_id = repository.create_analysis_run(
        session_id, scope, digest, model_name="fake", prompt_version="v1",
    )
    payload = {"analysis_run_id": run_id, "claims": []}
    repository.finalize_analysis_run(run_id, "validated", payload)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("ALTER TABLE report_analyses DROP COLUMN request_digest")

    migrated = ReportRepository(store)
    assert migrated.get_latest_validated_analysis(session_id, scope, digest) == payload
    with sqlite3.connect(store.db_path) as conn:
        stored_digest = conn.execute(
            "SELECT request_digest FROM report_analyses WHERE analysis_run_id = ?",
            (run_id,),
        ).fetchone()[0]
    assert stored_digest == ""
