"""Tests for the setup view config summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QMessageBox,
)

from config.treadmill_config import TreadmillGaitConfig
from config.test_config import TestConfig as RuntimeTestConfig
from data.subject_store import SubjectStore
from ui.views.setup_view import SetupView


_APP = None


def _app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    else:
        _APP = app
    return _APP


def test_setup_view_accepts_treadmill_gait_config_without_attribute_error():
    _app()
    view = SetupView()
    config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="05:00",
        treadmill_speed=5.5,
        direction="Interface side",
    )

    view._set_current_config(config, "manual")

    summary_text = view._summary_label.text()
    assert "跑步机步态" in summary_text
    assert "速度：5.5 km/h" in summary_text
    assert "方向：Interface side" in summary_text
    assert view.btn_ready.isEnabled()


def test_manual_config_initializes_from_selected_agent_test_type():
    _app()
    view = SetupView()
    view._agent_panel._test_type_combo.setCurrentText("Treadmill Gait Test")

    view._set_config_mode(1)

    assert view.param_panel._test_type == "Treadmill Gait Test"
    assert "treadmill_speed" in view.param_panel._widgets
    assert "direction" in view.param_panel._widgets
    assert "start_type" not in view.param_panel._widgets
    assert view._current_config.test_type == "Treadmill Gait Test"


def test_setup_view_uses_application_page_header_and_two_stage_action():
    _app()
    view = SetupView()

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert "测试" in labels
    assert "配置测试参数并连接设备" in labels
    assert "IronJump 步态分析系统" not in labels
    assert view.btn_ready.text() == "进入测试准备"
    assert "● 设备将在测试界面检查" not in labels
    assert view.findChild(QFrame, "ConfigSummaryCard") is not None
    assert (
        view._status_bar.sizePolicy().verticalPolicy()
        == QSizePolicy.Preferred
    )


def test_new_subject_dialog_uses_complete_dark_theme():
    _app()
    view = SetupView()

    dialog, _name, birth_year, _level = view._build_new_subject_dialog()

    assert dialog.objectName() == "NewSubjectDialog"
    assert "#121923" in dialog.styleSheet()
    assert isinstance(birth_year, QSpinBox)
    assert "QSpinBox" in dialog.styleSheet()


def test_config_summary_is_readable_and_structured():
    app = _app()
    view = SetupView()
    config = RuntimeTestConfig(
        start_type="Status change",
        stop_type="Status change",
        number_of_jumps=3,
    )

    view._set_current_config(config, "manual")
    view.show()
    app.processEvents()

    assert view._summary_label.font().pixelSize() >= 14
    assert "配置方式：手动配置" in view._summary_label.text()
    assert "测试模式：纵跳" in view._summary_label.text()
    assert "启动：Status change" in view._summary_label.text()
    assert "\n" in view._summary_label.text()
    assert view._summary_label.height() >= view._summary_label.sizeHint().height()


def test_fullscreen_summary_is_narrower_larger_and_flat(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    view.resize(1660, 900)
    view.show()
    QApplication.processEvents()

    status_title = view.findChild(QLabel, "SummaryTitle")
    device_card = view.findChild(QFrame, "DeviceStatusCard")

    assert view._status_bar.width() == 320
    assert status_title.font().pixelSize() >= 18
    assert view._device_state_label.font().pixelSize() >= 14
    style = " ".join(view.styleSheet().split())
    assert "QFrame#ConfigWorkArea { background: transparent; border: none;" in style
    assert "QFrame#DeviceStatusCard { background: transparent; border: none;" in style
    assert device_card is not None


def test_all_config_sources_use_final_validation():
    _app()
    view = SetupView()
    invalid = RuntimeTestConfig(stop_type="Status change", number_of_jumps=None)

    for source in ("agent", "manual", "history", "last_session"):
        view._set_current_config(invalid, source)
        assert not view.btn_ready.isEnabled()
        assert view._config_errors


def test_ready_button_is_outside_summary_and_fixed_to_bottom_right(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    view.resize(1200, 720)
    view.show()
    QApplication.processEvents()

    assert not view._status_bar.isAncestorOf(view.btn_ready)
    assert view.rect().right() - view.btn_ready.geometry().right() <= 30
    assert view.rect().bottom() - view.btn_ready.geometry().bottom() <= 30


def test_filter_summary_expands_only_when_defaults_change():
    _app()
    view = SetupView()
    default_config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="01:00",
        treadmill_speed=3.0,
        direction="Opposite side",
    )

    view._set_current_config(default_config, "manual")

    assert view._filter_state_label.text() == "默认配置"
    assert view._filter_details_label.isHidden()

    changed_config = TreadmillGaitConfig(
        stop_type="End of Time",
        test_length="01:00",
        treadmill_speed=3.0,
        direction="Opposite side",
        min_contact_time=80,
    )
    view._set_current_config(changed_config, "manual")

    assert view._filter_state_label.text() == "已修改"
    assert not view._filter_details_label.isHidden()
    assert "接触阈值：80 ms" in view._filter_details_label.text()


def test_device_state_is_informational_and_does_not_block_preparation():
    _app()
    view = SetupView()
    view._set_current_config(
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=3.0,
            direction="Opposite side",
        ),
        "manual",
    )

    view.on_device_state("disconnected", "设备未连接")

    assert "设备未连接" in view._device_state_label.text()
    assert "标称采样率：1000 Hz" in view._device_meta_label.text()
    assert view.btn_ready.isEnabled()


def test_device_status_shows_exact_led_faults_and_refreshes_on_request(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    refreshes = []
    view.led_health_refresh_requested.connect(lambda: refreshes.append(True))
    view.on_device_state("connected", "设备已连接")

    view.on_led_health(
        {
            "status": "warning",
            "sample_count": 64,
            "disconnected_leds": [3, 12],
            "flickering_leds": [7],
        }
    )

    assert "LED异常" in view._device_state_label.text()
    assert "未联通/持续遮挡 LED：3、12" in view._device_meta_label.text()
    assert "闪烁 LED：7" in view._device_meta_label.text()
    qtbot.mouseClick(view.btn_refresh_led_health, Qt.LeftButton)
    assert refreshes == [True]


def test_normal_led_health_does_not_add_a_user_reminder(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    view.on_device_state("connected", "设备已连接")

    view.on_led_health(
        {
            "status": "normal",
            "sample_count": 64,
            "disconnected_leds": [],
            "flickering_leds": [],
        }
    )

    assert view._device_state_label.text() == "● 设备已连接"
    assert "LED状态" not in view._device_meta_label.text()


def test_led_health_refresh_is_disabled_while_streaming(qtbot):
    view = SetupView()
    qtbot.addWidget(view)

    view.on_device_state("streaming", "设备正在采集")

    assert not view.btn_refresh_led_health.isEnabled()


def test_manual_config_scrollbar_stays_dark_at_minimum_window_size(qtbot):
    view = SetupView()
    qtbot.addWidget(view)
    view.resize(996, 560)
    view._set_config_mode(1)
    scroll = view.findChild(QScrollArea, "ManualConfigScroll")
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    view.show()
    QApplication.processEvents()

    scrollbar = scroll.verticalScrollBar()
    assert scrollbar.isVisible()
    background = scrollbar.grab().toImage().pixelColor(2, 2)
    assert background.lightness() < 80


def test_registered_profile_changes_require_explicit_update(tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    subject_id = store.create_subject(
        "Alice", 1990, height_cm=170.0, weight_kg=60.0,
        level="beginner", focus_side="left",
    )
    view = SetupView(subject_store=store)

    assert view.select_subject(subject_id)
    view._agent_panel._height_spin.setValue(180.0)
    view._agent_panel._weight_spin.setValue(70.0)
    view._agent_panel._level_combo.setCurrentText("advanced")
    view._agent_panel._focus_combo.setCurrentIndex(
        view._agent_panel._focus_combo.findData("right")
    )

    assert not view._update_subject_profile_btn.isHidden()
    unchanged = store.get_subject(subject_id)
    assert unchanged.height_cm == 170.0
    assert unchanged.birth_year == 1990

    monkeypatch.setattr(
        "ui.views.setup_view.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    view._on_update_subject_profile_clicked()

    updated = store.get_subject(subject_id)
    assert updated.height_cm == 180.0
    assert updated.weight_kg == 70.0
    assert updated.level == "advanced"
    assert updated.focus_side == "right"
    assert updated.birth_year == 1990


def test_registered_test_requires_selected_team_or_personal_identity(tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    subject_id = store.create_subject("Alice", 1990)
    alpha_id = store.create_team("Alpha")
    beta_id = store.create_team("Beta")
    inactive_id = store.create_team("Inactive")
    archived_id = store.create_team("Archived")
    store.add_subject_to_team(subject_id, alpha_id)
    store.add_subject_to_team(subject_id, beta_id)
    store.add_subject_to_team(subject_id, inactive_id)
    store.add_subject_to_team(subject_id, archived_id)
    store.remove_subject_from_team(subject_id, inactive_id)
    with store._connect() as conn:
        conn.execute("UPDATE teams SET archived = 1 WHERE id = ?", (archived_id,))
    view = SetupView(subject_store=store)
    ready = []
    view.ready_signal.connect(ready.append)

    assert view.select_subject(subject_id)
    view._set_current_config(
        RuntimeTestConfig(
            start_type="Status change", stop_type="Status change",
            finish_position="Inside area", number_of_jumps=3,
        ),
        "manual",
    )

    assert [
        view._team_identity_combo.itemText(index)
        for index in range(view._team_identity_combo.count())
    ] == ["请选择本次测试身份", "Alpha", "Beta", "不以团队身份测试"]
    assert not view.btn_ready.isEnabled()

    monkeypatch.setattr(
        "ui.views.setup_view.QMessageBox.information", lambda *_args, **_kwargs: None,
    )
    view._on_ready_clicked()
    assert ready == []

    view._team_identity_combo.setCurrentIndex(1)
    assert view.btn_ready.isEnabled()
    view._on_ready_clicked()
    assert ready[-1].team_id == alpha_id
    assert ready[-1].team_snapshot == {"id": alpha_id, "name": "Alpha"}

    view._team_identity_combo.setCurrentIndex(3)
    view._on_ready_clicked()
    assert ready[-1].team_id is None
    assert ready[-1].team_snapshot is None

    view._subject_combo.setCurrentIndex(0)
    assert [
        view._team_identity_combo.itemText(index)
        for index in range(view._team_identity_combo.count())
    ] == ["不以团队身份测试"]
    assert not view._team_identity_combo.isEnabled()
    assert view.btn_ready.isEnabled()
    view._on_ready_clicked()
    assert ready[-1].subject_id is None
    assert ready[-1].team_id is None
    assert ready[-1].team_snapshot is None


def test_selected_team_stays_disabled_until_config_is_confirmed(tmp_path):
    _app()
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    subject_id = store.create_subject("Alice", 1990)
    team_id = store.create_team("Alpha")
    store.add_subject_to_team(subject_id, team_id)
    view = SetupView(subject_store=store)

    assert view.select_subject(subject_id)
    view._team_identity_combo.setCurrentIndex(1)

    assert not view.btn_ready.isEnabled()


def test_empty_measurements_do_not_look_like_profile_edits(tmp_path):
    _app()
    store = SubjectStore(tmp_path / "subjects.sqlite3")
    subject_id = store.create_subject("Alice", 1990)
    view = SetupView(subject_store=store)

    assert view.select_subject(subject_id)
    assert view._update_subject_profile_btn.isHidden()

    view._agent_panel._height_spin.setValue(180.0)

    assert not view._update_subject_profile_btn.isHidden()
