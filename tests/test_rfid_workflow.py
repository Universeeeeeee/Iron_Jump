"""RFID taps route the real UI to configuration with the correct profile."""

import pytest
from qtpy.QtWidgets import QApplication, QDialog

from config.test_config import default_jump_config
from hardware.rc200u import SimulatedRc200u, UidRead
from tests.test_main_window_navigation import _window
from ui.views.setup_view import SessionSetup


def _rfid_window(qtbot, tmp_path, monkeypatch):
    reader = SimulatedRc200u()
    monkeypatch.setattr("ui.views.athletes_view.Rc200uReader", lambda: reader)
    window, controller = _window(qtbot, tmp_path)
    window._athletes_view._rfid_timer.stop()
    window._athletes_view._rfid_reader = reader
    store = window._subject_store
    alice = store.create_subject("Alice", 1990, height_cm=172, weight_kg=61,
                                 level="advanced", focus_side="left")
    bob = store.create_subject("Bob", 1985, height_cm=185, weight_kg=80)
    store.bind_card_uid(alice, "AABBCCDD")
    store.bind_card_uid(bob, "11223344")
    return window, controller, reader, alice, bob


def _tap(window, reader, uid):
    reader.queue_uid(uid)
    window._athletes_view._poll_rfid()


@pytest.mark.parametrize("page", ["athletes", "setup", "history", "settings"])
def test_bound_card_loads_profile_and_enters_config(qtbot, tmp_path, monkeypatch, page):
    window, controller, reader, alice, bob = _rfid_window(qtbot, tmp_path, monkeypatch)
    window._setup_view.select_subject(bob)
    getattr(window, f"_go_to_{page}")()
    window._athletes_view._search.setText("Bob")

    _tap(window, reader, "AABBCCDD")

    assert window._stack.currentWidget() is window._setup_view
    assert window._setup_view.current_subject_result().subject.id == alice
    profile = window._setup_view._agent_panel.current_profile_snapshot()
    assert window._setup_view.current_subject_result().subject.display_name == "Alice"
    assert profile["height_cm"] == 172
    assert profile["weight_kg"] == 61
    assert profile["level"] == "advanced"
    assert profile["focus_side"] == "left"
    assert controller.prepared == []
    assert controller.starts == 0


def test_held_card_does_not_reset_edits_even_when_status_changes(qtbot, tmp_path, monkeypatch):
    window, _, reader, alice, _ = _rfid_window(qtbot, tmp_path, monkeypatch)
    _tap(window, reader, "AABBCCDD")
    assert window._setup_view.current_subject_result().subject.id == alice
    window._setup_view._agent_panel._height_spin.setValue(180)
    for result in (UidRead("AABBCCDD", 10, "card halted"),
                   UidRead(None, 24, "timeout"),
                   UidRead("AABBCCDD", 0, "ok")):
        monkeypatch.setattr(reader, "request_uid", lambda result=result: result)
        window._athletes_view._poll_rfid()
        assert window._setup_view._agent_panel.current_profile_snapshot()["height_cm"] == 180


def test_remove_and_retap_loads_latest_profile_and_different_card_switches_user(qtbot, tmp_path, monkeypatch):
    window, _, reader, alice, bob = _rfid_window(qtbot, tmp_path, monkeypatch)
    _tap(window, reader, "AABBCCDD")
    window._subject_store.update_subject(alice, height_cm=176)
    _tap(window, reader, None)
    _tap(window, reader, "AABBCCDD")
    assert window._setup_view._agent_panel.current_profile_snapshot()["height_cm"] == 176
    _tap(window, reader, "11223344")
    assert window._setup_view.current_subject_result().subject.id == bob


def test_unknown_card_binding_continues_to_config(qtbot, tmp_path, monkeypatch):
    window, _, reader, alice, _ = _rfid_window(qtbot, tmp_path, monkeypatch)
    _tap(window, reader, "55667788")
    assert window._stack.currentWidget() is window._athletes_view
    assert "未绑定" in window._athletes_view._rfid_status.text()
    window._athletes_view._select_subject_id(alice)
    window._athletes_view._bind_current_card()
    assert window._subject_store.get_subject_by_card_uid("55667788").id == alice
    assert window._stack.currentWidget() is window._setup_view
    assert window._setup_view.current_subject_result().subject.id == alice


@pytest.mark.parametrize("state", ["prepared", "pending", "running", "paused"])
def test_tap_cannot_replace_prepared_or_running_identity(qtbot, tmp_path, monkeypatch, state):
    window, controller, reader, alice, bob = _rfid_window(qtbot, tmp_path, monkeypatch)
    window._setup_view.select_subject(bob)
    window._on_ready(SessionSetup(default_jump_config(), subject_id=bob))
    controller.is_running = state in {"running", "paused"}
    controller._start_pending = state == "pending"
    controller.is_paused = state == "paused"
    _tap(window, reader, "AABBCCDD")
    assert window._stack.currentWidget() is window._exec_view
    assert window._subject_id == bob
    assert window._setup_view.current_subject_result().subject.id == bob
    assert controller.stops == 0
    assert "重新刷卡" in window.statusBar().currentMessage()


def test_archived_card_does_not_load_previous_user(qtbot, tmp_path, monkeypatch):
    window, _, reader, alice, bob = _rfid_window(qtbot, tmp_path, monkeypatch)
    window._setup_view.select_subject(bob)
    window._subject_store.archive_subject(alice)
    window._go_to_athletes()
    _tap(window, reader, "AABBCCDD")
    assert window._stack.currentWidget() is window._athletes_view
    assert window._setup_view.current_subject_result().subject.id == bob
    assert "已归档" in window._athletes_view._rfid_status.text()


def test_modal_dialog_requires_retap_after_closing(qtbot, tmp_path, monkeypatch):
    window, _, reader, alice, bob = _rfid_window(qtbot, tmp_path, monkeypatch)
    window._setup_view.select_subject(bob)
    dialog = QDialog(window)
    qtbot.addWidget(dialog)
    dialog.setModal(True)
    dialog.show()
    QApplication.processEvents()
    _tap(window, reader, "AABBCCDD")
    assert window._setup_view.current_subject_result().subject.id == bob
    dialog.close()
    _tap(window, reader, None)
    _tap(window, reader, "AABBCCDD")
    assert window._setup_view.current_subject_result().subject.id == alice
