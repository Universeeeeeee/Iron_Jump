import pytest
import numpy as np

pytest.importorskip("dayu_widgets")

from ui.embedded_camera_panel import EmbeddedCameraPanel


def test_preview_area_keeps_sixteen_by_nine_ratio(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.resize(1200, 720)
    panel.show()
    qtbot.wait(10)

    assert panel._preview.width() * 9 == panel._preview.height() * 16
    content = panel._preview.contentsRect()
    assert content.width() * 9 == content.height() * 16


def test_preview_frame_fills_larger_sixteen_by_nine_area(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel._preview.setGeometry(0, 0, 2048, 1152)
    panel._preview_active = True

    panel._on_frame(np.zeros((1080, 1920, 3), dtype=np.uint8))

    pixmap = panel._preview.pixmap()
    assert pixmap.width() == panel._preview.contentsRect().width()
    assert pixmap.height() == panel._preview.contentsRect().height()


def test_default_preview_chrome_only_shows_settings_gear(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.resize(1200, 720)
    panel.show()
    qtbot.wait(10)

    assert not hasattr(panel, "_title")
    assert not hasattr(panel, "_stats")
    assert not hasattr(panel, "_btn_preview")
    assert panel._btn_settings.parent() is panel._preview_container
    assert panel._btn_settings.isVisible()
    assert panel._preview.geometry().contains(panel._btn_settings.geometry())


def test_restart_preview_action_restarts_capture(qtbot, monkeypatch):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    calls = []
    monkeypatch.setattr(panel, "shutdown", lambda: calls.append("shutdown"))
    monkeypatch.setattr(panel, "start_preview", lambda: calls.append("start"))

    panel._restart_action.trigger()

    assert panel._restart_action.text() == "重新启动预览"
    assert calls == ["shutdown", "start"]


def test_tinyse_settings_include_existing_camera_controls(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)

    assert panel._chk_mirror.text() == "镜像"
    assert panel._cmb_fov.count() == 3
    assert panel._cmb_ai.count() == 6
    assert panel._chk_af.text() == "自动对焦"
    assert panel._cmb_exp.count() == 19
    assert panel._cmb_flicker.count() == 2
    assert panel._cmb_wdr.count() == 3
    assert panel._record_action.text() == "Record"


def test_tinyse_default_settings_are_forwarded_to_control(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)

    class Control:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            return lambda value: self.calls.append((name, value))

        def set_ai_off(self):
            self.calls.append(("set_ai_off",))

    control = Control()
    panel._apply_control_settings(control)

    assert control.calls == [
        ("set_fov", 0),
        ("set_auto_focus", True),
        ("set_exposure_compensation", 0),
        ("set_anti_flicker", 0),
        ("set_wdr", 0),
        ("set_ai_off",),
    ]


def test_replay_offline_blocks_live_frames_and_redraws_on_resize(qtbot, tmp_path):
    from tests.test_avi_video import make_avi

    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.resize(900, 650)
    panel.show()
    panel.open_recording(make_avi(tmp_path, count=3, times=[0, 0.1, 0.3]))
    qtbot.waitUntil(lambda: panel._playback.info is not None)
    assert panel._playback_bar.isVisible()
    assert panel._playback_source.text() == "采样时间"
    assert not panel._controls_action.isEnabled()
    assert not panel._record_action.isEnabled()
    panel._preview_active = True
    current = panel._display_frame
    panel._on_frame(np.full((48, 64, 3), 255, np.uint8))
    assert panel._display_frame is current
    panel._playback.seek(2)
    qtbot.waitUntil(lambda: panel._playback.index == 2)
    assert "第 3/3 帧" in panel._playback_time.text()
    before = panel._preview.pixmap().size()
    panel.resize(700, 500)
    qtbot.waitUntil(lambda: panel._preview.pixmap().size() != before)
    assert panel._playback.index == 2
    panel._leave_playback()
    assert not panel._playback_bar.isVisible()
    assert panel._playback.info is None
    panel._on_frame(np.full((48, 64, 3), 255, np.uint8))
    assert panel._display_frame.mean() == 255
    panel.shutdown()


def test_replay_menu_recording_guards_and_completion(qtbot, tmp_path):
    from tests.test_avi_video import make_avi

    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    path = make_avi(tmp_path)
    assert panel._open_action.isEnabled()
    assert not panel._replay_action.isEnabled()

    class Capture:
        is_record_busy = True
        is_recording = False

    panel._capture = Capture()
    panel._refresh_menu()
    assert not panel._open_action.isEnabled()
    panel.open_recording(path)
    assert not panel._replay_mode
    panel._capture.is_record_busy = False
    panel._on_recording_finished(str(path))
    assert panel._replay_action.isEnabled()
    panel._capture = None
    panel.shutdown()


def test_replay_shortcuts_only_in_preview(qtbot, tmp_path):
    from qtpy.QtCore import Qt
    from qtpy.QtWidgets import QLineEdit
    from tests.test_avi_video import make_avi

    panel = EmbeddedCameraPanel()
    other = QLineEdit()
    qtbot.addWidget(panel)
    qtbot.addWidget(other)
    panel.show()
    panel.open_recording(make_avi(tmp_path, count=3))
    qtbot.waitUntil(lambda: panel._playback.info is not None)
    qtbot.keyClick(panel._preview, Qt.Key_Right)
    qtbot.waitUntil(lambda: panel._playback.index == 1)
    other.show()
    other.setFocus()
    qtbot.keyClick(other, Qt.Key_Right)
    qtbot.keyClick(other, Qt.Key_Space)
    assert panel._playback.index == 1
    assert not panel._playback.playing
    panel.shutdown()


def test_open_failure_is_visible_and_return_releases_player(qtbot, tmp_path):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.open_recording(tmp_path / "missing.avi")
    qtbot.waitUntil(lambda: "回放失败" in panel._preview.text())
    assert not panel._play_button.isEnabled()
    panel._leave_playback()
    assert panel._preview.text() == "未连接相机"
    panel.shutdown()


def test_stopped_preview_does_not_reappear_after_resize(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel._preview_active = True
    panel._on_frame(np.zeros((48, 64, 3), np.uint8))
    panel.stop_preview()
    panel.resize(700, 500)
    qtbot.wait(20)
    assert panel._preview.text() == "已停止"
    assert panel._display_frame is None


def test_camera_switch_and_close_stop_playback_worker(qtbot, tmp_path):
    from tests.test_avi_video import make_avi

    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.show()
    path = make_avi(tmp_path)
    panel.open_recording(path)
    qtbot.waitUntil(lambda: panel._playback.info is not None)
    panel.set_camera_type("logi")
    assert not panel._replay_mode
    assert panel._playback._worker is None
    panel.open_recording(path)
    qtbot.waitUntil(lambda: panel._playback.info is not None)
    panel.close()
    assert panel._playback._worker is None
