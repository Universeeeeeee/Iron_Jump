"""Read-only local settings page tests."""

from __future__ import annotations

from data.subject_store import SubjectStore
from ui.views.settings_view import SettingsView


def test_settings_view_is_local_and_read_only(qtbot, tmp_path):
    store = SubjectStore(tmp_path / "settings.sqlite3")
    view = SettingsView(store)
    qtbot.addWidget(view)

    text = " ".join(label.text() for label in view._value_labels.values())
    assert str(store.db_path) in text
    assert "0x04B4" in text
    assert "0x1004" in text
    assert "本地存储" in view._mode_label.text()
    assert "无需登录" in view._mode_label.text()


def test_main_acquisition_defaults_match_settings(qtbot, monkeypatch):
    from ui.session_controller import SessionController
    for name in ('DAYU_TIMEOUT', 'DAYU_CHUNK'):
        monkeypatch.delenv(name, raising=False)
    controller = SessionController()
    assert (controller._timeout_ms, controller._chunk_size) == (10, 2048)
    view = SettingsView()
    qtbot.addWidget(view)
    assert view._value_labels['timeout'].text() == '10 ms（只读）'
    assert view._value_labels['chunk'].text() == '2048 bytes（只读）'
