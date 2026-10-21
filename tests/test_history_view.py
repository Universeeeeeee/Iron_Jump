"""Tests for the read-only history view."""

import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtWidgets import QApplication, QLabel, QInputDialog

from config.test_config import TestConfig as _TestConfig
from config.test_report import JumpTestReport
from config.treadmill_config import TreadmillGaitConfig
from config.treadmill_report import TreadmillGaitReport
from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from data.subject_store import SubjectStore
from ui.views.history_view import HistoryView, _config_detail_lines


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


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


def _treadmill_gait_report(**overrides):
    values = {
        "finish_reason": "manual",
        "touch_count": 4,
        "lift_count": 4,
        "resolved_starting_foot": "left",
        "starting_foot_source": "auto_first_contact",
    }
    values.update(overrides)
    return TreadmillGaitReport(**values)


class HistoryViewTest(unittest.TestCase):
    def setUp(self):
        _app()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "iron_jump.sqlite3"
        self.store = SubjectStore(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_ground_history_parameters_do_not_require_flight_threshold(self):
        for config in (WalkingConfig(), OvergroundRunningConfig(min_contact_time=60)):
            with self.subTest(test_type=config.test_type):
                lines = _config_detail_lines(config)
                self.assertIn("接触阈值: >60ms", lines)
                self.assertFalse(any("腾空" in line for line in lines))

    def test_history_view_uses_readable_visual_hierarchy(self):
        view = HistoryView(self.store)
        view.show()
        QApplication.processEvents()
        title = view.findChild(QLabel, "HistoryTitle")

        self.assertEqual(title.text(), "历史记录")
        self.assertGreaterEqual(title.font().pixelSize(), 22)
        self.assertGreaterEqual(view._session_table.font().pixelSize(), 14)
        self.assertGreaterEqual(
            view._session_table.verticalHeader().defaultSectionSize(), 48
        )

    def test_history_view_filters_by_athlete_and_test_type(self):
        alice_id = self.store.create_subject("Alice", 1990)
        bob_id = self.store.create_subject("Bob", 1992)
        self.store.record_session(alice_id, _TestConfig(), _jump_report())
        self.store.record_session(
            bob_id,
            TreadmillGaitConfig(
                stop_type="End of Time",
                test_length="05:00",
                treadmill_speed=5.5,
                direction="Interface side",
            ),
            _treadmill_gait_report(),
        )
        view = HistoryView(self.store)

        view.load_all()
        view._athlete_filter.setCurrentIndex(view._athlete_filter.findText("Alice"))

        self.assertEqual(view._session_table.rowCount(), 1)
        self.assertEqual(view._session_table.item(0, 0).text(), "Alice")

        view._athlete_filter.setCurrentIndex(0)
        treadmill_index = next(
            index
            for index in range(view._test_type_filter.count())
            if "Treadmill" in view._test_type_filter.itemText(index)
        )
        view._test_type_filter.setCurrentIndex(treadmill_index)

        self.assertEqual(view._session_table.rowCount(), 1)
        self.assertEqual(view._session_table.item(0, 0).text(), "Bob")

    def test_load_subject_lists_sessions_and_emits_selected_config(self):
        subject_id = self.store.create_subject("Alice", 1990)
        result = self.store.search_subjects("Alice")[0]
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            started_at="2026-05-14 09:00:00",
        )
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=6),
            _jump_report(touch_count=6, finish_reason="manual"),
            started_at="2026-05-14 11:00:00",
        )
        view = HistoryView(self.store)
        received = []
        view.load_config_requested.connect(received.append)

        view.load_subject(result)
        view._session_table.selectRow(0)
        view._on_load_config_clicked()

        self.assertEqual(view._session_table.rowCount(), 2)
        self.assertIn("Alice", view._subject_label.text())
        self.assertIn("手动结束", view._detail_label.text())
        self.assertIn("跳高标准差", view._detail_label.text())
        self.assertEqual(received[0].number_of_jumps, 6)

    def test_history_view_loads_treadmill_config_without_attribute_error(self):
        subject_id = self.store.create_subject("Bob", 1988)
        result = self.store.search_subjects("Bob")[0]
        config = TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="05:00",
            treadmill_speed=5.5,
            direction="Interface side",
        )
        self.store.record_session(
            subject_id,
            config,
            _treadmill_gait_report(),
            started_at="2026-05-14 13:00:00",
        )
        view = HistoryView(self.store)
        received = []
        view.load_config_requested.connect(received.append)

        view.load_subject(result)
        view._session_table.selectRow(0)
        view._on_load_config_clicked()

        detail_text = view._detail_label.text()
        self.assertIn("跑步机速度: 5.5 km/h", detail_text)
        self.assertIn("行进方向: Interface side", detail_text)
        self.assertIsInstance(received[0], TreadmillGaitConfig)

    def test_global_results_open_report_and_link_temporary_session(self):
        subject_id = self.store.create_subject("Alice", 1990)
        session_id = self.store.record_session(
            None,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            subject_snapshot={"display_name": "临时测试", "age": 30},
        )
        view = HistoryView(self.store)
        opened = []
        view.open_report_requested.connect(opened.append)

        view.load_all()
        view._session_table.selectRow(0)
        view._on_open_report_clicked()

        self.assertEqual(view._session_table.rowCount(), 1)
        self.assertEqual(view._session_table.item(0, 0).text(), "临时测试")
        self.assertEqual(opened[0].id, session_id)
        self.assertIsInstance(opened[0].report, JumpTestReport)

        original = QInputDialog.getItem
        QInputDialog.getItem = staticmethod(
            lambda *args, **kwargs: ("Alice", True)
        )
        try:
            view._on_link_subject_clicked()
        finally:
            QInputDialog.getItem = original

        self.assertEqual(self.store.get_session(session_id).subject_id, subject_id)
        self.assertEqual(view._session_table.item(0, 0).text(), "Alice")
        self.assertEqual(view._session_table.item(0, 1).text(), "个人")

    def test_link_temporary_session_disambiguates_same_name_subjects(self):
        first_id = self.store.create_subject("Alice", 1990)
        second_id = self.store.create_subject("Alice", 1995)
        session_id = self.store.record_session(
            None,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            subject_snapshot={"display_name": "临时测试", "age": 30},
        )
        view = HistoryView(self.store)
        view.load_all()
        view._session_table.selectRow(0)

        original = QInputDialog.getItem

        def choose_second(*args, **kwargs):
            labels = args[3]
            assert all(" · " in label for label in labels)
            return (next(label for label in labels if "1995" in label), True)

        QInputDialog.getItem = staticmethod(choose_second)
        try:
            view._on_link_subject_clicked()
        finally:
            QInputDialog.getItem = original

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(self.store.get_session(session_id).subject_id, second_id)

    def test_history_shows_test_identity_and_can_load_one_team(self):
        subject_id = self.store.create_subject("Alice", 1990)
        alpha_id = self.store.create_team("Alpha")
        self.store.add_subject_to_team(subject_id, alpha_id)
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=3),
            _jump_report(touch_count=3),
            started_at="2026-05-14 09:00:00",
            team_id=alpha_id,
            team_snapshot={"id": alpha_id, "name": "Alpha"},
        )
        self.store.record_session(
            subject_id,
            _TestConfig(number_of_jumps=6),
            _jump_report(touch_count=6),
            started_at="2026-05-14 11:00:00",
        )
        self.store.record_session(
            None,
            _TestConfig(number_of_jumps=9),
            _jump_report(touch_count=9),
            started_at="2026-05-14 12:00:00",
        )
        view = HistoryView(self.store)

        view.load_all()

        self.assertEqual(view._session_table.horizontalHeaderItem(1).text(), "测试身份")
        self.assertEqual(
            {view._session_table.item(row, 1).text() for row in range(3)},
            {"Alpha", "个人"},
        )
        self.assertEqual(view._session_table.columnCount(), 5)

        view.load_team(self.store.search_teams("Alpha")[0])

        self.assertEqual(view._session_table.rowCount(), 1)
        self.assertIn("团队: Alpha", view._subject_label.text())
        self.assertEqual(view._session_table.item(0, 1).text(), "Alpha")

    def test_migration_marks_legacy_temporary_session_before_later_linking(self):
        legacy_path = Path(self.tmpdir.name) / "legacy-temporary.sqlite3"
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
                    subject_id INTEGER REFERENCES subjects(id),
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
                ) VALUES (1, 'Alice', 1990, '2026-01-01', '2026-01-01');
                INSERT INTO test_sessions (
                    id, subject_id, started_at, test_type, config_json
                ) VALUES (7, NULL, '2026-01-02 10:00:00', 'Jump Test',
                    '{"test_type":"Jump Test"}');
                """
            )

        conn.close()
        store = SubjectStore(legacy_path)
        self.assertTrue(store.get_session(7).is_temporary)
        store.link_session_to_subject(7, 1)
        view = HistoryView(store)

        view.load_all()

        self.assertEqual(view._session_table.item(0, 0).text(), "Alice")
        self.assertEqual(view._session_table.item(0, 1).text(), "个人")


if __name__ == "__main__":
    unittest.main()
