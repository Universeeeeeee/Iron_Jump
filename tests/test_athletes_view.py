"""Local athlete-management page tests."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtTest import QSignalSpy

from data.subject_store import SubjectStore
from ui.views.athletes_view import AthletesView, _DuplicateSubjectDialog, _SubjectDialog


def test_athletes_view_lists_searches_and_starts_test(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alice_id = store.create_subject("Alice", 1990)
    store.create_subject("Bob", 1985)
    view = AthletesView(store)
    qtbot.addWidget(view)

    assert view._table.rowCount() == 2

    view._search.setText("Alice")
    assert view._table.rowCount() == 1
    view._table.selectRow(0)

    spy = QSignalSpy(view.test_requested)
    qtbot.mouseClick(view._btn_test, Qt.LeftButton)

    assert spy.count() == 1
    assert spy.at(0)[0].subject.id == alice_id


def test_athletes_view_refreshes_after_external_subject_creation(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    view = AthletesView(store)
    qtbot.addWidget(view)

    assert view._table.rowCount() == 0
    store.create_subject("Carol", 1995)

    view.refresh()

    assert view._table.rowCount() == 1
    assert view._table.item(0, 0).text() == "Carol"


def test_athletes_view_displays_and_filters_active_team_memberships(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    multi_team_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    store.add_subject_to_team(multi_team_id, beta_id)
    store.create_subject("Bob", 1985)
    alpha_only_id = store.create_subject("Carol", 1995, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)

    teams_column = view._table.horizontalHeaderItem(5).text()
    assert teams_column == "所属团队"
    team_texts = {
        view._table.item(row, 0).text(): view._table.item(row, 5).text()
        for row in range(view._table.rowCount())
    }
    assert team_texts["Alice"] == "Alpha、Beta"
    assert team_texts["Bob"] == "未加入团队"

    view._team_filter.setCurrentIndex(view._team_filter.findData(alpha_id))
    assert {
        view._table.item(row, 0).text() for row in range(view._table.rowCount())
    } == {"Alice", "Carol"}

    view._team_filter.setCurrentIndex(view._team_filter.findData(view.WITHOUT_TEAM))
    assert [view._table.item(row, 0).text() for row in range(view._table.rowCount())] == [
        "Bob"
    ]
    assert alpha_only_id != multi_team_id


def test_team_filter_can_open_that_team_results(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    view = AthletesView(store)
    qtbot.addWidget(view)
    spy = QSignalSpy(view.team_results_requested)

    assert not view._btn_team_results.isEnabled()
    view._team_filter.setCurrentIndex(view._team_filter.findData(alpha_id))
    qtbot.mouseClick(view._btn_team_results, Qt.LeftButton)

    assert spy.count() == 1
    assert spy.at(0)[0].id == alpha_id


def test_subject_dialog_offers_initial_team_or_multi_team_memberships(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)

    create_dialog = _SubjectDialog(store=store)
    qtbot.addWidget(create_dialog)
    assert [create_dialog._initial_team.itemText(index) for index in range(create_dialog._initial_team.count())] == [
        "暂不加入团队",
        "Alpha",
        "Beta",
        "新建团队…",
    ]
    assert create_dialog.values()["team_ids"] == []

    edit_dialog = _SubjectDialog(store=store, subject=store.get_subject(subject_id))
    qtbot.addWidget(edit_dialog)
    assert edit_dialog._team_list is not None
    selected = [
        edit_dialog._team_list.item(index).data(Qt.UserRole)
        for index in range(edit_dialog._team_list.count())
        if edit_dialog._team_list.item(index).checkState() == Qt.Checked
    ]
    assert selected == [alpha_id]


def test_subject_dialog_creates_and_selects_new_initial_team(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    dialog = _SubjectDialog(store=store)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        "ui.views.athletes_view.QInputDialog.getText",
        lambda *args: ("Gamma", True),
    )

    dialog._initial_team.setCurrentIndex(dialog._initial_team.count() - 1)
    dialog._handle_initial_team_choice()

    gamma = store.search_teams("Gamma")[0]
    assert dialog._initial_team.currentData() == gamma.id
    assert dialog.values()["team_ids"] == [gamma.id]


def test_edit_subject_synchronizes_active_team_memberships(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        _SubjectDialog,
        "get_values",
        classmethod(
            lambda cls, parent, subject=None, *, store=None: {
                "display_name": "Alice",
                "birth_year": 1990,
                "height_cm": None,
                "weight_kg": None,
                "level": "intermediate",
                "focus_side": "",
                "team_ids": [beta_id],
            }
        ),
    )

    view._edit_selected()

    assert [team.name for team in store.get_subject_teams(subject_id)] == ["Beta"]


def test_create_duplicate_flow_reuses_selected_profile_and_membership(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    store.archive_subject(subject_id)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        view,
        "_ask_duplicate_action",
        lambda matches: ("reuse", matches[0]),
    )

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": [beta_id]}
    )

    assert [result.subject.id for result in store.search_subjects()] == [subject_id]
    assert [team.name for team in store.get_subject_teams(subject_id)] == ["Alpha", "Beta"]


def test_create_duplicate_flow_reuses_existing_target_membership(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    subject_id = store.create_subject("Alice", 1990, team_id=alpha_id)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        view,
        "_ask_duplicate_action",
        lambda matches: ("reuse", matches[0]),
    )

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": [alpha_id]}
    )

    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM team_memberships WHERE subject_id = ? AND team_id = ?",
            (subject_id, alpha_id),
        ).fetchone()[0]
    assert count == 1


def test_create_without_duplicate_creates_selected_initial_team(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    view = AthletesView(store)
    qtbot.addWidget(view)

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": [alpha_id]}
    )

    result = store.search_subjects()[0]
    assert [team.name for team in store.get_subject_teams(result.subject.id)] == ["Alpha"]


def test_create_duplicate_flow_can_create_second_profile_after_confirmation(
    qtbot, tmp_path, monkeypatch
):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    store.create_subject("Alice", 1990)
    view = AthletesView(store)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_ask_duplicate_action", lambda matches: ("create", None))

    view._create_subject_from_values(
        {"display_name": "Alice", "birth_year": 1990, "team_ids": []}
    )

    assert len(store.find_duplicate_subjects("Alice", 1990)) == 2


def test_duplicate_dialog_displays_profile_details_without_database_id(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alpha_id = store.create_team("Alpha")
    store.create_subject("Alice", 1990, team_id=alpha_id)
    candidate = store.find_duplicate_subjects("Alice", 1990)[0]

    dialog = _DuplicateSubjectDialog([candidate])
    qtbot.addWidget(dialog)

    assert dialog._table.horizontalHeaderItem(0).text() == "姓名"
    assert dialog._table.horizontalHeaderItem(1).text() == "出生年份"
    assert dialog._table.horizontalHeaderItem(2).text() == "所属团队"
    assert dialog._table.horizontalHeaderItem(3).text() == "创建时间"
    assert dialog._table.horizontalHeaderItem(4).text() == "最近测试"
    assert "id" not in " ".join(
        dialog._table.item(0, column).text() for column in range(dialog._table.columnCount())
    ).casefold()


def test_athletes_view_rfid_selects_bound_subject(qtbot, tmp_path):
    from hardware.rc200u import SimulatedRc200u

    store = SubjectStore(tmp_path / "subjects.sqlite3")
    alice_id = store.create_subject("Alice", 1990)
    bob_id = store.create_subject("Bob", 1985)
    store.bind_card_uid(alice_id, "AABBCCDD")
    reader = SimulatedRc200u()
    view = AthletesView(store, rfid_reader=reader)
    qtbot.addWidget(view)

    reader.queue_uid("AABBCCDD")
    view._poll_rfid()

    selected = view._selected_result()
    assert selected is not None
    assert selected.subject.id == alice_id
    assert "Alice" in view._rfid_status.text()
    assert view._table.item(0 if view._results[0].subject.id == alice_id else 1, 7).text() in {
        "AABBCCDD",
        store.get_subject(alice_id).card_uid,
    }
    assert bob_id != alice_id


def test_athletes_view_can_bind_unbound_card(qtbot, tmp_path):
    from hardware.rc200u import SimulatedRc200u

    store = SubjectStore(tmp_path / "subjects.sqlite3")
    bob_id = store.create_subject("Bob", 1985)
    reader = SimulatedRc200u()
    view = AthletesView(store, rfid_reader=reader)
    qtbot.addWidget(view)

    reader.queue_uid("11223344")
    view._poll_rfid()
    view._select_subject_id(bob_id)
    view._bind_current_card()

    assert store.get_subject_by_card_uid("11223344").id == bob_id
    assert view._table.item(
        next(row for row, result in enumerate(view._results) if result.subject.id == bob_id),
        7,
    ).text() == "11223344"


def test_athletes_view_rfid_reports_error_and_recovery(qtbot, tmp_path):
    from unittest.mock import Mock
    from hardware.rc200u import SimulatedRc200u, UidRead

    store = SubjectStore(tmp_path / "subjects.sqlite3")
    store.create_subject("Alice", 1990)
    reader = SimulatedRc200u()
    reader.request_uid = Mock(return_value=UidRead(None, 23, "driver missing"))
    view = AthletesView(store, rfid_reader=reader)
    qtbot.addWidget(view)
    view._poll_rfid()
    assert "23" in view._rfid_status.text()
    assert not view._btn_bind_card.isEnabled()
    reader.request_uid.return_value = UidRead(None, 24, "timeout")
    view._poll_rfid()
    assert "24" in view._rfid_status.text()
    reader.request_uid.return_value = UidRead(None, 8, "no card")
    view._poll_rfid()
    assert view._rfid_status.text() == "RFID：等待贴卡"
