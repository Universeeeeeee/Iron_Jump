"""Embedded voice controls use existing Qt business flows without live audio."""
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDockWidget

from tests.test_voice_session import make_bridge


def test_voice_is_embedded_and_diagnostics_do_not_hide_microphone(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    window.show()
    panel = window._voice_panel
    voice.handle_event({"type": "ready", "aec": "WebRTC AEC3"})
    assert not window.findChildren(QDockWidget)
    assert window.centralWidget().isAncestorOf(panel)
    assert panel.toggle_button.isVisible()
    assert not panel.diagnostics.isVisible()
    qtbot.mouseClick(panel.details_button, Qt.LeftButton)
    assert panel.diagnostics.isVisible()
    qtbot.mouseClick(panel.details_button, Qt.LeftButton)
    assert voice.enabled
    assert panel.toggle_button.isVisible()
    assert "聆听" in panel.state_label.text()


def test_voice_feedback_stays_visible_in_current_page(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    panel = window._voice_panel
    voice.handle_event({"type": "transcript", "text": "开始", "final": False, "turn": 1})
    assert "开始" in panel.transcript.text()
    assert not window._controller.is_running
    voice.handle_event({"type": "transcript", "text": "开始", "final": True, "turn": 1})
    assert "请先确认配置" in panel.reply.text()
    window._stack.setCurrentWidget(window._report_view)
    assert "报告" in panel.context_label.text()


def test_overground_pause_is_rejected_without_waiting(qtbot, monkeypatch):
    from config.walking_config import WalkingConfig
    window, voice = make_bridge(qtbot, monkeypatch)
    window._controller._config = WalkingConfig()
    window._controller._is_running = True
    try:
        voice.handle_text("暂停")
        assert voice.pending is None
        assert not voice.timer.isActive()
        assert "不支持暂停" in window._voice_panel.reply.text()
    finally:
        window._controller._is_running = False


def test_stop_speaking_invalidates_old_reply_without_stopping_test(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    writes = []
    monkeypatch.setattr(voice, "_write", writes.append)
    voice.agent_turn = voice.turn
    voice._wait_for("start")
    voice.interrupt_speech()
    assert writes[-1]["type"] == "interrupt"
    assert voice.pending is not None  # still wait for the device acknowledgement
    voice._agent_reply("过期的配置播报")
    assert "过期" not in window._voice_panel.reply.text()
    assert voice.enabled


def test_voice_error_survives_worker_exit(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    voice.handle_event({"type": "error", "message": "请检查麦克风权限"})
    voice._finished()
    assert "请检查麦克风权限" in window._voice_panel.reply.text()
    assert "未连接" in window._voice_panel.state_label.text()
    assert not window._voice_panel.interrupt_button.isEnabled()


def test_late_transcript_after_closing_does_not_execute(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    commands = []
    monkeypatch.setattr(voice, "handle_text", commands.append)
    voice.close()
    voice.handle_event({"type": "transcript", "text": "开始", "final": True, "turn": 3})
    assert not commands
    assert "已关闭" in window._voice_panel.state_label.text()


def test_voice_configuration_reveals_existing_conversation(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    setup = window._setup_view
    setup._set_config_mode(1)
    original_config = setup._current_config
    monkeypatch.setattr(setup._agent_panel, "submit_voice", lambda text: True)
    voice.handle_text("帮我配置十次纵跳")
    assert setup._config_stack.currentWidget() is setup._agent_panel
    assert setup._current_config is original_config  # application still requires confirmation


def test_overground_start_requires_preflight_and_cannot_apply_old_agent_config(qtbot, monkeypatch):
    from config.walking_config import WalkingConfig
    from config.test_config import default_jump_config
    window, voice = make_bridge(qtbot, monkeypatch)
    config = WalkingConfig()
    setup = window._setup_view
    setup._set_config_mode(1)
    setup._current_config = config
    setup._agent_panel._pending_config = default_jump_config()
    voice.handle_text("确认配置")
    assert setup._current_config is config
    assert "手动配置" in window._voice_panel.reply.text()
    window._controller._config = config
    window._controller._device_state = "connected"
    window._active_config = config
    window._stack.setCurrentWidget(window._exec_view)
    voice.handle_text("开始")
    assert voice.pending is None
    assert "空场自检尚未通过" in window._voice_panel.reply.text()
    window._controller._walking_ready = True
    voice.handle_text("开始")
    assert voice.pending is None
    assert "核对" in window._voice_panel.reply.text()
    assert "点击" in window._voice_panel.reply.text()
