"""Ground config follows the same validated service and UI flow as other modes."""
import time

import pytest
from pydantic import ValidationError

from agent.config.agent import LLMConfigAgent
from agent.config.models import AthleteProfile, LLMWalkingConfig, LLMOvergroundRunningConfig, LLMTestConfig
from agent.config.rule_engine import RuleEngine
from agent.config.service import ConfigService
from config.config_validation import validate_runtime_config
from config.test_config import config_from_dict
from tests.test_llm_agent_regressions import _FakeRunResult
from tests.test_agent_config_panel import _FakeClient
from tests.test_voice_session import make_bridge
from ui.views.agent_config_panel import AgentConfigPanel, _LLMHttpWorker

GROUND = [("walking", LLMWalkingConfig), ("overground_running", LLMOvergroundRunningConfig)]


@pytest.mark.parametrize("mode,model", GROUND)
@pytest.mark.parametrize("stop", ["Status change", "Software command"])
def test_ground_config_roundtrip_and_technical_policy(mode, model, stop):
    config = model(stop_type=stop, starting_foot="Left").to_test_config()
    assert config_from_dict(config.to_dict()) == config
    assert validate_runtime_config(config) == []
    config.confirmation_ms = 99
    profile = AthleteProfile(age=65, weight=70, height=170, level="beginner")
    normalized = RuleEngine().normalize_runtime_config(config, profile)
    assert normalized.stop_type == stop
    assert normalized.starting_foot == "Left"
    assert normalized.confirmation_ms == model().to_test_config().confirmation_ms
    assert normalized.min_contact_time == model().to_test_config().min_contact_time


@pytest.mark.parametrize("mode,model", GROUND)
@pytest.mark.parametrize("values", [
    {"stop_type": "End of Time"}, {"treadmill_speed": 3}, {"number_of_jumps": 5},
    {"starting_foot": "Both"}, {"segment_count": 8}, {"confirmation_ms": 1},
])
def test_ground_model_rejects_unsupported_parameters(mode, model, values):
    with pytest.raises(ValidationError):
        model(**values)


@pytest.mark.parametrize("mode,model", GROUND)
@pytest.mark.parametrize("stream", [False, True])
def test_ground_service_generate_modify_and_show_config(monkeypatch, mode, model, stream):
    class FakeAgent:
        async def run(self, user_message, **kwargs):
            output = model(stop_type="Software command", starting_foot="Right") if "修改" in user_message else model()
            return _FakeRunResult(output)

    monkeypatch.setattr(LLMConfigAgent, "_make_agent", staticmethod(lambda client, mode: FakeAgent()))
    service = ConfigService(mode="online")
    profile = AthleteProfile(age=30, weight=70, height=170)
    def call(message):
        return service.chat_stream(message, profile, mode, lambda _: None) if stream else service.chat(message, profile, mode)
    first, reply = call("请配置地面测试")
    assert first.test_type == model().test_type
    assert first.stop_type == "Status change"
    assert "空场自动结束" in reply
    assert "跳跃次数" not in reply
    modified, reply = call("修改配置为右脚先进入，手动结束")
    assert modified.starting_foot == "Right"
    assert modified.stop_type == "Software command"
    none, reply = call("查看当前配置")
    assert none is None
    assert "Right" in reply


def test_unknown_mode_and_cross_mode_output_are_rejected():
    with pytest.raises(ValueError, match="不支持"):
        ConfigService().llm_agent_for("invalid")
    agent = LLMConfigAgent("walking")
    config, reply = agent._finalize_config_output(LLMTestConfig(), time.perf_counter(), [])
    assert config is None
    assert "模式不一致" in reply


@pytest.mark.parametrize("mode,model", GROUND)
@pytest.mark.parametrize("voice", [False, True])
def test_ground_ui_request_confirm_and_apply(qtbot, monkeypatch, mode, model, voice):
    window, bridge = make_bridge(qtbot, monkeypatch)
    setup = window._setup_view
    panel = setup._agent_panel
    calls = []
    class Client(_FakeClient):
        def chat(self, message, athlete, agent_mode="jump"):
            calls.append(agent_mode)
            return {"config": model(starting_foot="Left").to_test_config().to_dict(), "reply": "已生成建议"}
    panel._llm_client = Client()
    panel._worker_ready = True
    panel._test_type_combo.setCurrentIndex(panel._test_type_combo.findData(mode))
    original = setup._current_config
    if voice:
        bridge.handle_text("帮我配置地面测试")
    else:
        panel._chat_input.setText("帮我配置地面测试")
        panel._on_send_message()
    qtbot.waitUntil(lambda: panel._llm_worker is None, timeout=5000)
    assert calls == [mode]
    assert setup._current_config is original
    assert panel._pending_config.test_type == model().test_type
    assert "空场自动结束" in panel._suggestion_text.text()
    if voice:
        bridge.handle_text("确认配置")
    else:
        panel._on_confirm_clicked()
    assert setup._current_config.test_type == model().test_type
    assert setup._current_config.starting_foot == "Left"
    assert not setup._config_errors


def test_switch_away_and_back_does_not_restore_late_pending_config(qtbot, monkeypatch):
    panel = AgentConfigPanel(llm_client=_FakeClient())
    qtbot.addWidget(panel)
    panel._test_type_combo.setCurrentIndex(panel._test_type_combo.findData("walking"))
    monkeypatch.setattr(_LLMHttpWorker, "start", lambda self: None)
    panel.submit_voice("配置地面走路")
    worker = panel._llm_worker
    panel._test_type_combo.setCurrentIndex(panel._test_type_combo.findData("jump"))
    panel._test_type_combo.setCurrentIndex(panel._test_type_combo.findData("walking"))
    worker.finished.emit(LLMWalkingConfig().to_test_config(), "旧建议")
    assert panel._pending_config is None
    assert "旧建议" in panel._chat_display.toPlainText()


@pytest.mark.parametrize("mode,model", GROUND)
def test_manual_ground_mode_is_preserved_when_voice_opens_assistant(qtbot, monkeypatch, mode, model):
    window, bridge = make_bridge(qtbot, monkeypatch)
    setup = window._setup_view
    setup._set_config_mode(1)
    setup._set_current_config(model().to_test_config(), "manual")
    seen = []
    monkeypatch.setattr(setup._agent_panel, "submit_voice", lambda text: seen.append(
        setup._agent_panel._current_agent_mode()) or True)
    bridge.handle_text("帮我修改配置")
    assert seen == [mode]
    assert setup._config_mode_index == 0


@pytest.mark.parametrize("mode,model", GROUND)
def test_ground_intent_disagreement_requires_clarification(monkeypatch, mode, model):
    from tests.test_llm_agent_regressions import _FakeSequenceAgent
    outputs = [model(starting_foot=foot) for foot in ("Left", "Right", "Left")]
    fake = _FakeSequenceAgent(outputs)
    monkeypatch.setattr(LLMConfigAgent, "_make_agent", staticmethod(lambda client, mode: fake))
    config, reply = LLMConfigAgent(mode).chat("帮我配置地面测试", AthleteProfile(age=30, weight=70, height=170))
    assert config is None
    assert "起始脚" in reply
