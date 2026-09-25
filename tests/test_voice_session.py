"""Real Qt controller + real GaitEngine; only the USB hardware is simulated."""

from qtpy.QtTest import QSignalSpy
from qtpy.QtCore import QProcess, QProcessEnvironment

from config.test_config import default_jump_config
from ui.main_window import MainWindow
from ui.voice_bridge import VoiceBridge
from ui.views.setup_view import SessionSetup
import ui.session_controller as session_module
from tests.test_session_controller_lifecycle import _FakeUsbWorker
from tests.test_main_window_navigation import _FakeLlmClient


def make_bridge(qtbot, monkeypatch):
    monkeypatch.setattr(session_module, "UsbWorker", _FakeUsbWorker)
    window = MainWindow(subject_store=None, llm_client=_FakeLlmClient(), enable_background_checks=False)
    qtbot.addWidget(window)
    bridge = VoiceBridge(window)
    window._voice = bridge
    bridge.enabled = True  # exercise business routing without opening the microphone
    return window, bridge


def test_voice_start_pause_resume_stop_changes_real_engine(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    controller = window._controller
    spoken = QSignalSpy(voice.spoken)
    window._on_ready(SessionSetup(config=default_jump_config(), subject_id=None, subject=None))
    qtbot.waitUntil(lambda: controller.device_state == "connected")
    voice.handle_text("开始")
    assert spoken.count() == 0
    qtbot.waitUntil(lambda: controller.is_running and spoken.count() == 1)
    assert spoken.at(0)[0] == "测试已开始。"
    assert not controller.engine.paused

    voice.handle_text("暂停")
    assert spoken.count() == 1
    qtbot.waitUntil(lambda: controller.is_paused and spoken.count() == 2)
    assert controller.engine.paused
    assert window._exec_view._paused
    assert spoken.at(1)[0] == "测试已暂停。"
    voice.handle_text("暂停")
    assert spoken.at(2)[0] == "测试已经暂停。"

    voice.handle_text("继续")
    qtbot.waitUntil(lambda: not controller.is_paused and spoken.count() == 4)
    assert not controller.engine.paused
    assert not window._exec_view._paused
    assert spoken.at(3)[0] == "测试已继续。"
    voice.handle_text("结束测试")
    assert not controller.is_running
    assert controller.engine is None
    assert window._stack.currentWidget() is window._report_view
    assert "报告已生成" in spoken.at(4)[0]


def test_voice_gait_question_and_followup_update_current_report(qtbot, monkeypatch):
    from tests.test_gait_insights import report

    window, voice = make_bridge(qtbot, monkeypatch)
    spoken = QSignalSpy(voice.spoken)
    window._report_view.load_report(report())
    window._stack.setCurrentWidget(window._report_view)
    voice.handle_text("步频稳定吗")
    assert "120.000 步/分钟" in spoken.at(0)[0]
    assert "有效样本" in window._report_view._gait_answer.toPlainText()
    voice.handle_text("具体证据呢")
    assert "120.000 步/分钟" in spoken.at(1)[0]
    window._report_view.load_report(report())
    assert window._report_view._gait_topic == ""


def test_greeting_does_not_submit_to_configuration_agent(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    spoken = QSignalSpy(voice.spoken)
    def unexpected(_text):
        raise AssertionError("greeting must not invoke the configuration agent")
    monkeypatch.setattr(window._setup_view._agent_panel, "submit_voice", unexpected)
    for phrase in ("喂，你好你好。", "你好", "你能做什么", "喂，你好。你是谁？"):
        voice.handle_text(phrase)
    assert spoken.count() == 4
    assert "你好，我在" in spoken.at(0)[0]
    assert "前后半程变化" in spoken.at(2)[0]
    assert "Iron Jump 的语音助手" in spoken.at(3)[0]
    assert not window._controller.is_running


def test_demo_disabled_configuration_is_not_reported_as_temporarily_busy(qtbot, tmp_path):
    from ui.demo import DemoWindow
    window = DemoWindow(db_path=tmp_path / "demo.sqlite3", enable_voice=True)
    qtbot.addWidget(window)
    voice = VoiceBridge(window)
    window._voice = voice
    voice.enabled = True
    spoken = QSignalSpy(voice.spoken)
    voice.handle_text("帮我配置一个步态测试")
    assert "演示未启用智能配置" in spoken.at(0)[0]
    assert "请稍后" not in spoken.at(0)[0]
    assert not window._llm_client.is_running
    window.close()


def test_no_false_success_on_wrong_state_or_failed_device(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    spoken = QSignalSpy(voice.spoken)
    voice.handle_text("开始")
    assert "请先确认配置" in spoken.at(0)[0]
    voice.handle_text("暂停")
    assert "没有运行中" in spoken.at(1)[0]
    voice._wait_for("start")
    voice._device_changed("error", "failed")
    assert "未确认执行" in spoken.at(2)[0]
    voice._wait_for("pause")
    voice._timed_out()
    assert "尚未收到" in spoken.at(3)[0]


def test_partial_and_stale_agent_responses_do_not_mutate_or_speak(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    calls = []
    monkeypatch.setattr(voice, "handle_text", calls.append)
    voice.handle_event({"type": "transcript", "text": "开始", "final": False, "turn": 1})
    assert not calls
    voice.handle_event({"type": "transcript", "text": "开始", "final": True, "turn": 1})
    assert calls == ["开始"]
    spoken = QSignalSpy(voice.spoken)
    voice.agent_turn = 1
    voice.handle_event({"type": "turn", "turn": 2})
    voice._agent_reply("旧回复")
    assert spoken.count() == 0


def test_voice_config_confirmation_and_prepare_use_existing_validation(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    setup = window._setup_view
    spoken = QSignalSpy(voice.spoken)
    voice.handle_text("确认配置")
    assert "还没有" in spoken.at(0)[0]
    config = default_jump_config()
    setup._agent_panel._set_pending_config(config, "test")
    voice.handle_text("确认配置")
    assert setup._current_config is config
    assert "配置已应用" in spoken.at(1)[0]
    voice.handle_text("准备测试")
    assert window._stack.currentWidget() is window._exec_view
    qtbot.waitUntil(lambda: window._controller.device_state == "connected")
    window._controller.discard()


def test_missing_key_worker_exits_and_manual_ui_remains_available(qtbot, monkeypatch):
    window, voice = make_bridge(qtbot, monkeypatch)
    environment = QProcessEnvironment.systemEnvironment()
    for name in ("VOLC_SPEECH_API_KEY", "VOLC_ASR_API_KEY", "VOLC_TTS_API_KEY"):
        environment.insert(name, "")
    voice.process.setProcessEnvironment(environment)
    voice.toggle()
    qtbot.waitUntil(lambda: voice.process.state() == QProcess.NotRunning, timeout=10000)
    qtbot.waitUntil(lambda: "VOLC_SPEECH_API_KEY" in voice.log.toPlainText())
    assert not voice.enabled
    assert window._voice_button.text() == "开启语音"
    assert window._stack.currentWidget() is window._setup_view


def test_voice_agent_config_and_report_callbacks_use_current_turn(qtbot, monkeypatch):
    from dataclasses import asdict
    from tests.test_report_analysis_ui import _report, _FakeAnalysisClient
    window, voice = make_bridge(qtbot, monkeypatch)
    class Client(_FakeLlmClient):
        is_running = True
        def worker_status(self, timeout=0.25):
            return "ready"
        def chat(self, message, athlete, agent_mode="jump"):
            assert message == "帮我配置连续纵跳十次"
            return {"config": asdict(default_jump_config()), "reply": "配置建议"}
    panel = window._setup_view._agent_panel
    panel._llm_client = Client()
    panel._worker_ready = True
    spoken = QSignalSpy(voice.spoken)
    voice.handle_text("帮我配置连续纵跳十次")
    qtbot.waitUntil(lambda: panel._pending_config is not None)
    assert "正在生成" in spoken.at(0)[0]
    assert "建议配置已生成" in spoken.at(1)[0]
    assert window._setup_view._current_config is None
    voice.handle_text("确认配置")
    assert window._setup_view._current_config is panel._pending_config

    report_view = window._report_view
    report_view._llm_client = _FakeAnalysisClient()
    report_view.load_report(_report(), 12)
    report_view.set_analysis_availability(True)
    window._stack.setCurrentWidget(report_view)
    qtbot.waitUntil(lambda: not report_view._analysis_workers)
    voice.handle_text("分析报告")
    qtbot.waitUntil(lambda: any("后半程触地时间" in spoken.at(i)[0] for i in range(spoken.count())))
    assert report_view._llm_client.analyze_calls[0][0] == 12
    assert "co_change_is_not_causation" in spoken.at(spoken.count() - 1)[0]


def test_voice_gait_session_persists_answers_and_exports(qtbot, tmp_path, monkeypatch):
    """ASR-final IPC through simulation, real engine, history and Excel; no cloud/audio."""
    from openpyxl import load_workbook
    from ui.demo import DemoWindow
    import ui.views.report_view as report_module

    window = DemoWindow(db_path=tmp_path / "demo.sqlite3", enable_voice=True)
    qtbot.addWidget(window)
    voice = VoiceBridge(window)
    window._voice = voice
    voice.enabled = True
    spoken = QSignalSpy(voice.spoken)
    controller = window._controller
    turn = 0

    def utterance(text):
        nonlocal turn
        turn += 1
        voice.handle_event({"type": "transcript", "text": text, "final": True, "turn": turn})

    try:
        utterance("准备测试")
        qtbot.waitUntil(lambda: controller.device_state == "connected")
        utterance("开始")
        qtbot.waitUntil(lambda: controller.is_running and voice.pending is None)
        utterance("开始")
        assert "已在运行" in spoken.at(spoken.count() - 1)[0]
        qtbot.waitUntil(lambda: len(controller.engine._export_frames) > 4200, timeout=7000)
        utterance("暂停")
        qtbot.waitUntil(lambda: controller.is_paused and voice.pending is None)
        count = len(controller.engine._export_frames)
        qtbot.wait(150)
        assert len(controller.engine._export_frames) == count
        utterance("继续")
        qtbot.waitUntil(lambda: not controller.is_paused and voice.pending is None)
        qtbot.waitUntil(lambda: len(controller.engine._export_frames) > count + 4200, timeout=7000)
        utterance("结束")
        assert controller.engine is None
        assert controller._thread is None
        records = window._subject_store.get_all_sessions()
        assert len(records) == 1
        saved = window._subject_store.get_session(records[0].id)
        assert saved.report.report_config_snapshot["pause_boundaries_s"]
        window._go_to_history()
        window._on_history_open_report(saved)
        assert "模拟数据" in window._report_view._title.text()
        for question in ("左右脚差异怎么样", "步频稳定吗", "后半程有什么变化", "具体证据呢"):
            utterance(question)
            answer = spoken.at(spoken.count() - 1)[0]
            full_answer = window._report_view._gait_answer.toPlainText()
            spoken_content = answer.removesuffix("其余详情见页面。")
            assert full_answer.replace("\n", "").startswith(spoken_content)
            assert "点击定位证据" in full_answer
            assert "模拟" in answer
        monkeypatch.setattr(report_module, "_get_base_dir", lambda: str(tmp_path))
        monkeypatch.setattr(report_module.QMessageBox, "question", lambda *a, **k: report_module.QMessageBox.Yes)
        monkeypatch.setattr(report_module.QMessageBox, "information", lambda *a, **k: None)
        errors = []
        monkeypatch.setattr(report_module.QMessageBox, "warning", lambda *a, **k: errors.append(a))
        window._report_view._on_export()
        assert not errors
        files = list((tmp_path / "data").glob("*.xlsx"))
        assert len(files) == 1
        with files[0].open("rb") as stream:
            book = load_workbook(stream)
            assert "非受试者实测" in book["数据来源"].cell(1, 2).value
            book.close()
    finally:
        window.close()


def test_voice_config_summary_reads_values_before_confirmation():
    from ui.views.agent_config_panel import AgentConfigPanel
    from config.treadmill_config import TreadmillGaitConfig
    config = TreadmillGaitConfig(stop_type="End of Time", test_length="10:05", treadmill_speed=3.6)
    summary = AgentConfigPanel._spoken_config_summary(config)
    assert "3.6" in summary
    assert "10分5秒" in summary
    assert "确认配置后应用" in summary


def test_demo_agent_uses_project_interpreter_and_gait_mode(qtbot, tmp_path, monkeypatch):
    import sys
    from ui.demo import DemoWindow
    from ui.llm_client import AgentWorkerClient
    monkeypatch.setattr(AgentWorkerClient, "start", lambda self: False)
    window = DemoWindow(db_path=tmp_path / "agent-demo.sqlite3", enable_voice=True, enable_agent=True)
    qtbot.addWidget(window)
    assert window._llm_client._python_exe == sys.executable
    assert window._setup_view._agent_panel._current_agent_mode() == "treadmill_gait"
    assert getattr(window._llm_client, "configuration_enabled", True)
    window.close()
