"""Tests for the SQLite subject store MVP."""

import json
import sys
import sqlite3
import tempfile
import unittest
from dataclasses import fields
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.models import AthleteProfile
from config.test_config import TestConfig as _TestConfig
from config.test_report import (
    JumpQualityNoticeRecord,
    JumpResultRecord,
    JumpTestReport,
)
from config.treadmill_config import TreadmillGaitConfig
from config.treadmill_report import (
    GaitBoundaryPartial,
    GaitCycleRecord,
    GaitEventRecord,
    TreadmillGaitReport,
    TreadmillStepResult,
    summarize,
)
from data.subject_store import SubjectProfile, SubjectStore


def _jump_report(**overrides):
    values = {
        "touch_count": 5,
        "lift_count": 5,
        "air_times": (0.4, 0.42),
        "contact_times": (0.2, 0.21),
        "cycle_times": (0.6, 0.63),
        "avg_jump_height": 0.2,
        "max_jump_height": 0.22,
        "avg_air_time": 0.41,
        "max_air_time": 0.42,
        "avg_contact_time": 0.205,
        "avg_cadence": 95.0,
        "finish_reason": "jump_count_reached",
        "jump_heights": (0.18, 0.22),
        "cadences": (92.0, 98.0),
        "min_jump_height": 0.18,
        "std_jump_height": 0.02,
        "min_air_time": 0.4,
        "std_air_time": 0.01,
        "min_contact_time": 0.2,
        "max_contact_time": 0.21,
        "std_contact_time": 0.005,
        "export_frames": ([1, 0, 1],),
        "export_timestamps": (1.0,),
    }
    values.update(overrides)
    return JumpTestReport(**values)


class SubjectStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "iron_jump.sqlite3"
        self.store = SubjectStore(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_schema_uses_level_and_focus_side_only(self):
        with self.store._connect() as conn:
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(subjects)").fetchall()
            }
        self.assertIn("level", cols)
        self.assertIn("focus_side", cols)
        self.assertNotIn("condition", cols)
        self.assertNotIn("affected_side", cols)

        profile_fields = {field.name for field in fields(SubjectProfile)}
        self.assertIn("level", profile_fields)
        self.assertIn("focus_side", profile_fields)
        self.assertNotIn("condition", profile_fields)
        self.assertNotIn("affected_side", profile_fields)

    def test_create_subject_defaults_level_to_intermediate(self):
        subject_id = self.store.create_subject("Alice", 1990)
        subject = self.store.get_subject(subject_id)
        self.assertIsNotNone(subject)
        self.assertEqual(subject.level, "intermediate")
        self.assertEqual(subject.focus_side, "")

    def test_search_subjects_returns_display_labels(self):
        subject_id = self.store.create_subject(
            "Alice", 1990, level="beginner", focus_side="left"
        )
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=5),
            _jump_report(),
            started_at="2026-05-14 10:00:00",
        )

        results = self.store.search_subjects("Ali")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].subject.id, subject_id)
        self.assertEqual(results[0].display_labels["Level"], "beginner")
        self.assertEqual(results[0].display_labels["Focus"], "left")
        self.assertEqual(results[0].display_labels["Last test"], "2026-05-14")

    def test_subject_to_athlete_profile_uses_new_fields(self):
        subject_id = self.store.create_subject(
            "Bob",
            2000,
            height_cm=180,
            weight_kg=75,
            level="advanced",
            focus_side="right",
        )
        subject = self.store.get_subject(subject_id)
        profile = self.store.subject_to_athlete_profile(subject, recent_sessions=[])

        self.assertIsInstance(profile, AthleteProfile)
        self.assertEqual(profile.age, datetime.now().year - 2000)
        self.assertEqual(profile.height, 180)
        self.assertEqual(profile.weight, 75)
        self.assertEqual(profile.level, "advanced")
        self.assertEqual(profile.focus_side, "right")

    def test_record_session_round_trips_config_and_summary(self):
        subject_id = self.store.create_subject("Carol", 1995)
        config = _TestConfig(number_of_jumps=7, min_contact_time=80)
        report = _jump_report(touch_count=7)

        session_id = self.store.record_session(
            subject_id,
            config,
            report,
            height_cm=168,
            weight_kg=60,
        )
        session = self.store.get_last_session(subject_id)

        self.assertEqual(session.id, session_id)
        self.assertEqual(session.config.number_of_jumps, 7)
        self.assertEqual(session.config.min_contact_time, 80)
        self.assertEqual(session.total_jumps, 2)
        self.assertEqual(session.report_summary["total_jumps"], 2)
        self.assertEqual(session.report_summary["min_jump_height"], report.min_jump_height)
        self.assertEqual(session.report_summary["std_jump_height"], report.std_jump_height)
        self.assertEqual(session.report_summary["min_air_time"], report.min_air_time)
        self.assertEqual(session.report_summary["std_air_time"], report.std_air_time)
        self.assertEqual(session.report_summary["min_contact_time"], report.min_contact_time)
        self.assertEqual(session.report_summary["max_contact_time"], report.max_contact_time)
        self.assertEqual(session.report_summary["std_contact_time"], report.std_contact_time)
        self.assertNotIn("jump_heights", session.report_summary)
        self.assertNotIn("cadences", session.report_summary)
        self.assertNotIn("export_frames", session.report_summary)
        self.assertNotIn("export_timestamps", session.report_summary)

        self.assertEqual(session.height_cm, 168)
        self.assertEqual(session.weight_kg, 60)
        subject = self.store.get_subject(subject_id)
        self.assertIsNone(subject.height_cm)
        self.assertIsNone(subject.weight_kg)

    def test_record_session_does_not_update_subject_measurements(self):
        subject_id = self.store.create_subject(
            "Alice", 1990, height_cm=170.0, weight_kg=60.0
        )

        self.store.record_session(
            subject_id,
            _TestConfig(),
            _jump_report(),
            height_cm=180.0,
            weight_kg=70.0,
            subject_snapshot={"height_cm": 180.0, "weight_kg": 70.0},
        )

        subject = self.store.get_subject(subject_id)
        self.assertEqual(subject.height_cm, 170.0)
        self.assertEqual(subject.weight_kg, 60.0)

    def test_update_subject_from_session_profile_updates_only_safe_profile_fields(self):
        subject_id = self.store.create_subject(
            "Alice",
            1990,
            height_cm=170.0,
            weight_kg=60.0,
            level="beginner",
            focus_side="left",
        )

        self.store.update_subject_from_session_profile(
            subject_id,
            height_cm=180.0,
            weight_kg=70.0,
            level="advanced",
            focus_side="right",
        )

        subject = self.store.get_subject(subject_id)
        self.assertEqual(subject.display_name, "Alice")
        self.assertEqual(subject.birth_year, 1990)
        self.assertEqual(subject.height_cm, 180.0)
        self.assertEqual(subject.weight_kg, 70.0)
        self.assertEqual(subject.level, "advanced")
        self.assertEqual(subject.focus_side, "right")

    def test_subject_measurements_require_finite_in_range_values(self):
        invalid_cases = (
            (-1.0, None),
            (float("nan"), None),
            (float("inf"), None),
            (251.0, None),
            (None, -1.0),
            (None, 301.0),
        )
        subject_id = self.store.create_subject("Alice", 1990)

        for height_cm, weight_kg in invalid_cases:
            with self.subTest(height_cm=height_cm, weight_kg=weight_kg):
                with self.assertRaises(ValueError):
                    self.store.create_subject(
                        "Invalid", 1990, height_cm=height_cm, weight_kg=weight_kg
                    )
                with self.assertRaises(ValueError):
                    self.store.update_subject(
                        subject_id, height_cm=height_cm, weight_kg=weight_kg
                    )
                with self.assertRaises(ValueError):
                    self.store.update_subject_measurements(
                        subject_id, height_cm=height_cm, weight_kg=weight_kg
                    )

        nullable_subject_id = self.store.create_subject(
            "Nullable", 1990, height_cm=None, weight_kg=None
        )
        self.store.update_subject(
            nullable_subject_id, height_cm=None, weight_kg=None
        )

    def test_measured_foot_length_requires_a_finite_positive_value(self):
        subject_id = self.store.create_subject("Alice", 1990)

        for foot_length_cm in (-1.0, 0.0, float("nan"), float("inf")):
            with self.subTest(foot_length_cm=foot_length_cm):
                with self.assertRaises(ValueError):
                    self.store.update_subject_measurements(
                        subject_id, measured_foot_length_cm=foot_length_cm
                    )

    def test_sqlite_guards_reject_invalid_subject_measurements(self):
        subject_id = self.store.create_subject("Alice", 1990)

        with self.store._connect() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO subjects (display_name, normalized_name, birth_year, height_cm)
                    VALUES ('Invalid', 'invalid', 1990, -1.0)
                    """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE subjects SET weight_kg = 301.0 WHERE id = ?",
                    (subject_id,),
                )

    def test_recent_history_uses_agent_expected_keys(self):
        subject_id = self.store.create_subject("Dana", 1998)
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=4, min_contact_time=90),
            _jump_report(touch_count=4),
            started_at="2026-05-14 11:00:00",
        )

        history = self.store.get_recent_history(subject_id)
        self.assertEqual(history[0]["date"], "2026-05-14")
        self.assertEqual(history[0]["test_type"], "Jump Test")
        self.assertEqual(history[0]["number_of_jumps"], 4)
        self.assertEqual(history[0]["min_contact_time"], 90)
        self.assertNotIn("condition", history[0])
        self.assertNotIn("affected_side", history[0])

    def test_get_sessions_filters_by_subject_and_returns_newest_first(self):
        subject_id = self.store.create_subject("Eve", 1992)
        other_id = self.store.create_subject("Frank", 1991)
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            started_at="2026-05-14 09:00:00",
        )
        latest_id = self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=6),
            _jump_report(touch_count=6, finish_reason="manual"),
            started_at="2026-05-14 11:00:00",
        )
        self.store.record_session(
            other_id,
            _TestConfig(number_of_jumps=9),
            _jump_report(touch_count=9),
            started_at="2026-05-14 12:00:00",
        )

        sessions = self.store.get_sessions(subject_id, limit=1)

        self.assertEqual([session.id for session in sessions], [latest_id])
        self.assertEqual(sessions[0].config.number_of_jumps, 6)
        self.assertEqual(sessions[0].report_summary["finish_reason"], "manual")

    def test_delete_unused_subject_but_archive_used_subject(self):
        unused_id = self.store.create_subject("Unused", 1980)
        self.assertTrue(self.store.delete_subject_if_unused(unused_id))
        self.assertIsNone(self.store.get_subject(unused_id))

        used_id = self.store.create_subject("Used", 1985)
        self.store.record_session(used_id, _TestConfig(), _jump_report())
        self.assertFalse(self.store.delete_subject_if_unused(used_id))
        self.assertTrue(self.store.get_subject(used_id).archived)
        self.assertEqual(self.store.search_subjects("Used"), [])
        self.assertEqual(len(self.store.search_subjects("Used", include_archived=True)), 1)

    def test_delete_unused_subject_removes_team_memberships(self):
        subject_id = self.store.create_subject("Unused", 1980)
        team_id = self.store.create_team("Alpha")
        self.store.add_subject_to_team(subject_id, team_id)

        self.assertTrue(self.store.delete_subject_if_unused(subject_id))
        self.assertIsNone(self.store.get_subject(subject_id))
        with self.store._connect() as conn:
            membership = conn.execute(
                "SELECT * FROM team_memberships WHERE subject_id = ?", (subject_id,)
            ).fetchone()
        self.assertIsNone(membership)

    def test_reusing_archived_subject_restores_it_and_adds_target_team(self):
        alpha_id = self.store.create_team("Alpha")
        beta_id = self.store.create_team("Beta")
        subject_id = self.store.create_subject("Alice", 1990, team_id=alpha_id)
        self.store.archive_subject(subject_id)

        candidate = self.store.find_duplicate_subjects("Alice", 1990)[0]
        self.store.restore_subject_and_add_to_team(candidate.subject.id, beta_id)

        visible = self.store.search_subjects("Alice")
        self.assertEqual([item.subject.id for item in visible], [subject_id])
        self.assertFalse(visible[0].subject.archived)
        self.assertEqual(
            [team.name for team in self.store.get_subject_teams(subject_id)],
            ["Alpha", "Beta"],
        )

    def test_subject_edit_and_team_sync_roll_back_together_on_invalid_team(self):
        alpha_id = self.store.create_team("Alpha")
        beta_id = self.store.create_team("Beta")
        subject_id = self.store.create_subject("Alice", 1990, team_id=alpha_id)

        with self.assertRaises(KeyError):
            self.store.update_subject_and_sync_teams(
                subject_id,
                team_ids=[beta_id, 999],
                display_name="Changed Alice",
            )

        subject = self.store.get_subject(subject_id)
        self.assertEqual(subject.display_name, "Alice")
        self.assertEqual(
            [team.name for team in self.store.get_subject_teams(subject_id)], ["Alpha"]
        )


    def test_subject_store_persists_measured_foot_length_and_treadmill_detail(self):
        subject_id = self.store.create_subject(
            display_name="Runner",
            sex="",
            birth_year=1990,
            height_cm=175.0,
            weight_kg=70.0,
            level="intermediate",
            focus_side="",
            notes="",
        )
        self.store.update_subject_measurements(
            subject_id,
            height_cm=175.0,
            weight_kg=70.0,
            measured_foot_length_cm=26.5,
        )
        config = TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
            foot_length_cm_snapshot=26.5,
            foot_length_source="manual",
        )

        report = TreadmillGaitReport(
            finish_reason="manual",
            touch_count=0,
            lift_count=0,
            resolved_starting_foot="unknown",
            starting_foot_source="unknown",
            per_step_results=(
                TreadmillStepResult(
                    index=0,
                    side="left",
                    row_status="valid",
                    is_event_valid=True,
                    is_included_in_statistics=True,
                    correction_source="none",
                    gap_between_feet_cm=8.5,
                    quality_flags=("gap_below_minimum",),
                ),
            ),
            metric_summaries={"contact_time_s": summarize(())},
            report_config_snapshot=config.to_dict(),
            raw_gait_events=(GaitEventRecord(0, 0.0, "left", "touch"),),
            gait_cycles=(
                GaitCycleRecord(
                    index=0,
                    side="left",
                    start_time_s=0.0,
                    end_time_s=1.0,
                    gait_cycle_s=1.0,
                    stance_phase_s=0.6,
                    stance_phase_percent=60.0,
                    swing_phase_s=0.4,
                    swing_phase_percent=40.0,
                    step_time_s=0.5,
                    single_support_s=0.4,
                    single_support_percent=40.0,
                    total_double_support_s=0.2,
                    total_double_support_percent=20.0,
                    load_response_s=0.1,
                    load_response_percent=10.0,
                    pre_swing_s=0.1,
                    pre_swing_percent=10.0,
                    total_flight_time_s=0.0,
                    statistics_exclusion_reason=(
                        "Contact time below minimum threshold"
                    ),
                    quality_flags=("running_overlap_above_tolerance",),
                ),
            ),
            boundary_partials=(
                GaitBoundaryPartial("right", 0.5, 1.2, 0.7, "摆动相"),
            ),
            cycle_metric_summaries={"gait_cycle_s": summarize((1.0,))},
            cycle_side_summaries={
                "left": {"gait_cycle_s": summarize((1.0,))},
                "right": {"gait_cycle_s": summarize(())},
            },
        )

        session_id = self.store.record_session(
            subject_id,
            config=config,
            report=report,
        )
        session = self.store.get_session(session_id)

        self.assertEqual(session.report_summary["report_type"], "treadmill_gait")
        self.assertEqual(session.report_summary["valid_cycle_count"], 1)
        self.assertEqual(session.report_detail["report_schema_version"], 3)
        self.assertEqual(session.report_detail["report_config_snapshot"]["treadmill_speed"], 5.0)
        self.assertEqual(session.report_detail["raw_gait_events"][0]["side"], "left")
        self.assertEqual(session.report_detail["gait_cycles"][0]["gait_cycle_s"], 1.0)
        self.assertEqual(
            session.report_detail["gait_cycles"][0]["statistics_exclusion_reason"],
            "Contact time below minimum threshold",
        )
        self.assertEqual(
            session.report_detail["gait_cycles"][0]["quality_flags"],
            ["running_overlap_above_tolerance"],
        )
        self.assertEqual(
            session.report_detail["per_step_results"][0]["gap_between_feet_cm"],
            8.5,
        )
        self.assertEqual(
            session.report_detail["per_step_results"][0]["quality_flags"],
            ["gap_below_minimum"],
        )
        self.assertEqual(session.report_detail["boundary_partials"][0]["phase"], "摆动相")

    def test_temporary_session_can_be_saved_and_linked_later(self):
        snapshot = {
            "display_name": "临时测试",
            "age": 30,
            "height_cm": 170.0,
            "weight_kg": 70.0,
            "level": "intermediate",
            "focus_side": "",
        }
        session_id = self.store.record_session(
            None,
            _TestConfig(number_of_jumps=5),
            _jump_report(),
            subject_snapshot=snapshot,
            config_source="manual",
        )

        session = self.store.get_session(session_id)
        self.assertIsNone(session.subject_id)
        self.assertEqual(session.subject_snapshot, snapshot)
        self.assertEqual(session.config_source, "manual")
        self.assertEqual(self.store.get_all_sessions()[0].id, session_id)

        subject_id = self.store.create_subject("Later Linked", 1990)
        self.store.link_session_to_subject(session_id, subject_id)
        linked = self.store.get_session(session_id)

        self.assertEqual(linked.subject_id, subject_id)
        self.assertEqual(linked.subject_snapshot, snapshot)
        self.assertIsNone(linked.team_id)
        self.assertEqual(linked.team_snapshot, {})

    def test_record_session_rejects_archived_subject_but_allows_temporary(self):
        subject_id = self.store.create_subject("Alice", 1990)
        alpha_id = self.store.create_team("Alpha")
        self.store.add_subject_to_team(subject_id, alpha_id)
        self.store.archive_subject(subject_id)

        with self.assertRaises(ValueError):
            self.store.record_session(999, _TestConfig(), _jump_report())
        with self.assertRaises(ValueError):
            self.store.record_session(subject_id, _TestConfig(), _jump_report())
        with self.assertRaises(ValueError):
            self.store.record_session(
                subject_id,
                _TestConfig(),
                _jump_report(),
                team_id=alpha_id,
                team_snapshot={"id": alpha_id, "name": "Alpha"},
            )

        temporary_id = self.store.record_session(
            None, _TestConfig(), _jump_report()
        )
        self.assertTrue(self.store.get_session(temporary_id).is_temporary)

    def test_record_session_starts_write_transaction_before_identity_validation(self):
        subject_id = self.store.create_subject("Alice", 1990)
        observed_transaction_states = []
        original = self.store._validate_session_identity

        def probe(conn, *args, **kwargs):
            observed_transaction_states.append(conn.in_transaction)
            return original(conn, *args, **kwargs)

        self.store._validate_session_identity = probe
        self.store.record_session(subject_id, _TestConfig(), _jump_report())

        self.assertEqual(observed_transaction_states, [True])

    def test_team_session_requires_an_active_membership_and_saved_snapshot(self):
        subject_id = self.store.create_subject("Alice", 1990)
        alpha_id = self.store.create_team("Alpha")
        beta_id = self.store.create_team("Beta")
        self.store.add_subject_to_team(subject_id, alpha_id)

        personal_id = self.store.record_session(
            subject_id, _TestConfig(), _jump_report()
        )
        team_id = self.store.record_session(
            subject_id,
            _TestConfig(),
            _jump_report(),
            team_id=alpha_id,
            team_snapshot={"id": alpha_id, "name": "Alpha"},
        )

        self.assertIsNone(self.store.get_session(personal_id).team_id)
        session = self.store.get_session(team_id)
        self.assertEqual(session.team_id, alpha_id)
        self.assertEqual(session.team_snapshot, {"id": alpha_id, "name": "Alpha"})

        with self.assertRaises(ValueError):
            self.store.record_session(
                subject_id,
                _TestConfig(),
                _jump_report(),
                team_snapshot={"id": alpha_id, "name": "Alpha"},
            )
        with self.assertRaises(ValueError):
            self.store.record_session(
                subject_id,
                _TestConfig(),
                _jump_report(),
                team_id=beta_id,
                team_snapshot={"id": beta_id, "name": "Beta"},
            )
        with self.assertRaises(ValueError):
            self.store.record_session(
                subject_id,
                _TestConfig(),
                _jump_report(),
                team_id=alpha_id,
                team_snapshot={"id": beta_id, "name": "Beta"},
            )
        with self.assertRaises(ValueError):
            self.store.record_session(
                None,
                _TestConfig(),
                _jump_report(),
                team_id=alpha_id,
                team_snapshot={"id": alpha_id, "name": "Alpha"},
            )

        self.store.remove_subject_from_team(subject_id, alpha_id)
        with self.assertRaises(ValueError):
            self.store.record_session(
                subject_id,
                _TestConfig(),
                _jump_report(),
                team_id=alpha_id,
                team_snapshot={"id": alpha_id, "name": "Alpha"},
            )

        self.store.add_subject_to_team(subject_id, alpha_id)
        with self.store._connect() as conn:
            conn.execute("UPDATE teams SET archived = 1 WHERE id = ?", (alpha_id,))
        with self.assertRaises(ValueError):
            self.store.record_session(
                subject_id,
                _TestConfig(),
                _jump_report(),
                team_id=alpha_id,
                team_snapshot={"id": alpha_id, "name": "Alpha"},
            )

    def test_team_history_queries_the_same_session_rows_and_keeps_snapshot(self):
        subject_id = self.store.create_subject("Alice", 1990)
        alpha_id = self.store.create_team("Alpha")
        self.store.add_subject_to_team(subject_id, alpha_id)
        team_session_id = self.store.record_session(
            subject_id,
            _TestConfig(),
            _jump_report(),
            team_id=alpha_id,
            team_snapshot={"id": alpha_id, "name": "Alpha"},
        )
        self.store.record_session(subject_id, _TestConfig(), _jump_report())

        self.assertEqual(len(self.store.get_sessions(subject_id)), 2)
        self.assertEqual(
            [session.id for session in self.store.get_team_sessions(alpha_id)],
            [team_session_id],
        )
        self.assertEqual(len(self.store.get_all_sessions()), 2)

        with self.store._connect() as conn:
            conn.execute(
                "UPDATE teams SET name = ?, archived = 1 WHERE id = ?",
                ("Renamed Alpha", alpha_id),
            )
        self.assertEqual(
            self.store.get_session(team_session_id).team_snapshot["name"], "Alpha"
        )

    def test_alpha_beta_membership_keeps_team_and_personal_history_separate(self):
        subject_id = self.store.create_subject("Alice", 1990)
        alpha_id = self.store.create_team("Alpha")
        beta_id = self.store.create_team("Beta")
        self.store.add_subject_to_team(subject_id, alpha_id)
        self.store.add_subject_to_team(subject_id, beta_id)

        alpha_session_id = self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            team_id=alpha_id,
            team_snapshot={"id": alpha_id, "name": "Alpha"},
        )
        personal_session_id = self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=6),
            _jump_report(touch_count=6),
        )

        self.assertEqual(
            [session.id for session in self.store.get_sessions(subject_id)],
            [personal_session_id, alpha_session_id],
        )
        self.assertEqual(
            [session.id for session in self.store.get_team_sessions(alpha_id)],
            [alpha_session_id],
        )
        self.assertEqual(self.store.get_team_sessions(beta_id), [])
        self.assertEqual(
            {session.id for session in self.store.get_all_sessions()},
            {alpha_session_id, personal_session_id},
        )

        with self.store._connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0], 1
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM team_memberships WHERE active = 1"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM test_sessions").fetchone()[0], 2
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM test_sessions WHERE team_id = ?",
                    (alpha_id,),
                ).fetchone()[0],
                1,
            )

    def test_session_reconstructs_saved_jump_and_treadmill_reports(self):
        jump_record = JumpResultRecord(
            index=1,
            lift_time_s=0.1,
            touch_time_s=0.5,
            air_time_s=0.4,
            jump_height_m=0.1962,
            contact_time_s=None,
            cycle_time_s=None,
            cadence_jumps_per_min=None,
            is_included_in_statistics=True,
            quality_flags=("flight_time_above_review_threshold",),
        )
        jump_notice = JumpQualityNoticeRecord(
            kind="contact_cluster_above_limit",
            time_s=0.7,
            cluster_length=51,
            ratio=51 / 96,
        )
        jump_id = self.store.record_session(
            None,
            _TestConfig(number_of_jumps=5),
            _jump_report(
                jump_results=(jump_record,),
                quality_notices=(jump_notice,),
                report_config_snapshot={"touch_max_cluster_length": 50},
            ),
        )
        jump_session = self.store.get_session(jump_id)
        jump = jump_session.report

        self.assertIsInstance(jump, JumpTestReport)
        self.assertEqual(jump.jump_heights, (0.18, 0.22))
        self.assertEqual(jump_session.report_detail["report_schema_version"], 2)
        self.assertEqual(jump.jump_results[0].quality_flags, jump_record.quality_flags)
        self.assertEqual(jump.quality_notices[0].cluster_length, 51)
        self.assertEqual(jump.report_config_snapshot["touch_max_cluster_length"], 50)

        treadmill = TreadmillGaitReport(
            finish_reason="manual",
            touch_count=1,
            lift_count=1,
            resolved_starting_foot="left",
            starting_foot_source="auto_first_contact",
            per_step_results=(
                TreadmillStepResult(
                    index=0,
                    side="left",
                    row_status="valid",
                    is_event_valid=True,
                    is_included_in_statistics=True,
                    correction_source="none",
                    quality_flags=("reviewed",),
                ),
            ),
            metric_summaries={"contact_time_s": summarize((0.2,))},
            gait_cycles=(
                GaitCycleRecord(
                    index=0,
                    side="left",
                    start_time_s=0.0,
                    end_time_s=1.0,
                    gait_cycle_s=1.0,
                    stance_phase_s=0.6,
                    stance_phase_percent=60.0,
                    swing_phase_s=0.4,
                    swing_phase_percent=40.0,
                    step_time_s=0.5,
                    single_support_s=0.4,
                    single_support_percent=40.0,
                    total_double_support_s=0.2,
                    total_double_support_percent=20.0,
                    load_response_s=0.1,
                    load_response_percent=10.0,
                    pre_swing_s=0.1,
                    pre_swing_percent=10.0,
                    total_flight_time_s=0.0,
                    stride_length_cm=103.5,
                ),
            ),
        )
        treadmill_id = self.store.record_session(
            None,
            TreadmillGaitConfig(
                stop_type="Software command",
                test_length=None,
                treadmill_speed=5.0,
                direction="Interface side",
            ),
            treadmill,
        )
        restored = self.store.get_session(treadmill_id).report

        self.assertIsInstance(restored, TreadmillGaitReport)
        self.assertEqual(restored.per_step_results[0].quality_flags, ("reviewed",))
        self.assertEqual(restored.metric_summaries["contact_time_s"].mean, 0.2)
        self.assertEqual(restored.gait_cycles[0].stride_length_cm, 103.5)

        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT report_detail_json FROM test_sessions WHERE id = ?",
                (treadmill_id,),
            ).fetchone()
            detail = json.loads(row["report_detail_json"])
            detail["gait_cycles"][0].pop("stride_length_cm")
            conn.execute(
                "UPDATE test_sessions SET report_detail_json = ? WHERE id = ?",
                (json.dumps(detail, ensure_ascii=False), treadmill_id),
            )

        legacy_restored = self.store.get_session(treadmill_id).report
        self.assertIsNone(legacy_restored.gait_cycles[0].stride_length_cm)

    def test_session_subject_id_schema_is_nullable(self):
        with self.store._connect() as conn:
            columns = {
                row["name"]: row
                for row in conn.execute("PRAGMA table_info(test_sessions)")
            }

        self.assertEqual(columns["subject_id"]["notnull"], 0)
        self.assertIn("subject_snapshot_json", columns)
        self.assertIn("config_source", columns)

    def test_schema_v1_adds_team_tables_and_nullable_session_team(self):
        with self.store._connect() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            session_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(test_sessions)")
            }
            version = conn.execute("PRAGMA user_version").fetchone()[0]

        self.assertIn("teams", tables)
        self.assertIn("team_memberships", tables)
        self.assertIn("team_id", session_columns)
        self.assertIn("team_snapshot_json", session_columns)
        self.assertIn("is_temporary", session_columns)
        self.assertEqual(version, 1)

    def test_subject_can_join_multiple_teams_and_leave_one(self):
        subject_id = self.store.create_subject("Alice", 1990)
        team_a = self.store.create_team("Alpha")
        team_b = self.store.create_team("Beta")

        self.store.add_subject_to_team(subject_id, team_a)
        self.store.add_subject_to_team(subject_id, team_b)
        self.assertEqual(
            [team.name for team in self.store.get_subject_teams(subject_id)],
            ["Alpha", "Beta"],
        )

        self.store.remove_subject_from_team(subject_id, team_a)
        self.assertEqual(
            [team.name for team in self.store.get_subject_teams(subject_id)],
            ["Beta"],
        )

    def test_team_names_are_trimmed_and_normalized_for_uniqueness(self):
        team_id = self.store.create_team("  Alpha  Team  ")

        self.assertEqual(self.store.search_teams()[0].id, team_id)
        self.assertEqual(self.store.search_teams()[0].name, "Alpha  Team")
        with self.assertRaises(ValueError):
            self.store.create_team("alpha team")

    def test_readding_inactive_membership_reactivates_it(self):
        subject_id = self.store.create_subject("Alice", 1990)
        team_id = self.store.create_team("Alpha")
        self.store.add_subject_to_team(subject_id, team_id)
        self.store.remove_subject_from_team(subject_id, team_id)

        self.store.add_subject_to_team(subject_id, team_id)

        self.assertEqual(
            [team.id for team in self.store.get_subject_teams(subject_id)], [team_id]
        )
        with self.store._connect() as conn:
            membership = conn.execute(
                "SELECT active, left_at FROM team_memberships"
            ).fetchone()
        self.assertEqual(membership["active"], 1)
        self.assertIsNone(membership["left_at"])

    def test_missing_or_archived_team_cannot_receive_new_membership(self):
        subject_id = self.store.create_subject("Alice", 1990)
        with self.assertRaises(KeyError):
            self.store.add_subject_to_team(subject_id, 999)

        team_id = self.store.create_team("Alpha")
        with self.store._connect() as conn:
            conn.execute("UPDATE teams SET archived = 1 WHERE id = ?", (team_id,))
        with self.assertRaises(KeyError):
            self.store.add_subject_to_team(subject_id, team_id)

    def test_create_subject_with_team_creates_membership_atomically(self):
        team_id = self.store.create_team("Alpha")
        subject_id = self.store.create_subject("Alice", 1990, team_id=team_id)

        self.assertEqual(
            [team.id for team in self.store.get_subject_teams(subject_id)], [team_id]
        )
        with self.assertRaises(KeyError):
            self.store.create_subject("Bob", 1991, team_id=999)
        self.assertEqual(self.store.search_subjects("Bob"), [])

    def test_duplicate_lookup_matches_normalized_name_and_birth_year(self):
        subject_id = self.store.create_subject("  Alice  Smith ", 1990)
        self.store.create_subject("Alice Smith", 1991)

        matches = self.store.find_duplicate_subjects("alice   smith", 1990)

        self.assertEqual([item.subject.id for item in matches], [subject_id])

    def test_subject_search_result_includes_active_team_names(self):
        subject_id = self.store.create_subject("Alice", 1990)
        beta_id = self.store.create_team("Beta")
        alpha_id = self.store.create_team("Alpha")
        self.store.add_subject_to_team(subject_id, beta_id)
        self.store.add_subject_to_team(subject_id, alpha_id)

        result = self.store.search_subjects("Alice")[0]

        self.assertEqual(result.team_names, ("Alpha", "Beta"))

    def test_existing_required_subject_schema_is_migrated_without_data_loss(self):
        legacy_path = Path(self.tmpdir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.executescript(
                """
                CREATE TABLE subjects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    sex TEXT NOT NULL DEFAULT '',
                    birth_year INTEGER NOT NULL,
                    height_cm REAL,
                    weight_kg REAL,
                    level TEXT NOT NULL DEFAULT 'intermediate',
                    focus_side TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE test_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id INTEGER NOT NULL REFERENCES subjects(id),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    test_type TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    height_cm REAL,
                    weight_kg REAL,
                    total_jumps INTEGER,
                    finish_reason TEXT,
                    report_summary_json TEXT,
                    export_path TEXT
                );
                INSERT INTO subjects (
                    id, display_name, birth_year, created_at, updated_at
                ) VALUES (1, 'Legacy', 1990, '2026-01-01', '2026-01-01');
                """
            )
            conn.execute(
                """
                INSERT INTO test_sessions (
                    id, subject_id, started_at, test_type, config_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    7,
                    1,
                    "2026-01-02 10:00:00",
                    "Jump Test",
                    '{"test_type":"Jump Test"}',
                ),
            )

        migrated = SubjectStore(legacy_path)

        self.assertEqual(migrated.get_session(7).subject_id, 1)
        self.assertIsNone(migrated.get_session(7).team_id)
        self.assertFalse(migrated.get_session(7).is_temporary)
        with migrated._connect() as conn:
            subject_column = next(
                row
                for row in conn.execute("PRAGMA table_info(test_sessions)")
                if row["name"] == "subject_id"
            )
            temporary_column = next(
                row
                for row in conn.execute("PRAGMA table_info(test_sessions)")
                if row["name"] == "is_temporary"
            )
        self.assertEqual(subject_column["notnull"], 0)
        self.assertEqual(temporary_column["notnull"], 1)

    def test_existing_temporary_marker_is_repaired_for_unlinked_sessions(self):
        session_id = self.store.record_session(
            None,
            _TestConfig(),
            _jump_report(),
            subject_snapshot={"display_name": "临时测试"},
        )
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE test_sessions SET is_temporary = 0 WHERE id = ?",
                (session_id,),
            )

        reopened = SubjectStore(self.db_path)

        self.assertTrue(reopened.get_session(session_id).is_temporary)


if __name__ == "__main__":
    unittest.main()


    def test_bind_card_uid_links_and_rejects_duplicates(self):
        alice_id = self.store.create_subject("Alice", 1990)
        bob_id = self.store.create_subject("Bob", 1985)
        self.store.bind_card_uid(alice_id, "aa:bb:cc:dd")
        alice = self.store.get_subject(alice_id)
        self.assertEqual(alice.card_uid, "AABBCCDD")
        found = self.store.get_subject_by_card_uid("aabbccdd")
        self.assertEqual(found.id, alice_id)
        with self.assertRaises(ValueError):
            self.store.bind_card_uid(bob_id, "AABBCCDD")
        self.store.unbind_card_uid(alice_id)
        self.assertIsNone(self.store.get_subject(alice_id).card_uid)
        self.store.bind_card_uid(bob_id, "AABBCCDD")
        self.assertEqual(self.store.get_subject_by_card_uid("AABBCCDD").id, bob_id)
