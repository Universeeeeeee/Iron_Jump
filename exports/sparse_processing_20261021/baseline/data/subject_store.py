"""SQLite persistence for athlete/subject profiles and test sessions."""

from __future__ import annotations
from config.overground_running_report import OvergroundRunningReport

import json
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from config.test_config import AnyTestConfig, TestConfig, config_from_dict
from config.test_report import (
    GaitTestReport,
    JumpQualityNoticeRecord,
    JumpResultRecord,
    JumpTestReport,
    TestReport,
)
from config.treadmill_report import (
    GaitBoundaryPartial,
    GaitCycleRecord,
    GaitEventRecord,
    MetricSummary,
    TreadmillGaitReport,
    TreadmillRunningReport,
    TreadmillStepResult,
)
from path_utils import get_base_dir


LEVELS = {"beginner", "intermediate", "advanced"}
FOCUS_SIDES = {"", "left", "right", "both"}
FINISH_REASONS = {"jump_count_reached", "time_up", "manual", "error"}


@dataclass(frozen=True)
class SubjectProfile:
    id: int
    display_name: str
    sex: str
    birth_year: int
    height_cm: float | None = None
    weight_kg: float | None = None
    measured_foot_length_cm: float | None = None
    level: str = "intermediate"
    focus_side: str = ""
    notes: str = ""
    card_uid: str | None = None
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TeamProfile:
    id: int
    name: str
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class TeamMembership:
    subject_id: int
    team_id: int
    active: bool
    joined_at: str
    left_at: str | None = None


@dataclass(frozen=True)
class SubjectSearchResult:
    subject: SubjectProfile
    display_labels: dict[str, str]
    last_session_at: str | None = None
    team_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionRecord:
    id: int
    subject_id: int | None
    started_at: str
    finished_at: str | None
    test_type: str
    config_json: str
    height_cm: float | None = None
    weight_kg: float | None = None
    total_jumps: int | None = None
    finish_reason: str | None = None
    report_summary_json: str | None = None
    report_detail_json: str | None = None
    subject_snapshot_json: str | None = None
    config_source: str | None = None
    export_path: str | None = None
    team_id: int | None = None
    team_snapshot_json: str | None = None
    is_temporary: bool = False

    @property
    def config(self) -> AnyTestConfig:
        return config_from_dict(json.loads(self.config_json))

    @property
    def report_summary(self) -> dict[str, Any]:
        if not self.report_summary_json:
            return {}
        return json.loads(self.report_summary_json)

    @property
    def report_detail(self) -> dict[str, Any]:
        if not self.report_detail_json:
            return {}
        return json.loads(self.report_detail_json)

    @property
    def subject_snapshot(self) -> dict[str, Any]:
        if not self.subject_snapshot_json:
            return {}
        return json.loads(self.subject_snapshot_json)

    @property
    def team_snapshot(self) -> dict[str, Any]:
        if not self.team_snapshot_json:
            return {}
        return json.loads(self.team_snapshot_json)

    @property
    def report(self) -> TestReport:
        return _report_from_detail(self.report_detail)


def default_db_path() -> Path:
    return Path(get_base_dir()) / "data" / "iron_jump.sqlite3"


class SubjectStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_subject(
        self,
        display_name: str,
        birth_year: int,
        *,
        sex: str = "",
        height_cm: float | None = None,
        weight_kg: float | None = None,
        level: str = "intermediate",
        focus_side: str = "",
        notes: str = "",
        team_id: int | None = None,
    ) -> int:
        self._validate_subject_values(display_name, birth_year, level, focus_side)
        self._validate_measurements(height_cm, weight_kg)
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO subjects (
                    display_name, sex, birth_year, height_cm, weight_kg,
                    level, focus_side, notes, normalized_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    display_name.strip(),
                    sex,
                    birth_year,
                    height_cm,
                    weight_kg,
                    level,
                    focus_side,
                    notes,
                    _normalize_name(display_name),
                    now,
                    now,
                ),
            )
            subject_id = int(cur.lastrowid)
            if team_id is not None:
                self._add_subject_to_team(conn, subject_id, team_id)
            return subject_id

    def update_subject(self, subject_id: int, **fields: Any) -> None:
        if not fields:
            return
        with self._connect() as conn:
            self._update_subject_in_connection(conn, subject_id, fields)

    def update_subject_and_sync_teams(
        self, subject_id: int, *, team_ids: list[int], **fields: Any
    ) -> None:
        selected_team_ids = set(team_ids)
        with self._connect() as conn:
            self._update_subject_in_connection(conn, subject_id, fields)
            rows = conn.execute(
                """
                SELECT team_id FROM team_memberships
                WHERE subject_id = ? AND active = 1
                """,
                (subject_id,),
            ).fetchall()
            active_team_ids = {row["team_id"] for row in rows}
            for team_id in selected_team_ids - active_team_ids:
                self._add_subject_to_team(conn, subject_id, team_id)
            for team_id in active_team_ids - selected_team_ids:
                conn.execute(
                    """
                    UPDATE team_memberships
                    SET active = 0, left_at = ?
                    WHERE subject_id = ? AND team_id = ? AND active = 1
                    """,
                    (_now(), subject_id, team_id),
                )

    def restore_subject_and_add_to_team(
        self, subject_id: int, team_id: int | None = None
    ) -> None:
        with self._connect() as conn:
            subject = conn.execute(
                "SELECT id FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()
            if subject is None:
                raise KeyError(f"Subject not found: {subject_id}")
            if team_id is not None:
                self._add_subject_to_team(conn, subject_id, team_id)
            conn.execute(
                "UPDATE subjects SET archived = 0, updated_at = ? WHERE id = ?",
                (_now(), subject_id),
            )

    def _update_subject_in_connection(
        self, conn: sqlite3.Connection, subject_id: int, fields: dict[str, Any]
    ) -> None:
        allowed = {
            "display_name",
            "sex",
            "birth_year",
            "height_cm",
            "weight_kg",
            "level",
            "focus_side",
            "notes",
            "card_uid",
            "archived",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown subject fields: {', '.join(sorted(unknown))}")
        if not fields:
            return

        row = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Subject not found: {subject_id}")
        current = _subject_from_row(row)

        display_name = fields.get("display_name", current.display_name)
        birth_year = fields.get("birth_year", current.birth_year)
        level = fields.get("level", current.level)
        focus_side = fields.get("focus_side", current.focus_side)
        self._validate_subject_values(display_name, birth_year, level, focus_side)
        self._validate_measurements(
            fields.get("height_cm") if "height_cm" in fields else None,
            fields.get("weight_kg") if "weight_kg" in fields else None,
        )
        if "card_uid" in fields:
            fields = dict(fields)
            fields["card_uid"] = normalize_card_uid(fields["card_uid"])

        assignments = [f"{name} = ?" for name in fields]
        values = [_db_value(fields[name]) for name in fields]
        if "display_name" in fields:
            index = list(fields).index("display_name")
            values[index] = display_name.strip()
            assignments.append("normalized_name = ?")
            values.append(_normalize_name(display_name))
        assignments.append("updated_at = ?")
        values.append(_now())
        values.append(subject_id)

        conn.execute(
            f"UPDATE subjects SET {', '.join(assignments)} WHERE id = ?",
            values,
        )

    def create_team(self, name: str) -> int:
        display_name = name.strip()
        normalized_name = _normalize_name(name)
        if not normalized_name:
            raise ValueError("team name is required")

        now = _now()
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO teams (name, normalized_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (display_name, normalized_name, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Team already exists: {display_name}") from exc
            return int(cur.lastrowid)

    def search_teams(
        self, query: str = "", *, include_archived: bool = False
    ) -> list[TeamProfile]:
        sql = "SELECT * FROM teams"
        where: list[str] = []
        params: list[Any] = []
        normalized_query = _normalize_name(query)
        if normalized_query:
            where.append("normalized_name LIKE ?")
            params.append(f"%{normalized_query}%")
        if not include_archived:
            where.append("archived = 0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY normalized_name, id"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_team_from_row(row) for row in rows]

    def get_subject_teams(
        self, subject_id: int, *, active_only: bool = True
    ) -> list[TeamProfile]:
        sql = """
            SELECT t.*
            FROM teams t
            JOIN team_memberships tm ON tm.team_id = t.id
            WHERE tm.subject_id = ? AND t.archived = 0
        """
        params: list[Any] = [subject_id]
        if active_only:
            sql += " AND tm.active = 1"
        sql += " ORDER BY t.normalized_name, t.id"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_team_from_row(row) for row in rows]

    def add_subject_to_team(self, subject_id: int, team_id: int) -> None:
        with self._connect() as conn:
            self._add_subject_to_team(conn, subject_id, team_id)

    def remove_subject_from_team(self, subject_id: int, team_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE team_memberships
                SET active = 0, left_at = ?
                WHERE subject_id = ? AND team_id = ? AND active = 1
                """,
                (_now(), subject_id, team_id),
            )

    def archive_subject(self, subject_id: int) -> None:
        self.update_subject(subject_id, archived=True)

    def delete_subject_if_unused(self, subject_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM test_sessions WHERE subject_id = ?",
                (subject_id,),
            ).fetchone()
            if row["count"]:
                conn.execute(
                    "UPDATE subjects SET archived = 1, updated_at = ? WHERE id = ?",
                    (_now(), subject_id),
                )
                return False
            conn.execute(
                "DELETE FROM team_memberships WHERE subject_id = ?", (subject_id,)
            )
            cur = conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))
            return cur.rowcount > 0

    def search_subjects(
        self,
        query: str = "",
        *,
        include_archived: bool = False,
        team_id: int | None = None,
        without_team: bool = False,
    ) -> list[SubjectSearchResult]:
        if team_id is not None and without_team:
            raise ValueError("team_id and without_team cannot be used together")
        sql = """
            SELECT
                s.*,
                latest.last_session_at
            FROM subjects s
            LEFT JOIN (
                SELECT subject_id, MAX(started_at) AS last_session_at
                FROM test_sessions
                GROUP BY subject_id
            ) latest ON latest.subject_id = s.id
        """
        where: list[str] = []
        params: list[Any] = []

        if query.strip():
            where.append("s.display_name LIKE ?")
            params.append(f"%{query.strip()}%")
        if not include_archived:
            where.append("s.archived = 0")
        if team_id is not None:
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM team_memberships tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.subject_id = s.id AND tm.team_id = ?
                      AND tm.active = 1 AND t.archived = 0
                )
                """
            )
            params.append(team_id)
        elif without_team:
            where.append(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM team_memberships tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.subject_id = s.id AND tm.active = 1 AND t.archived = 0
                )
                """
            )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.updated_at DESC, s.id DESC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            team_names = self._active_team_names(conn, [row["id"] for row in rows])
        return [
            SubjectSearchResult(
                subject=_subject_from_row(row),
                display_labels=self._display_labels(row),
                last_session_at=row["last_session_at"],
                team_names=team_names.get(row["id"], ()),
            )
            for row in rows
        ]

    def find_duplicate_subjects(
        self, display_name: str, birth_year: int
    ) -> list[SubjectSearchResult]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.*,
                    latest.last_session_at
                FROM subjects s
                LEFT JOIN (
                    SELECT subject_id, MAX(started_at) AS last_session_at
                    FROM test_sessions
                    GROUP BY subject_id
                ) latest ON latest.subject_id = s.id
                WHERE s.normalized_name = ? AND s.birth_year = ?
                ORDER BY s.updated_at DESC, s.id DESC
                """,
                (_normalize_name(display_name), birth_year),
            ).fetchall()
            team_names = self._active_team_names(conn, [row["id"] for row in rows])
        return [
            SubjectSearchResult(
                subject=_subject_from_row(row),
                display_labels=self._display_labels(row),
                last_session_at=row["last_session_at"],
                team_names=team_names.get(row["id"], ()),
            )
            for row in rows
        ]

    def get_subject_by_card_uid(self, card_uid: str) -> SubjectProfile | None:
        normalized = normalize_card_uid(card_uid)
        if normalized is None:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subjects WHERE card_uid = ?",
                (normalized,),
            ).fetchone()
        return _subject_from_row(row) if row else None

    def bind_card_uid(self, subject_id: int, card_uid: str) -> None:
        normalized = normalize_card_uid(card_uid)
        if normalized is None:
            raise ValueError("card_uid is required")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, display_name FROM subjects WHERE card_uid = ?",
                (normalized,),
            ).fetchone()
            if existing is not None and int(existing["id"]) != int(subject_id):
                raise ValueError(
                    f"Card already bound to {existing['display_name']} (#{existing['id']})"
                )
            self._update_subject_in_connection(
                conn, subject_id, {"card_uid": normalized}
            )

    def unbind_card_uid(self, subject_id: int) -> None:
        with self._connect() as conn:
            self._update_subject_in_connection(conn, subject_id, {"card_uid": None})

    def get_subject(self, subject_id: int) -> SubjectProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()
        return _subject_from_row(row) if row else None

    def get_last_session(
        self, subject_id: int, test_type: str | None = None
    ) -> SessionRecord | None:
        sql = "SELECT * FROM test_sessions WHERE subject_id = ?"
        params: list[Any] = [subject_id]
        if test_type is not None:
            sql += " AND test_type = ?"
            params.append(test_type)
        sql += " ORDER BY started_at DESC, id DESC LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return _session_from_row(row) if row else None

    def get_session(self, session_id: int) -> SessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM test_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _session_from_row(row) if row else None

    def get_sessions(self, subject_id: int, *, limit: int = 50) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM test_sessions
                WHERE subject_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (subject_id, limit),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def get_all_sessions(self, *, limit: int = 200) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM test_sessions
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def get_team_sessions(self, team_id: int, *, limit: int = 200) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM test_sessions
                WHERE team_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (team_id, limit),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def count_subject_session_candidates(
        self,
        subject_id: int,
        test_type: str,
        *,
        exclude_session_id: int,
    ) -> int:
        """Count longitudinal candidates without loading report details."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM test_sessions
                WHERE subject_id = ? AND test_type = ? AND id != ?
                  AND report_detail_json IS NOT NULL
                  AND report_detail_json != ''
                """,
                (subject_id, test_type, exclude_session_id),
            ).fetchone()
        return int(row["count"])

    def count_team_session_candidates(
        self,
        team_id: int,
        test_type: str,
        *,
        exclude_session_id: int,
        exclude_subject_id: int | None = None,
    ) -> int:
        """Count cohort candidates without loading report details."""
        sql = """
            SELECT COUNT(*) AS count
            FROM test_sessions
            WHERE team_id = ? AND test_type = ? AND id != ?
              AND report_detail_json IS NOT NULL
              AND report_detail_json != ''
        """
        params: list[Any] = [team_id, test_type, exclude_session_id]
        if exclude_subject_id is not None:
            sql += " AND (subject_id IS NULL OR subject_id != ?)"
            params.append(exclude_subject_id)
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row["count"])

    def get_recent_history(
        self, subject_id: int, *, limit: int = 3
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM test_sessions
                WHERE subject_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (subject_id, limit),
            ).fetchall()
        return [_history_from_session(_session_from_row(row)) for row in reversed(rows)]

    def record_session(
        self,
        subject_id: int | None,
        config: AnyTestConfig,
        report: TestReport,
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        height_cm: float | None = None,
        weight_kg: float | None = None,
        subject_snapshot: dict[str, Any] | None = None,
        config_source: str | None = None,
        export_path: str | None = None,
        team_id: int | None = None,
        team_snapshot: dict[str, Any] | None = None,
    ) -> int:
        summary = _report_summary(report)
        finish_reason = _normalize_finish_reason(report.finish_reason)
        if isinstance(report, OvergroundRunningReport) and report.finish_reason not in FINISH_REASONS:
            # Legacy SQL CHECK has a small vocabulary; preserve the precise reason
            # in the report JSON without misclassifying automatic completion as error.
            finish_reason = None
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._validate_session_identity(
                conn, subject_id, team_id, team_snapshot
            )
            cur = conn.execute(
                """
                INSERT INTO test_sessions (
                    subject_id, started_at, finished_at, test_type, config_json,
                    height_cm, weight_kg, total_jumps, finish_reason,
                    report_summary_json, report_detail_json,
                    subject_snapshot_json, config_source, export_path,
                    team_id, team_snapshot_json, is_temporary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subject_id,
                    started_at or now,
                    finished_at or now,
                    config.test_type,
                    json.dumps(config.to_dict(), ensure_ascii=False),
                    height_cm,
                    weight_kg,
                    summary.get("total_jumps"),
                    finish_reason,
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(_report_detail(report), ensure_ascii=False),
                    json.dumps(subject_snapshot, ensure_ascii=False)
                    if subject_snapshot
                    else None,
                    config_source,
                    export_path,
                    team_id,
                    json.dumps(team_snapshot, ensure_ascii=False)
                    if team_snapshot is not None
                    else None,
                    int(subject_id is None),
                ),
            )
            return int(cur.lastrowid)

    @staticmethod
    def _validate_session_identity(
        conn: sqlite3.Connection,
        subject_id: int | None,
        team_id: int | None,
        team_snapshot: dict[str, Any] | None,
    ) -> None:
        if subject_id is None:
            if team_id is not None or team_snapshot is not None:
                raise ValueError("Temporary sessions cannot use a team identity")
            return

        subject = conn.execute(
            "SELECT archived FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if subject is None or subject["archived"]:
            raise ValueError("Subject is not available for testing")

        if team_id is None:
            if team_snapshot is not None:
                raise ValueError("Personal sessions cannot include a team snapshot")
            return

        if not isinstance(team_snapshot, dict) or team_snapshot.get("id") != team_id:
            raise ValueError("Team snapshot must identify the selected team")
        membership = conn.execute(
            """
            SELECT 1
            FROM team_memberships tm
            JOIN teams t ON t.id = tm.team_id
            WHERE tm.subject_id = ? AND tm.team_id = ?
              AND tm.active = 1 AND t.archived = 0
            """,
            (subject_id, team_id),
        ).fetchone()
        if membership is None:
            raise ValueError("Subject is not an active member of the selected team")

    def link_session_to_subject(self, session_id: int, subject_id: int) -> None:
        if self.get_subject(subject_id) is None:
            raise KeyError(f"Subject not found: {subject_id}")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE test_sessions SET subject_id = ? WHERE id = ?",
                (subject_id, session_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Session not found: {session_id}")

    def update_subject_measurements(
        self,
        subject_id: int,
        *,
        height_cm: float | None = None,
        weight_kg: float | None = None,
        measured_foot_length_cm: float | None = None,
    ) -> None:
        with self._connect() as conn:
            self._update_subject_measurements(
                conn, subject_id, height_cm, weight_kg, measured_foot_length_cm
            )

    def update_subject_from_session_profile(
        self,
        subject_id: int,
        *,
        height_cm: float | None,
        weight_kg: float | None,
        level: str,
        focus_side: str,
    ) -> None:
        self.update_subject(
            subject_id,
            height_cm=height_cm,
            weight_kg=weight_kg,
            level=level,
            focus_side=focus_side,
        )

    def subject_to_athlete_profile(
        self,
        subject: SubjectProfile,
        recent_sessions: list[dict[str, Any]] | None = None,
    ) -> AthleteProfile:
        from agent.models import AthleteProfile  # 延迟导入，避免拖入 pydantic 依赖
        history = (
            recent_sessions
            if recent_sessions is not None
            else self.get_recent_history(subject.id)
        )
        return AthleteProfile(
            age=max(0, datetime.now().year - subject.birth_year),
            weight=float(subject.weight_kg or 0.0),
            height=float(subject.height_cm or 0.0),
            level=subject.level,
            focus_side=subject.focus_side,
            history=history,
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL DEFAULT '',
                    sex TEXT NOT NULL DEFAULT '',
                    birth_year INTEGER NOT NULL,
                    height_cm REAL,
                    weight_kg REAL,
                    level TEXT NOT NULL DEFAULT 'intermediate'
                        CHECK(level IN ('beginner', 'intermediate', 'advanced')),
                    focus_side TEXT NOT NULL DEFAULT ''
                        CHECK(focus_side IN ('', 'left', 'right', 'both')),
                    notes TEXT NOT NULL DEFAULT '',
                    card_uid TEXT,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS test_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id INTEGER REFERENCES subjects(id),
                    started_at TEXT NOT NULL DEFAULT (datetime('now')),
                    finished_at TEXT,
                    test_type TEXT NOT NULL DEFAULT 'Jump Test',
                    config_json TEXT NOT NULL,
                    height_cm REAL,
                    weight_kg REAL,
                    total_jumps INTEGER,
                    finish_reason TEXT CHECK(finish_reason IN
                        ('jump_count_reached', 'time_up', 'manual', 'error')),
                    report_summary_json TEXT,
                    report_detail_json TEXT,
                    subject_snapshot_json TEXT,
                    config_source TEXT,
                    export_path TEXT,
                    team_id INTEGER REFERENCES teams(id),
                    team_snapshot_json TEXT,
                    is_temporary INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS team_memberships (
                    subject_id INTEGER NOT NULL REFERENCES subjects(id),
                    team_id INTEGER NOT NULL REFERENCES teams(id),
                    active INTEGER NOT NULL DEFAULT 1,
                    joined_at TEXT NOT NULL DEFAULT (datetime('now')),
                    left_at TEXT,
                    PRIMARY KEY (subject_id, team_id)
                );

                CREATE INDEX IF NOT EXISTS idx_subjects_name_archived
                    ON subjects(display_name, archived);
                CREATE INDEX IF NOT EXISTS idx_sessions_subject_started
                    ON test_sessions(subject_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_team_memberships_active
                    ON team_memberships(subject_id, active, team_id);

                CREATE TRIGGER IF NOT EXISTS validate_subject_measurements_insert
                BEFORE INSERT ON subjects
                FOR EACH ROW
                WHEN (
                    (NEW.height_cm IS NOT NULL AND
                        (NEW.height_cm <= 0 OR NEW.height_cm > 250))
                    OR
                    (NEW.weight_kg IS NOT NULL AND
                        (NEW.weight_kg <= 0 OR NEW.weight_kg > 300))
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid subject measurement');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_subject_measurements_update
                BEFORE UPDATE OF height_cm, weight_kg ON subjects
                FOR EACH ROW
                WHEN (
                    (NEW.height_cm IS NOT NULL AND
                        (NEW.height_cm <= 0 OR NEW.height_cm > 250))
                    OR
                    (NEW.weight_kg IS NOT NULL AND
                        (NEW.weight_kg <= 0 OR NEW.weight_kg > 300))
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid subject measurement');
                END;
                """
            )

            _ensure_column(
                conn,
                "subjects",
                "normalized_name",
                "normalized_name TEXT NOT NULL DEFAULT ''",
            )
            _ensure_column(
                conn, "subjects", "measured_foot_length_cm", "measured_foot_length_cm REAL"
            )
            _ensure_column(conn, "subjects", "card_uid", "card_uid TEXT")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_subjects_card_uid
                ON subjects(card_uid)
                WHERE card_uid IS NOT NULL AND card_uid != ''
                """
            )
            _ensure_column(
                conn, "test_sessions", "report_detail_json", "report_detail_json TEXT"
            )
            _ensure_column(
                conn,
                "test_sessions",
                "subject_snapshot_json",
                "subject_snapshot_json TEXT",
            )
            _ensure_column(
                conn, "test_sessions", "config_source", "config_source TEXT"
            )
            _ensure_column(
                conn, "test_sessions", "team_id", "team_id INTEGER REFERENCES teams(id)"
            )
            _ensure_column(
                conn, "test_sessions", "team_snapshot_json", "team_snapshot_json TEXT"
            )
            _ensure_column(
                conn,
                "test_sessions",
                "is_temporary",
                "is_temporary INTEGER NOT NULL DEFAULT 0",
            )
            self._backfill_normalized_subject_names(conn)
            _migrate_test_sessions_subject_nullable(conn)
            conn.execute(
                "UPDATE test_sessions SET is_temporary = 1 WHERE subject_id IS NULL"
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_subjects_normalized_birth_year
                ON subjects(normalized_name, birth_year)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_team_started
                ON test_sessions(team_id, started_at DESC)
                """
            )
            conn.execute("PRAGMA user_version = 1")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _display_labels(self, row: sqlite3.Row) -> dict[str, str]:
        labels = {
            "Age": str(max(0, datetime.now().year - int(row["birth_year"]))),
            "Level": row["level"],
        }
        if row["focus_side"]:
            labels["Focus"] = row["focus_side"]
        if row["last_session_at"]:
            labels["Last test"] = row["last_session_at"][:10]
        return labels

    @staticmethod
    def _active_team_names(
        conn: sqlite3.Connection, subject_ids: list[int]
    ) -> dict[int, tuple[str, ...]]:
        if not subject_ids:
            return {}
        placeholders = ", ".join("?" for _ in subject_ids)
        rows = conn.execute(
            f"""
            SELECT tm.subject_id, t.name
            FROM team_memberships tm
            JOIN teams t ON t.id = tm.team_id
            WHERE tm.subject_id IN ({placeholders})
                AND tm.active = 1 AND t.archived = 0
            ORDER BY tm.subject_id, t.normalized_name, t.id
            """,
            subject_ids,
        ).fetchall()
        team_names: dict[int, list[str]] = {}
        for row in rows:
            team_names.setdefault(row["subject_id"], []).append(row["name"])
        return {subject_id: tuple(names) for subject_id, names in team_names.items()}

    @staticmethod
    def _backfill_normalized_subject_names(conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT id, display_name FROM subjects").fetchall()
        conn.executemany(
            "UPDATE subjects SET normalized_name = ? WHERE id = ?",
            [(_normalize_name(row["display_name"]), row["id"]) for row in rows],
        )

    @staticmethod
    def _add_subject_to_team(
        conn: sqlite3.Connection, subject_id: int, team_id: int
    ) -> None:
        team = conn.execute(
            "SELECT archived FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if team is None or team["archived"]:
            raise KeyError(f"Active team not found: {team_id}")
        subject = conn.execute(
            "SELECT id FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if subject is None:
            raise KeyError(f"Subject not found: {subject_id}")
        now = _now()
        conn.execute(
            """
            INSERT INTO team_memberships (
                subject_id, team_id, active, joined_at, left_at
            ) VALUES (?, ?, 1, ?, NULL)
            ON CONFLICT(subject_id, team_id) DO UPDATE SET
                active = 1, joined_at = excluded.joined_at, left_at = NULL
            """,
            (subject_id, team_id, now),
        )

    def _update_subject_measurements(
        self,
        conn: sqlite3.Connection,
        subject_id: int,
        height_cm: float | None,
        weight_kg: float | None,
        measured_foot_length_cm: float | None = None,
    ) -> None:
        self._validate_measurements(height_cm, weight_kg)
        self._validate_measured_foot_length(measured_foot_length_cm)
        updates: dict[str, Any] = {}
        if height_cm is not None:
            updates["height_cm"] = height_cm
        if weight_kg is not None:
            updates["weight_kg"] = weight_kg
        if measured_foot_length_cm is not None:
            updates["measured_foot_length_cm"] = measured_foot_length_cm
        if updates:
            assignments = [f"{name} = ?" for name in updates]
            values = list(updates.values())
            assignments.append("updated_at = ?")
            values.append(_now())
            values.append(subject_id)
            conn.execute(
                f"UPDATE subjects SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    @staticmethod
    def _validate_subject_values(
        display_name: str, birth_year: int, level: str, focus_side: str
    ) -> None:
        if not display_name or not display_name.strip():
            raise ValueError("display_name is required")
        current_year = datetime.now().year
        if birth_year < 1900 or birth_year > current_year:
            raise ValueError("birth_year is out of range")
        if level not in LEVELS:
            raise ValueError(f"level must be one of {sorted(LEVELS)}")
        if focus_side not in FOCUS_SIDES:
            raise ValueError(f"focus_side must be one of {sorted(FOCUS_SIDES)}")

    @staticmethod
    def _validate_measurements(
        height_cm: float | None, weight_kg: float | None
    ) -> None:
        SubjectStore._validate_optional_measurement(height_cm, "height_cm", 250.0)
        SubjectStore._validate_optional_measurement(weight_kg, "weight_kg", 300.0)

    @staticmethod
    def _validate_measured_foot_length(value: float | None) -> None:
        SubjectStore._validate_optional_measurement(
            value, "measured_foot_length_cm", None
        )

    @staticmethod
    def _validate_optional_measurement(
        value: float | None, field_name: str, maximum: float | None
    ) -> None:
        if value is None:
            return
        try:
            is_valid = math.isfinite(value) and value > 0
        except TypeError as exc:
            raise ValueError(f"{field_name} must be a finite positive number") from exc
        if maximum is not None:
            is_valid = is_valid and value <= maximum
        if not is_valid:
            maximum_text = f" and no greater than {maximum:g}" if maximum else ""
            raise ValueError(
                f"{field_name} must be finite, positive{maximum_text}"
            )


def normalize_card_uid(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(
        ch for ch in str(value).strip().upper() if ch in "0123456789ABCDEF"
    )
    if len(cleaned) < 8:
        return None
    return cleaned


def _subject_from_row(row: sqlite3.Row) -> SubjectProfile:
    try:
        measured_foot_length_cm = row["measured_foot_length_cm"]
    except (IndexError, KeyError):
        measured_foot_length_cm = None
    card_uid = _optional_row_value(row, "card_uid")
    if card_uid == "":
        card_uid = None
    return SubjectProfile(
        id=int(row["id"]),
        display_name=row["display_name"],
        sex=row["sex"],
        birth_year=int(row["birth_year"]),
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        measured_foot_length_cm=measured_foot_length_cm,
        level=row["level"],
        focus_side=row["focus_side"],
        notes=row["notes"],
        card_uid=card_uid,
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    subject_id = row["subject_id"]
    finish_reason = row["finish_reason"]
    if row["test_type"] == "Overground Running Test":
        finish_reason = json.loads(row["report_summary_json"] or "{}").get("finish_reason", finish_reason)
    return SessionRecord(
        id=int(row["id"]),
        subject_id=int(subject_id) if subject_id is not None else None,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        test_type=row["test_type"],
        config_json=row["config_json"],
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        total_jumps=row["total_jumps"],
        finish_reason=finish_reason,
        report_summary_json=row["report_summary_json"],
        report_detail_json=_optional_row_value(row, "report_detail_json"),
        subject_snapshot_json=_optional_row_value(
            row, "subject_snapshot_json"
        ),
        config_source=_optional_row_value(row, "config_source"),
        export_path=row["export_path"],
        team_id=_optional_row_value(row, "team_id"),
        team_snapshot_json=_optional_row_value(row, "team_snapshot_json"),
        is_temporary=bool(_optional_row_value(row, "is_temporary")),
    )


def _team_from_row(row: sqlite3.Row) -> TeamProfile:
    return TeamProfile(
        id=int(row["id"]),
        name=row["name"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _history_from_session(session: SessionRecord) -> dict[str, Any]:
    config = session.config
    summary = session.report_summary
    # Extra fields are reserved for future report-analysis agents; the current
    # config agent only reads date/test_type/number_of_jumps/min_contact_time.
    return {
        "date": session.started_at[:10],
        "test_type": session.test_type,
        "number_of_jumps": getattr(config, "number_of_jumps", None),
        "min_contact_time": config.min_contact_time,
        "finish_reason": session.finish_reason,
        "total_jumps": session.total_jumps,
        "summary": summary,
    }


def _report_detail(report: TestReport) -> dict[str, Any]:
    from dataclasses import asdict as _asdict

    if isinstance(report, JumpTestReport):
        detail = _asdict(report)
        detail.pop("export_frames", None)
        detail.pop("export_timestamps", None)
        return {
            "report_type": "jump",
            "report_schema_version": 2,
            **detail,
        }
    if isinstance(report, OvergroundRunningReport):
        detail = _asdict(report)
        detail.pop("export_frames", None)
        detail.pop("export_timestamps", None)
        return {"report_type": "overground_running", "report_schema_version": 1, **detail}
    if isinstance(report, GaitTestReport):
        detail = _asdict(report)
        detail.pop("export_frames", None)
        detail.pop("export_timestamps", None)
        return {
            "report_type": "gait",
            "report_schema_version": 1,
            **detail,
        }

    if isinstance(report, TreadmillGaitReport):
        report_type = "treadmill_gait"
    else:
        report_type = "treadmill_running"

    return {
        "report_type": report_type,
        "report_schema_version": 3,
        "finish_reason": report.finish_reason,
        "touch_count": report.touch_count,
        "lift_count": report.lift_count,
        "resolved_starting_foot": report.resolved_starting_foot,
        "starting_foot_source": report.starting_foot_source,
        "foot_length_cm_snapshot": report.foot_length_cm_snapshot,
        "foot_length_source": report.foot_length_source,
        "per_step_results": [_asdict(r) for r in report.per_step_results],
        "metric_summaries": {k: _asdict(v) for k, v in report.metric_summaries.items()},
        "left_right_results": {k: _asdict(v) for k, v in report.left_right_results.items()},
        "asymmetry_metrics": report.asymmetry_metrics,
        "report_config_snapshot": report.report_config_snapshot,
        "visual_timeline": [
            frame.to_dict() if hasattr(frame, "to_dict") else frame
            for frame in report.visual_timeline
        ],
        "raw_gait_events": [_asdict(event) for event in report.raw_gait_events],
        "gait_cycles": [_asdict(cycle) for cycle in report.gait_cycles],
        "boundary_partials": [_asdict(partial) for partial in report.boundary_partials],
        "cycle_metric_summaries": {
            key: _asdict(value)
            for key, value in report.cycle_metric_summaries.items()
        },
        "cycle_side_summaries": {
            side: {key: _asdict(value) for key, value in summaries.items()}
            for side, summaries in report.cycle_side_summaries.items()
        },
        "cycle_asymmetry_percent": report.cycle_asymmetry_percent,
    }


def _report_from_detail(detail: dict[str, Any]) -> TestReport:
    if not detail:
        raise ValueError("Session does not contain a saved report")

    report_type = detail.get("report_type")
    values = {
        key: value
        for key, value in detail.items()
        if key not in {"report_type", "report_schema_version"}
    }

    if report_type == "jump":
        for key in (
            "air_times",
            "contact_times",
            "cycle_times",
            "jump_heights",
            "cadences",
        ):
            if key in values:
                values[key] = tuple(values[key])
        values["jump_results"] = tuple(
            JumpResultRecord(
                **{
                    **item,
                    "quality_flags": tuple(item.get("quality_flags", ())),
                }
            )
            for item in values.get("jump_results", ())
        )
        values["quality_notices"] = tuple(
            JumpQualityNoticeRecord(**item)
            for item in values.get("quality_notices", ())
        )
        if not values["jump_results"]:
            values["jump_results"] = _legacy_jump_results(values)
        return JumpTestReport(**values)

    if report_type == "overground_running":
        values["visual_timeline"] = tuple(values.get("visual_timeline", ()))
        return OvergroundRunningReport(**values)

    if report_type == "gait":
        for key in (
            "stride_lengths",
            "velocities",
            "foot_a_support_times",
            "foot_b_support_times",
            "visual_timeline",
        ):
            if key in values:
                values[key] = tuple(values[key])
        return GaitTestReport(**values)

    if report_type not in {"treadmill_gait", "treadmill_running"}:
        raise ValueError(f"Unsupported saved report type: {report_type}")

    values["per_step_results"] = tuple(
        TreadmillStepResult(
            **{
                **item,
                "quality_flags": tuple(item.get("quality_flags", ())),
            }
        )
        for item in values.get("per_step_results", ())
    )
    values["metric_summaries"] = _metric_summary_map(
        values.get("metric_summaries", {})
    )
    values["left_right_results"] = _metric_summary_map(
        values.get("left_right_results", {})
    )
    values["raw_gait_events"] = tuple(
        GaitEventRecord(**item)
        for item in values.get("raw_gait_events", ())
    )
    values["gait_cycles"] = tuple(
        GaitCycleRecord(
            **{
                **item,
                "quality_flags": tuple(item.get("quality_flags", ())),
            }
        )
        for item in values.get("gait_cycles", ())
    )
    values["boundary_partials"] = tuple(
        GaitBoundaryPartial(**item)
        for item in values.get("boundary_partials", ())
    )
    values["cycle_metric_summaries"] = _metric_summary_map(
        values.get("cycle_metric_summaries", {})
    )
    values["cycle_side_summaries"] = {
        side: _metric_summary_map(summaries)
        for side, summaries in values.get("cycle_side_summaries", {}).items()
    }
    values["visual_timeline"] = tuple(values.get("visual_timeline", ()))

    report_class = (
        TreadmillGaitReport
        if report_type == "treadmill_gait"
        else TreadmillRunningReport
    )
    return report_class(**values)


def _metric_summary_map(values: dict[str, Any]) -> dict[str, MetricSummary]:
    return {
        key: value if isinstance(value, MetricSummary) else MetricSummary(**value)
        for key, value in values.items()
    }


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, ddl: str
) -> bool:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        return True
    return False


def _migrate_test_sessions_subject_nullable(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]: row
        for row in conn.execute("PRAGMA table_info(test_sessions)")
    }
    subject_column = columns.get("subject_id")
    if subject_column is None or not subject_column["notnull"]:
        return

    conn.execute("DROP TABLE IF EXISTS test_sessions_nullable")
    conn.execute(
        """
        CREATE TABLE test_sessions_nullable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER REFERENCES subjects(id),
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            test_type TEXT NOT NULL DEFAULT 'Jump Test',
            config_json TEXT NOT NULL,
            height_cm REAL,
            weight_kg REAL,
            total_jumps INTEGER,
            finish_reason TEXT CHECK(finish_reason IN
                ('jump_count_reached', 'time_up', 'manual', 'error')),
            report_summary_json TEXT,
            report_detail_json TEXT,
            subject_snapshot_json TEXT,
            config_source TEXT,
            export_path TEXT,
            team_id INTEGER REFERENCES teams(id),
            team_snapshot_json TEXT,
            is_temporary INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO test_sessions_nullable (
            id, subject_id, started_at, finished_at, test_type, config_json,
            height_cm, weight_kg, total_jumps, finish_reason,
            report_summary_json, report_detail_json, subject_snapshot_json,
            config_source, export_path, team_id, team_snapshot_json, is_temporary
        )
        SELECT
            id, subject_id, started_at, finished_at, test_type, config_json,
            height_cm, weight_kg, total_jumps, finish_reason,
            report_summary_json, report_detail_json, subject_snapshot_json,
            config_source, export_path, team_id, team_snapshot_json, is_temporary
        FROM test_sessions
        """
    )
    conn.execute("DROP TABLE test_sessions")
    conn.execute(
        "ALTER TABLE test_sessions_nullable RENAME TO test_sessions"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_subject_started
        ON test_sessions(subject_id, started_at DESC)
        """
    )


def _optional_row_value(row: sqlite3.Row, key: str):
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _report_summary(report: TestReport) -> dict[str, Any]:
    base: dict[str, Any] = {
        "finish_reason": report.finish_reason,
        "touch_count": report.touch_count,
        "lift_count": report.lift_count,
    }
    if isinstance(report, JumpTestReport):
        base.update(
            {
                "report_type": "jump",
                "total_jumps": len(report.jump_heights),
                "avg_jump_height": report.avg_jump_height,
                "max_jump_height": report.max_jump_height,
                "min_jump_height": report.min_jump_height,
                "std_jump_height": report.std_jump_height,
                "avg_air_time": report.avg_air_time,
                "max_air_time": report.max_air_time,
                "min_air_time": report.min_air_time,
                "std_air_time": report.std_air_time,
                "avg_contact_time": report.avg_contact_time,
                "max_contact_time": report.max_contact_time,
                "min_contact_time": report.min_contact_time,
                "std_contact_time": report.std_contact_time,
                "avg_cadence": report.avg_cadence,
            }
        )
    elif isinstance(report, OvergroundRunningReport):
        base.update({"report_type": "overground_running",
                     "valid_steps": report.running_summary["valid_steps"],
                     "running_speed_m_s": report.running_summary["running_speed_m_s"]})
    elif isinstance(report, GaitTestReport):
        base.update(
            {
                "report_type": "gait",
                "avg_stride": report.avg_stride,
                "max_stride": report.max_stride,
                "avg_velocity": report.avg_velocity,
                "max_velocity": report.max_velocity,
                "imbalance_index": report.imbalance_index,
                "avg_double_support": report.avg_double_support,
                "avg_single_support": report.avg_single_support,
                "avg_acceleration": report.avg_acceleration,
            }
        )
    elif isinstance(report, TreadmillGaitReport):
        valid_cycles = [
            cycle for cycle in report.gait_cycles
            if cycle.is_included_in_statistics
        ]
        base.update(
            {
                "report_type": "treadmill_gait",
                "valid_step_count": sum(
                    1 for row in report.per_step_results if row.is_included_in_statistics
                ),
                "valid_cycle_count": len(valid_cycles),
                "left_valid_cycle_count": sum(
                    1 for cycle in valid_cycles if cycle.side == "left"
                ),
                "right_valid_cycle_count": sum(
                    1 for cycle in valid_cycles if cycle.side == "right"
                ),
            }
        )
    elif isinstance(report, TreadmillRunningReport):
        valid_cycles = [
            cycle for cycle in report.gait_cycles
            if cycle.is_included_in_statistics
        ]
        base.update(
            {
                "report_type": "treadmill_running",
                "valid_step_count": sum(
                    1 for row in report.per_step_results if row.is_included_in_statistics
                ),
                "valid_cycle_count": len(valid_cycles),
                "left_valid_cycle_count": sum(
                    1 for cycle in valid_cycles if cycle.side == "left"
                ),
                "right_valid_cycle_count": sum(
                    1 for cycle in valid_cycles if cycle.side == "right"
                ),
            }
        )
    return base


def _legacy_jump_results(values: dict[str, Any]) -> tuple[JumpResultRecord, ...]:
    """Reconstruct physical jump rows for schema-v1 reports."""
    air = tuple(values.get("air_times", ()))
    heights = tuple(values.get("jump_heights", ()))
    contacts = tuple(values.get("contact_times", ()))
    cycles = tuple(values.get("cycle_times", ()))
    cadences = tuple(values.get("cadences", ()))
    count = max(
        len(air),
        len(heights),
        len(contacts) + (1 if contacts else 0),
        len(cycles) + (1 if cycles else 0),
        len(cadences) + (1 if cadences else 0),
        0,
    )
    records = []
    for index in range(count):
        offset = index - 1
        air_time = air[index] if index < len(air) else None
        cycle_time = cycles[offset] if 0 <= offset < len(cycles) else None
        cadence = cadences[offset] if 0 <= offset < len(cadences) else None
        records.append(
            JumpResultRecord(
                index=index + 1,
                lift_time_s=None,
                touch_time_s=None,
                air_time_s=air_time,
                jump_height_m=heights[index] if index < len(heights) else None,
                contact_time_s=(
                    contacts[offset] if 0 <= offset < len(contacts) else None
                ),
                cycle_time_s=cycle_time,
                cadence_jumps_per_min=cadence,
                is_included_in_statistics=air_time is not None,
            )
        )
    return tuple(records)


def _normalize_finish_reason(reason: str) -> str:
    return reason if reason in FINISH_REASONS else "error"


def _normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _db_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    return value
