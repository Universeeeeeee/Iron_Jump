"""Windows pipe encoding and pythonw launch regressions, without live audio."""
import io
import json
import sys

from voice.__main__ import emit
from ui.voice_bridge import _worker_command
from tests.test_voice_session import make_bridge


def test_chinese_transcript_survives_gbk_stdout(monkeypatch):
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="gbk")
    monkeypatch.setattr(sys, "stdout", stdout)
    event = {"type": "transcript", "text": "配置地面走路测试", "turn": 1, "final": True}
    emit(event)
    assert json.loads(raw.getvalue()) == event
    assert raw.getvalue().isascii()


def test_pythonw_worker_uses_same_environment_console_python(monkeypatch, tmp_path):
    console = tmp_path / "python.exe"
    console.touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    program, args = _worker_command()
    assert program == str(console)
    assert args == ["-X", "utf8", "-u", "-m", "voice", "--worker"]


def test_missing_console_python_is_explicit(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    with pytest.raises(RuntimeError, match="python.exe"):
        _worker_command()


def test_chinese_reply_is_ascii_json_for_worker_stdin(qtbot, monkeypatch):
    window, bridge = make_bridge(qtbot, monkeypatch)
    from qtpy.QtCore import QProcess
    received = []
    monkeypatch.setattr(bridge.process, "state", lambda: QProcess.Running)
    monkeypatch.setattr(bridge.process, "write", received.append)
    bridge._write({"type": "speak", "text": "语音已开启，请说", "turn": 1})
    assert received[0].isascii()
    assert json.loads(received[0].decode("gbk"))["text"] == "语音已开启，请说"
    monkeypatch.setattr(bridge.process, "state", lambda: QProcess.NotRunning)


def test_transcript_pipe_reaches_business_router(qtbot, monkeypatch):
    window, bridge = make_bridge(qtbot, monkeypatch)
    payload = {"type": "transcript", "text": "地面走路", "final": True, "turn": 1}
    raw = (json.dumps(payload, ensure_ascii=True) + '\n').encode('gbk')
    monkeypatch.setattr(bridge.process, "readAllStandardOutput", lambda: raw)
    calls = []
    monkeypatch.setattr(bridge, "handle_text", calls.append)
    bridge._read()
    assert calls == ["地面走路"]
    assert "地面走路" in window._voice_panel.transcript.text()


def test_bad_pipe_encoding_is_visible_and_startup_timeout_stops_waiting(qtbot, monkeypatch):
    window, bridge = make_bridge(qtbot, monkeypatch)
    raw = (json.dumps({"type": "error", "message": "中文错误"}, ensure_ascii=False) + '\n').encode('gbk')
    monkeypatch.setattr(bridge.process, "readAllStandardOutput", lambda: raw)
    bridge._read()
    assert "消息解析失败" in window._voice_panel.reply.text()
    bridge.startup_timer.start(60000)
    bridge._startup_timed_out()
    assert not bridge.enabled
    assert not bridge.startup_timer.isActive()
    assert "60 秒" in window._voice_panel.reply.text()


def test_ready_cancels_startup_timeout(qtbot, monkeypatch):
    window, bridge = make_bridge(qtbot, monkeypatch)
    bridge.startup_timer.start(60000)
    bridge.handle_event({"type": "ready"})
    assert not bridge.startup_timer.isActive()


def test_blank_lines_and_split_transcript_keep_following_events(qtbot, monkeypatch):
    window, bridge = make_bridge(qtbot, monkeypatch)
    event = {"type": "transcript", "text": "地面走路", "final": True, "turn": 1}
    raw = (json.dumps(event, ensure_ascii=True) + '\r\n').encode('ascii')
    chunks = iter([b'\r\n  \n' + raw[:20], raw[20:]])
    monkeypatch.setattr(bridge.process, "readAllStandardOutput", lambda: next(chunks))
    calls = []
    monkeypatch.setattr(bridge, "handle_text", calls.append)
    bridge._read()
    assert calls == []
    assert not window._voice_panel.reply.text()
    bridge._read()
    assert calls == ["地面走路"]


def test_invalid_message_is_reported_without_dropping_next_transcript(qtbot, monkeypatch):
    window, bridge = make_bridge(qtbot, monkeypatch)
    event = {"type": "transcript", "text": "地面跑步", "final": True, "turn": 1}
    raw = b'not-json\n' + (json.dumps(event) + '\n').encode('ascii')
    monkeypatch.setattr(bridge.process, "readAllStandardOutput", lambda: raw)
    calls = []
    monkeypatch.setattr(bridge, "handle_text", calls.append)
    bridge._read()
    assert "消息解析失败" in window._voice_panel.diagnostics.toPlainText()
    assert calls == ["地面跑步"]


def test_real_subprocess_pipe_roundtrip_with_windows_encoding(qtbot, monkeypatch):
    from qtpy.QtCore import QProcess, QProcessEnvironment
    window, bridge = make_bridge(qtbot, monkeypatch)
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONIOENCODING", "gbk")
    bridge.process.setProcessEnvironment(env)
    calls = []
    monkeypatch.setattr(bridge, "handle_text", calls.append)
    code = (
        'import sys,json; from voice.__main__ import emit; '
        'value=json.loads(sys.stdin.readline()); '
        'emit({"type":"transcript","text":value["text"],"final":True,"turn":1})'
    )
    bridge.process.start(sys.executable, ["-u", "-c", code])
    qtbot.waitUntil(lambda: bridge.process.state() == QProcess.Running, timeout=5000)
    bridge._write({"type": "speak", "text": "配置地面走路", "turn": 1})
    qtbot.waitUntil(lambda: bool(calls), timeout=5000)
    assert calls == ["配置地面走路"]
    qtbot.waitUntil(lambda: bridge.process.state() == QProcess.NotRunning, timeout=5000)
