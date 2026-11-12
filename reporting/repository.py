"""Read-only report access and append-only Report Agent run persistence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal

from data.subject_store import SessionRecord, SubjectStore

from .builders import ReportDataPackageBuilder, ReportManifestBuilder
from .models import (
    AnalysisRunMetrics,
    DataAccessScope,
    DataScopeAvailability,
    ReportContextInput,
    ReportDataPackage,
    ReportManifest,
    ResumableSequentialAnalysis,
    SequentialLoopCheckpoint,
)


AnalysisRunStatus = Literal["running", "validated", "rejected", "failed"]


class ReportSessionNotFoundError(KeyError):
    pass


class MissingReportSnapshotError(ValueError):
    pass


class ReportRepository:
    def __init__(
        self,
        subject_store: SubjectStore,
        *,
        package_builder: ReportDataPackageBuilder | None = None,
        manifest_builder: ReportManifestBuilder | None = None,
    ):
        self._store = subject_store
        self._package_builder = package_builder or ReportDataPackageBuilder()
        self._manifest_builder = manifest_builder or ReportManifestBuilder()
        self._init_analysis_table()

    def get_session_context(self, session_id: int) -> ReportContextInput:
        session = self._get_session(session_id)
        return ReportContextInput(
            session_id=session.id,
            test_type=session.test_type,
            started_at=session.started_at,
            finished_at=session.finished_at,
            subject_id=session.subject_id,
            team_id=session.team_id,
            is_temporary=session.is_temporary,
            subject_snapshot=session.subject_snapshot,
            team_snapshot=session.team_snapshot,
            config_snapshot=session.config.to_dict(),
        )

    def get_package(self, session_id: int) -> ReportDataPackage:
        session = self._get_session(session_id)
        if not session.report_detail_json:
            raise MissingReportSnapshotError(
                f"Session {session_id} does not contain report_detail_json"
            )
        return self._package_builder.build(
            session.report,
            self.get_session_context(session_id),
        )

    def get_manifest(self, session_id: int) -> ReportManifest:
        return self._manifest_builder.build(self.get_package(session_id))

    def get_scope_availability(self, session_id: int) -> DataScopeAvailability:
        session = self._get_session(session_id)
        if session.is_temporary or session.subject_id is None:
            return DataScopeAvailability(
                reasons=("temporary_session_has_no_external_scope",)
            )
        longitudinal_count = self._store.count_subject_session_candidates(
            session.subject_id,
            session.test_type,
            exclude_session_id=session.id,
        )
        cohort_count = 0
        reasons: list[str] = []
        if session.team_id is not None:
            cohort_count = self._store.count_team_session_candidates(
                session.team_id,
                session.test_type,
                exclude_session_id=session.id,
                exclude_subject_id=session.subject_id,
            )
        else:
            reasons.append("session_has_no_team_scope")
        return DataScopeAvailability(
            longitudinal_candidates=longitudinal_count,
            cohort_candidates=cohort_count,
            longitudinal_available=longitudinal_count > 0,
            cohort_available=cohort_count > 0,
            reasons=tuple(reasons),
        )

    def compare_previous_session(self, session_id):
        from .comparison import compare_packages

        current = self._get_session(session_id)
        if current.is_temporary or current.subject_id is None:
            return {"status": "guest"}
        match = self.get_previous_package(session_id)
        if match:
            previous, protocol = match
            return compare_packages(self.get_package(session_id), previous, protocol)
        return {"status": "no_previous", "current_session_id": session_id}

    def get_previous_package(self, session_id):
        from .comparison import protocol_description, protocol_digest

        current = self._get_session(session_id)
        if current.is_temporary or current.subject_id is None:
            return None
        protocol = protocol_description(current)
        with self._connect() as conn:
            candidates = conn.execute(
                """SELECT id FROM test_sessions
                   WHERE subject_id = ? AND test_type = ? AND team_id IS ?
                     AND is_temporary = 0 AND report_detail_json IS NOT NULL
                     AND report_detail_json NOT IN ('', '{}')
                     AND (started_at < ? OR (started_at = ? AND id < ?))
                   ORDER BY started_at DESC, id DESC""",
                (current.subject_id, current.test_type, current.team_id,
                 current.started_at, current.started_at, current.id),
            ).fetchall()
        for row in candidates:
            previous = self._get_session(row["id"])
            if protocol_description(previous) == protocol:
                return self.get_package(previous.id), protocol_digest(protocol)
        return None

    def longitudinal_is_current(self, analysis):
        context = (analysis.get("question_context") or {}).get("longitudinal")
        if not context:
            return True
        try:
            current = self.get_package(analysis["session_id"])
            match = self.get_previous_package(analysis["session_id"])
            if match is None:
                return False
            previous, protocol = match
            return (
                current.metadata.package_digest == context["current"]["package_digest"]
                and current.metadata.session_id == context["current"]["session_id"]
                and previous.metadata.package_digest == context["previous"]["package_digest"]
                and previous.metadata.session_id == context["previous"]["session_id"]
                and protocol == context["protocol_digest"]
            )
        except (KeyError, ValueError, TypeError):
            return False

    def create_analysis_run(
        self,
        session_id: int,
        scope: DataAccessScope,
        package_digest: str,
        *,
        model_name: str,
        prompt_version: str,
        request_digest: str = "",
    ) -> str:
        self._get_session(session_id)
        run_id = f"run_{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO report_analyses (
                    analysis_run_id, session_id, status,
                    data_access_scope_json, package_digest,
                    model_name, prompt_version, request_digest, created_at
                ) VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    self._scope_json(scope),
                    package_digest,
                    model_name,
                    prompt_version,
                    request_digest,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
        return run_id

    def finalize_analysis_run(
        self,
        run_id: str,
        status: AnalysisRunStatus,
        package: dict[str, Any] | None,
        error_code: str | None = None,
    ) -> None:
        if status == "running":
            raise ValueError("final status cannot be running")
        if status == "validated" and package is None:
            raise ValueError("validated runs require an analysis package")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT status FROM report_analyses WHERE analysis_run_id = ?",
                (run_id,),
            ).fetchone()
            if current is None:
                raise KeyError(f"Analysis run not found: {run_id}")
            if current["status"] != "running":
                raise ValueError("analysis run is already finalized")
            conn.execute(
                """
                UPDATE report_analyses
                SET status = ?, analysis_package_json = ?, error_code = ?
                WHERE analysis_run_id = ?
                """,
                (
                    status,
                    json.dumps(package, ensure_ascii=False, sort_keys=True)
                    if package is not None
                    else None,
                    error_code,
                    run_id,
                ),
            )

    def get_latest_validated_analysis(
        self,
        session_id: int,
        scope: DataAccessScope,
        package_digest: str,
        *,
        request_digest: str = "",
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT analysis_package_json
                FROM report_analyses
                WHERE session_id = ? AND status = 'validated'
                  AND data_access_scope_json = ? AND package_digest = ?
                  AND request_digest = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (session_id, self._scope_json(scope), package_digest, request_digest),
            ).fetchone()
        if row is None or not row["analysis_package_json"]:
            return None
        return json.loads(row["analysis_package_json"])

    def get_validated_analysis(
        self,
        run_id: str,
        session_id: int,
        scope: DataAccessScope,
        package_digest: str,
        *,
        include_current_scope: bool = False,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT analysis_package_json
                FROM report_analyses
                WHERE analysis_run_id = ? AND session_id = ?
                  AND status = 'validated' AND data_access_scope_json IN (?, ?)
                  AND package_digest = ?
                """,
                (run_id, session_id, self._scope_json(scope),
                 self._scope_json(DataAccessScope()) if include_current_scope else self._scope_json(scope),
                 package_digest),
            ).fetchone()
        if row is None or not row["analysis_package_json"]:
            return None
        analysis = json.loads(row["analysis_package_json"])
        return analysis if self.longitudinal_is_current(analysis) else None

    def list_validated_analyses(self, session_id, scope, package_digest, *, include_current_scope=False):
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT analysis_run_id, created_at, analysis_package_json
                   FROM report_analyses
                   WHERE session_id = ? AND status = 'validated'
                     AND data_access_scope_json IN (?, ?) AND package_digest = ?
                   ORDER BY id DESC""",
                (session_id, self._scope_json(scope),
                 self._scope_json(DataAccessScope()) if include_current_scope else self._scope_json(scope),
                 package_digest),
            ).fetchall()
            history = []
            for row in rows:
                analysis = json.loads(row["analysis_package_json"])
                if not self.longitudinal_is_current(analysis):
                    continue
                context = analysis.get("question_context") or {}
                history.append({
                    "analysis_run_id": row["analysis_run_id"],
                    "created_at": row["created_at"],
                    "question": context.get("question", ""),
                    "parent_analysis_run_id": context.get("parent_analysis_run_id"),
                })
        return history

    def update_analysis_run_metrics(
        self,
        run_id: str,
        metrics: AnalysisRunMetrics,
    ) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE report_analyses
                SET run_metrics_json = ?
                WHERE analysis_run_id = ?
                """,
                (
                    json.dumps(
                        metrics.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    run_id,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Analysis run not found: {run_id}")

    def save_analysis_checkpoint(
        self,
        run_id: str,
        checkpoint: SequentialLoopCheckpoint,
    ) -> None:
        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT session_id, status, data_access_scope_json,
                       package_digest, request_digest
                FROM report_analyses
                WHERE analysis_run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"Analysis run not found: {run_id}")
            if run["status"] != "running":
                raise ValueError("cannot checkpoint a finalized analysis run")
            if (
                run["session_id"] != checkpoint.session_id
                or run["package_digest"] != checkpoint.package_digest
                or run["request_digest"] != checkpoint.request_digest
                or run["data_access_scope_json"]
                != self._scope_json(checkpoint.data_access_scope)
            ):
                raise ValueError("checkpoint identity does not match analysis run")
            conn.execute(
                """
                INSERT INTO report_analysis_checkpoints (
                    analysis_run_id, checkpoint_json, created_at
                ) VALUES (?, ?, ?)
                """,
                (
                    run_id,
                    json.dumps(
                        checkpoint.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

    def get_resumable_analysis_checkpoint(
        self,
        session_id: int,
        scope: DataAccessScope,
        package_digest: str,
        *,
        model_name: str,
        prompt_version: str,
        skill_version: str,
        observation_builder_version: str,
        analysis_tool_registry_version: str,
        analysis_method_registry_version: str,
        kernel_version: str,
        prompt_content_digest: str | None = None,
        request_digest: str = "",
    ) -> ResumableSequentialAnalysis | None:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.analysis_run_id, c.checkpoint_json
                FROM report_analyses AS r
                JOIN report_analysis_checkpoints AS c
                  ON c.analysis_run_id = r.analysis_run_id
                WHERE r.session_id = ? AND r.status = 'running'
                  AND r.data_access_scope_json = ?
                  AND r.package_digest = ?
                  AND r.request_digest = ?
                  AND r.model_name = ? AND r.prompt_version = ?
                ORDER BY c.id DESC
                """,
                (
                    session_id,
                    self._scope_json(scope),
                    package_digest,
                    request_digest,
                    model_name,
                    prompt_version,
                ),
            ).fetchall()
        expected_versions = {
            "session_id": session_id,
            "data_access_scope": scope,
            "package_digest": package_digest,
            "request_digest": request_digest,
            "skill_version": skill_version,
            "observation_builder_version": observation_builder_version,
            "analysis_tool_registry_version": analysis_tool_registry_version,
            "analysis_method_registry_version": analysis_method_registry_version,
            "kernel_version": kernel_version,
        }
        if prompt_content_digest is not None:
            expected_versions["prompt_content_digest"] = (
                prompt_content_digest
            )
        for row in rows:
            try:
                checkpoint = SequentialLoopCheckpoint.model_validate_json(
                    row["checkpoint_json"]
                )
            except (ValueError, TypeError):
                continue
            if all(
                getattr(checkpoint, field_name) == expected_value
                for field_name, expected_value in expected_versions.items()
            ):
                return ResumableSequentialAnalysis(
                    analysis_run_id=row["analysis_run_id"],
                    checkpoint=checkpoint,
                )
        return None

    def _get_session(self, session_id: int) -> SessionRecord:
        session = self._store.get_session(session_id)
        if session is None:
            raise ReportSessionNotFoundError(session_id)
        return session

    def _scope_json(self, scope: DataAccessScope) -> str:
        return json.dumps(
            scope.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )

    def _connect(self):
        conn = sqlite3.connect(self._store.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_analysis_table(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS report_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_run_id TEXT NOT NULL UNIQUE,
                    session_id INTEGER NOT NULL REFERENCES test_sessions(id),
                    status TEXT NOT NULL CHECK(status IN
                        ('running', 'validated', 'rejected', 'failed')),
                    data_access_scope_json TEXT NOT NULL,
                    package_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL DEFAULT '',
                    model_name TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    analysis_package_json TEXT,
                    run_metrics_json TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_analyses_session_status
                    ON report_analyses(session_id, status, id DESC);
                CREATE TABLE IF NOT EXISTS report_analysis_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_run_id TEXT NOT NULL
                        REFERENCES report_analyses(analysis_run_id),
                    checkpoint_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_report_checkpoints_run
                    ON report_analysis_checkpoints(analysis_run_id, id DESC);
                CREATE TABLE IF NOT EXISTS report_annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES test_sessions(id),
                    analysis_run_id TEXT NOT NULL REFERENCES report_analyses(analysis_run_id),
                    claim_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(analysis_run_id, claim_id, revision)
                );
                CREATE INDEX IF NOT EXISTS idx_report_annotations_session ON report_annotations(session_id, id DESC);
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(report_analyses)")
            }
            if "run_metrics_json" not in columns:
                conn.execute(
                    "ALTER TABLE report_analyses ADD COLUMN run_metrics_json TEXT"
                )
            if "request_digest" not in columns:
                conn.execute(
                    "ALTER TABLE report_analyses "
                    "ADD COLUMN request_digest TEXT NOT NULL DEFAULT ''"
                )
