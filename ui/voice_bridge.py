"""Qt-thread business routing and subprocess lifecycle for optional voice."""

import json
from pathlib import Path
import sys
import time

from qtpy.QtCore import QObject, QProcess, QTimer, Signal

from config.config_validation import validate_runtime_config
from voice.command_router import conversational_reply, match_command
from voice.replies import concise_reply


def _worker_command():
    executable = Path(sys.executable)
    if executable.name.lower() in {"pythonw.exe", "pythonw"}:
        executable = executable.with_name("python.exe" if executable.suffix else "python")
        if not executable.is_file():
            raise RuntimeError("未找到语音子进程所需的 python.exe，请检查 Python 安装。")
    return str(executable), ["-X", "utf8", "-u", "-m", "voice", "--worker"]


class VoiceBridge(QObject):
    spoken = Signal(str)  # text feedback remains observable when TTS fails

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.controller = window._controller
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._drain_stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.buffer = bytearray()
        self.turn = 0
        self.pending = None
        self.agent_turn = None
        self.report_turn = None
        self.enabled = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timed_out)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self._startup_timed_out)
        self.started_at = 0.0
        self.panel = window._voice_panel
        self.log = self.panel.diagnostics
        self.last_error = None
        self.controller.session_started.connect(self._started)
        self.controller.session_finished.connect(self._session_finished)
        self.controller.pause_state_changed.connect(self._paused)
        self.controller.device_state_changed.connect(self._device_changed)
        window._setup_view._agent_panel.voice_reply.connect(self._agent_reply)
        window._report_view.voice_reply.connect(self._report_reply)

    def toggle(self):
        if self.process.state() != QProcess.NotRunning:
            self.close()
            return
        self.enabled = True
        self.last_error = None
        self.panel.set_state("正在连接语音…")
        self.panel.reply.hide()
        self.panel.transcript.hide()
        self.turn = 0
        self.buffer.clear()
        self.window._voice_button.setText("关闭语音（连接中）")
        self.log.appendPlainText("正在连接豆包语音并初始化回声消除…")
        try:
            executable, args = _worker_command()
        except RuntimeError as exc:
            self.handle_event({"type": "error", "message": str(exc)})
            self._finished()
            return
        self.startup_timer.start(60000)
        self.process.start(executable, args)

    def _write(self, value):
        if self.process.state() == QProcess.Running:
            self.process.write((json.dumps(value, ensure_ascii=True) + "\n").encode("ascii"))

    def say(self, text, turn=None):
        if not self.enabled or (turn is not None and turn != self.turn):
            return
        text = concise_reply(text)
        self.panel.show_reply(text)
        self.log.appendPlainText("助手：" + text)
        self.spoken.emit(text)
        self._write({"type": "speak", "text": text, "turn": self.turn})

    def _read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b"\n" in self.buffer:
            raw, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            if not raw.strip():
                continue
            try:
                self.handle_event(json.loads(raw))
            except (ValueError, KeyError, TypeError):
                self.handle_event({"type": "error", "message": "语音消息解析失败，请同步最新代码并完全重启应用；若仍无文字，请查看语音诊断。"})

    def handle_event(self, event):
        if not self.enabled:
            return
        kind = event["type"]
        if kind in {"turn", "transcript"} and event.get("turn", self.turn) < self.turn:
            return
        if kind == "ready":
            self.startup_timer.stop()
            if event.get("aec"):
                self.log.appendPlainText("已启用 WebRTC AEC3 声学回声消除与降噪。")
            self.window._voice_button.setText("关闭语音")
            self.panel.set_state("正在聆听")
            self.panel.interrupt_button.setEnabled(True)
            self.say("语音已开启，请说。")
        elif kind == "turn":
            self.turn = event["turn"]
            self.panel.set_state("正在聆听")
        elif kind == "transcript":
            self.panel.show_transcript(event["text"], event["final"])
            if event["final"]:
                self.turn = event["turn"]
                self.log.appendPlainText("你：" + event["text"])
                self.handle_text(event["text"])
        elif kind == "error":
            self.last_error = event["message"]
            self.panel.show_reply(event["message"])
            self.panel.set_state("语音异常 · 查看提示")
            self.log.appendPlainText(event["message"])
            self.window.statusBar().showMessage(event["message"], 15000)
        elif kind == "metric":
            self.log.appendPlainText(f"TTS 首包：{event['value']} ms（不含 ASR 和实际播放延迟）")

    def handle_text(self, text):
        command = match_command(text)
        c, w = self.controller, self.window
        social_reply = conversational_reply(text)
        if social_reply:
            self.say(social_reply)
            return
        if command == "interrupt":
            # The worker already cancelled playback on the first ASR partial.
            return
        if command in {"start", "pause", "resume", "stop"}:
            if self.pending and not (command == "stop" and c.is_running):
                self.say("正在执行，请稍候。")
                return
            if command == "start":
                if c.is_running:
                    self.say("测试已在运行。" if not c.is_paused else "测试已暂停，请说继续。")
                elif w._stack.currentWidget() is not w._exec_view:
                    self.say("请先确认配置并说准备测试。")
                elif c.device_state != "connected":
                    self.say("设备尚未就绪，不能开始测试。")
                elif getattr(c, "quality_status", {}).get("requires_acknowledgement"):
                    self.say("检测到阈值内的异常光束。请查看异常位置，现场确认空场，并在界面点击降级开始。")
                elif (c.config.test_type in {"Sprint and Gait Test", "Overground Running Test"}
                      and not c._walking_ready):
                    self.say("空场自检尚未通过，请保持测量区域无遮挡，等待界面提示就绪后再开始。")
                elif c.config.test_type in {"Sprint and Gait Test", "Overground Running Test"}:
                    self.say("请核对界面显示的设备段数，并点击“确认共 N 段并开始”。")
                else:
                    self._wait_for("start")
                    w._on_start()
            elif not c.is_running:
                self.say("当前没有运行中的测试。")
            elif command in {"pause", "resume"} and c.config.test_type in {
                "Sprint and Gait Test", "Overground Running Test"
            }:
                self.say("地面单次通过不支持暂停或继续；可说结束测试，停步会保留在本次记录中。")
            elif command == "pause" and c.is_paused:
                self.say("测试已经暂停。")
            elif command == "resume" and not c.is_paused:
                self.say("测试已经在运行。")
            else:
                self._wait_for(command)
                {"pause": c.pause, "resume": c.resume, "stop": w._on_manual_stop}[command]()
        elif command == "confirm":
            setup = w._setup_view
            config = setup._agent_panel._pending_config
            if c.is_running or w._stack.currentWidget() is not setup:
                self.say("请返回配置页面后再确认配置。")
            elif setup._config_mode_index != 0:
                self.say("当前为手动配置，请先进入智能配置生成建议。")
            elif config is None:
                self.say("还没有建议配置，请先描述测试要求。")
            elif (config.test_type != setup._agent_panel.current_test_type()
                  or validate_runtime_config(config)):
                self.say("配置校验未通过，请查看参数提示。")
            else:
                setup._agent_panel._on_confirm_clicked()
                if setup._current_config is config and not setup._config_errors:
                    self.say("配置已应用。可以说准备测试。")
                else:
                    self.say("配置未能应用，请检查界面。")
        elif command == "prepare":
            setup = w._setup_view
            if w._stack.currentWidget() is not setup or not setup.btn_ready.isEnabled():
                self.say("请在配置页确认有效配置和本次测试身份。")
            else:
                setup._on_ready_clicked()
                if w._stack.currentWidget() is w._exec_view:
                    self.say("准备中，就绪后请说开始。")
        elif command == "setup":
            if c.is_running:
                self.say("请先结束当前测试。")
            else:
                w._on_return_to_config()
                self.say("已返回配置页面。")
        elif command == "report":
            if w._stack.currentWidget() is not w._report_view:
                self.say("请先结束测试或打开一份历史报告。")
            elif w._report_view.request_voice_analysis():
                self.report_turn = self.turn
                self.panel.set_state("正在分析报告…")
                self.say("正在分析报告，请稍候。")
            else:
                self.say("分析尚未就绪，请查看页面提示。")
        elif w._stack.currentWidget() in {w._setup_view, w._exec_view}:
            if c.is_running:
                self.say("测试正在运行。更改测试模式或配置前，请先结束当前测试。")
                return
            if w._stack.currentWidget() is w._exec_view:
                w._on_return_to_config()
            panel = w._setup_view._agent_panel
            w._setup_view._set_config_mode(0)
            if panel.submit_voice(text):
                self.agent_turn = self.turn
                self.panel.set_state("正在生成配置…")
                self.say("正在生成配置。")
            else:
                status = panel.voice_submission_status
                if status == "disabled":
                    self.say("当前演示未启用智能配置，请使用手动配置。")
                elif status == "busy":
                    self.say("上一条配置建议正在生成，请稍候。")
                else:
                    self.say("智能配置未连接，请检查服务或手动配置。")
        elif w._stack.currentWidget() is w._report_view:
            self.say(w._report_view.answer_gait_question(text))
        else:
            self.say("测试控制可以说开始、暂停、继续或结束；报告页可以说分析报告。")

    def _wait_for(self, command):
        self.started_at = time.perf_counter()
        self.pending = (command, self.turn)
        self.panel.set_state("等待设备确认…")
        self.timer.start(5000)

    def _ack(self, command, text):
        if self.pending and self.pending[0] == command:
            _, turn = self.pending
            self.pending = None
            self.timer.stop()
            elapsed = round((time.perf_counter() - self.started_at) * 1000)
            self.log.appendPlainText(f"控制执行确认：{elapsed} ms（从最终识别文本到执行确认）")
            self.panel.show_reply(text)
            self.panel.set_state("正在聆听" if self.enabled else "麦克风已关闭")
            self.say(text, turn)

    def _started(self):
        self._ack("start", "测试已开始。")

    def _paused(self, paused):
        self._ack("pause" if paused else "resume", "测试已暂停。" if paused else "测试已继续。")

    def _session_finished(self, report):
        text = "测试已结束，报告已生成。"
        count = getattr(report, "touch_count", None)
        if count is not None:
            text = f"测试已结束，共记录{count}次触地，报告已生成。"
        if self.pending and self.pending[0] == "stop":
            self._ack("stop", text)
        else:
            self.pending = None
            self.timer.stop()
            if self.enabled:
                self.panel.set_state("正在聆听")
            self.say(text)

    def _device_changed(self, state, message):
        if state == "error" and self.pending:
            self.pending = None
            self.timer.stop()
            self.panel.set_state("设备异常 · 查看提示")
            self.say("设备发生错误，控制指令未确认执行，请查看设备状态。")

    def _timed_out(self):
        self.pending = None
        self.panel.set_state("执行未确认 · 查看提示")
        self.say("尚未收到设备执行确认，请检查测试状态，不要重复开始。")

    def _agent_reply(self, text):
        if self.agent_turn is not None:
            if self.agent_turn == self.turn and self.enabled:
                self.panel.set_state("正在聆听")
            self.say(text, self.agent_turn)
            self.agent_turn = None

    def _report_reply(self, text):
        if self.report_turn is not None:
            if self.report_turn == self.turn and self.enabled:
                self.panel.set_state("正在聆听")
            self.say(text, self.report_turn)
            self.report_turn = None

    def interrupt_speech(self):
        if not self.enabled:
            return
        self.turn += 1
        self.agent_turn = self.report_turn = None
        self._write({"type": "interrupt", "turn": self.turn})
        self.panel.set_state("正在聆听")
        self.panel.show_reply("已请求停止播报，测试状态不变。")

    def _drain_stderr(self):
        self.process.readAllStandardError()  # Pipecat diagnostics must not block the worker pipe.

    def _process_error(self, error):
        if not self.enabled:
            return
        self.last_error = "语音进程无法启动或意外退出，请检查安装环境。"
        self.panel.show_reply(self.last_error)
        self._finished()

    def _startup_timed_out(self):
        if not self.enabled:
            return
        self.handle_event({"type": "error", "message": "语音启动超过 60 秒仍未就绪，请检查音频设备、语音依赖和 ASR 网络后重新开启。"})
        self.process.kill()
        self._finished()

    def _finished(self, *_args):
        self.startup_timer.stop()
        if self.enabled and self.last_error is None:
            self.last_error = "语音连接已结束，可重新开启；手动操作仍可使用。"
            self.panel.show_reply(self.last_error)
        self.enabled = False
        self.pending = None
        self.agent_turn = self.report_turn = None
        self.timer.stop()
        self.window._voice_button.setText("开启语音")
        self.panel.interrupt_button.setEnabled(False)
        self.panel.set_state("语音未连接 · 查看提示" if self.last_error else "麦克风已关闭")

    def close(self):
        self.startup_timer.stop()
        self.enabled = False
        self.last_error = None
        self.agent_turn = self.report_turn = None
        self.timer.stop()
        if self.process.state() != QProcess.NotRunning:
            self._write({"type": "stop"})
            if not self.process.waitForFinished(1500):
                self.process.kill()
                self.process.waitForFinished(1000)
        self._finished()
