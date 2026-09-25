import gzip
import json
import struct

import pytest

from voice.command_router import match_command
from voice.protocol import asr_request, asr_response, tts_request, tts_response, Utterances, SpeechProtocolError
from voice.settings import VoiceSettings
from voice.responses import analysis_speech


@pytest.mark.parametrize("text,command", [
    ("开始", "start"), ("请开始测试。", "start"), ("暂停", "pause"),
    ("先暂停", "pause"), ("暂停一下！", "pause"), ("继续", "resume"),
    ("继续测试", "resume"), ("结束测试", "stop"), ("停止", "stop"),
    ("确认配置", "confirm"), ("准备测试", "prepare"), ("分析报告", "report"),
    ("不要开始", None), ("暂停测试这个功能是怎么实现的？", None),
    ("继续测试会怎样", None), ("开始测试然后暂停", None), ("别暂停", None),
    ("帮我配置连续纵跳十次", None), ("嗯", None),
])
def test_whole_utterance_routing(text, command):
    assert match_command(text) == command


def test_asr_wire_request_and_negative_final_sequence():
    packet = asr_request({"request": {"model_name": "bigmodel"}}, 1)
    assert packet[:4] == b"\x11\x11\x11\0"
    assert struct.unpack(">iI", packet[4:12]) == (1, len(packet) - 12)
    assert json.loads(gzip.decompress(packet[12:]))["request"]["model_name"] == "bigmodel"
    packet = asr_request(b"\0\1" * 320, 2, last=True)
    assert packet[1] == 0x23
    assert struct.unpack(">i", packet[4:8])[0] == -2
    assert gzip.decompress(packet[12:]) == b"\0\1" * 320


def test_asr_server_fixture_and_malformed_response():
    body = gzip.compress(json.dumps({"result": {"text": "暂停"}}).encode())
    packet = b"\x11\x93\x11\0" + struct.pack(">iI", -4, len(body)) + body
    assert asr_response(packet) == ({"result": {"text": "暂停"}}, True)
    with pytest.raises(SpeechProtocolError):
        asr_response(packet[:-2])
    with pytest.raises(SpeechProtocolError, match="代码 45000000"):
        asr_response(b"\x11\xf0\x10\0" + struct.pack(">II", 45000000, 0))


def test_definite_segments_are_not_executed_twice_or_deduped_by_text():
    seen = Utterances()
    def payload(text, end, definite):
        return {"result": {"utterances": [{"text": text, "end_time": end, "definite": definite}]}}
    assert list(seen.extract(payload("暂停", 400, False))) == [("暂停", False)]
    assert list(seen.extract(payload("暂停", 500, True))) == [("暂停", True)]
    assert list(seen.extract(payload("暂停", 500, True))) == []
    assert list(seen.extract(payload("暂停", 1500, True))) == [("暂停", True)]


def test_tts_event_wire_fixtures():
    packet = tts_request(1, {})
    assert packet == b"\x11\x14\x10\0" + struct.pack(">II", 1, 2) + b"{}"
    packet = tts_request(100, {}, "sid")
    assert packet[8:15] == b"\0\0\0\3sid"
    connected = b"\x11\x94\x10\0" + struct.pack(">II", 50, 4) + b"conn" + struct.pack(">I", 2) + b"{}"
    assert tts_response(connected).session_id == ""
    audio = b"\x11\xb4\0\0" + struct.pack(">II", 352, 3) + b"sid" + struct.pack(">I", 4) + b"\0\1\0\2"
    message = tts_response(audio)
    assert (message.event, message.session_id, message.payload) == (352, "sid", b"\0\1\0\2")
    with pytest.raises(SpeechProtocolError):
        tts_response(audio[:-1])


def test_missing_credentials_are_actionable_and_never_print_keys(monkeypatch):
    for name in ("VOLC_SPEECH_API_KEY", "VOLC_ASR_API_KEY", "VOLC_TTS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="VOLC_SPEECH_API_KEY"):
        VoiceSettings.from_env()
    monkeypatch.setenv("VOLC_SPEECH_API_KEY", "test-secret")
    settings = VoiceSettings.from_env()
    assert settings.headers("asr")["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
    assert "test-secret" not in repr(settings)


def test_report_speech_retains_claim_and_global_limits():
    result = analysis_speech({"claims": [{"text": "结果一", "limitations": ["样本少"]}],
                              "overall_limitations": ["不能用于诊断"]})
    assert "结果一" in result and "样本少" in result and "不能用于诊断" in result
def test_social_intents_cannot_swallow_commands_or_configuration_requests():
    from voice.command_router import conversational_reply
    assert conversational_reply("喂，你好你好。") is not None
    for text in ("不要开始", "你好，开始测试", "暂停测试怎么实现", "帮我配置十次纵跳", "不需要帮助"):
        assert conversational_reply(text) is None
