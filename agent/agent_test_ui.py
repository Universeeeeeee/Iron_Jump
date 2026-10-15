"""
agent_test_ui.py — Agent 参数配置独立测试工具

用 dayu_widgets 构建，验证离线（规则引擎）和在线（LLM）两种模式。
与主 UI 完全解耦，不依赖硬件模块。

使用方式::

    python -m agent.agent_test_ui
"""

from __future__ import annotations

import time
import traceback

from qtpy.QtCore import Qt, Signal, QThread
from qtpy.QtGui import QTextCursor
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QComboBox, QSizePolicy, QSplitter, QTextEdit,
)

from dayu_widgets.divider import MDivider
from dayu_widgets.label import MLabel
from dayu_widgets.spin_box import MSpinBox, MDoubleSpinBox
from dayu_widgets.push_button import MPushButton
from dayu_widgets.line_edit import MLineEdit
from dayu_widgets.qt import application
from dayu_widgets import dayu_theme

from agent import GaitAgent, AthleteProfile
from markdown_it import MarkdownIt

_md = MarkdownIt().enable("table")

def _md_to_html(text: str) -> str:
    """将 LLM 回复中的 markdown 转为 QTextEdit 可渲染的 HTML。"""
    # 去掉末尾的 ⏱ 计时行（它不需要渲染为 markdown）
    return _md.render(text)


# ---- LLM 调用线程 ----

class LLMWorker(QThread):
    """在子线程中执行 LLM 调用，text_chunk 逐 token 推送流式文本。"""
    text_chunk = Signal(str)     # 流式文本增量
    finished = Signal(object, str)  # (TestConfig | None, reply_text)
    error = Signal(str)

    def __init__(self, agent: GaitAgent, message: str, ctx: AthleteProfile):
        super().__init__()
        self._agent = agent
        self._message = message
        self._ctx = ctx

    def run(self):
        try:
            config, reply = self._agent.chat_online_stream(
                self._message, self._ctx,
                on_chunk=lambda text: self.text_chunk.emit(text),
            )
            self.finished.emit(config, reply)
        except Exception as e:
            self.error.emit(f"{e}\n{traceback.format_exc()}")


class WarmupWorker(QThread):
    """后台初始化在线 Agent，避免切到在线模式时阻塞 UI。"""
    ready = Signal()
    error = Signal(str)

    def __init__(self, agent: GaitAgent):
        super().__init__()
        self._agent = agent

    def run(self):
        try:
            self._agent.warmup_online()
            self.ready.emit()
        except Exception as e:
            self.error.emit(f"{e}\n{traceback.format_exc()}")


# ---- 用户信息面板 ----

class AthletePanel(QWidget):
    """用户运动档案输入面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(MDivider("用户信息"))

        grid = QGridLayout()
        grid.setSpacing(8)

        # 年龄
        self.age_spin = MSpinBox()
        self.age_spin.setRange(1, 120)
        self.age_spin.setValue(30)
        grid.addWidget(MLabel("年龄"), 0, 0)
        grid.addWidget(self.age_spin, 0, 1)

        # 体重
        self.weight_spin = MDoubleSpinBox()
        self.weight_spin.setRange(10, 300)
        self.weight_spin.setValue(70.0)
        self.weight_spin.setSuffix(" kg")
        grid.addWidget(MLabel("体重"), 1, 0)
        grid.addWidget(self.weight_spin, 1, 1)

        # 身高
        self.height_spin = MDoubleSpinBox()
        self.height_spin.setRange(50, 250)
        self.height_spin.setValue(170.0)
        self.height_spin.setSuffix(" cm")
        grid.addWidget(MLabel("身高"), 2, 0)
        grid.addWidget(self.height_spin, 2, 1)

        # 训练水平
        self.level_combo = QComboBox()
        self.level_combo.addItems([
            "advanced", "intermediate", "beginner",
        ])
        grid.addWidget(MLabel("训练水平"), 3, 0)
        grid.addWidget(self.level_combo, 3, 1)

        # 侧重训练
        self.side_combo = QComboBox()
        self.side_combo.addItems(["", "left", "right", "both"])
        grid.addWidget(MLabel("侧重训练"), 4, 0)
        grid.addWidget(self.side_combo, 4, 1)



        layout.addLayout(grid)
        layout.addStretch()

    def get_context(self) -> AthleteProfile:
        """收集当前输入，构建 AthleteProfile。"""
        return AthleteProfile(
            age=self.age_spin.value(),
            weight=self.weight_spin.value(),
            height=self.height_spin.value(),
            level=self.level_combo.currentText(),
            focus_side=self.side_combo.currentText(),
        )


# ---- 主测试窗口 ----

class AgentTestWindow(QWidget):
    """Agent 参数配置测试主窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agent 参数配置测试工具")
        self.resize(900, 800)

        self._agent = GaitAgent(mode="offline")
        self._llm_worker: LLMWorker | None = None
        self._chat_start_time: float = 0.0
        self._stream_anchor: int | None = None
        self._stream_buffer = ""
        self._agent_label_inserted = False
        self._warmup_worker: WarmupWorker | None = None
        self._warmup_started = False
        self._warmup_ready = False
        self._warmup_error: str | None = None

        self._build_ui()
        self._connect_signals()
        self._start_warmup()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        # ===== 上半部分: 用户信息 + 操作面板 =====
        splitter = QSplitter(Qt.Horizontal)

        # 左: 用户信息（固定宽度，不参与拉伸）
        self._athlete_panel = AthletePanel()
        self._athlete_panel.setMaximumWidth(240)
        splitter.addWidget(self._athlete_panel)

        # 右: 操作面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # -- 模式选择 --
        right_layout.addWidget(MDivider("配置模式"))

        mode_layout = QHBoxLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["离线 (规则引擎)", "在线 (LLM)"])
        mode_layout.addWidget(MLabel("模式:"))
        mode_layout.addWidget(self._mode_combo)
        mode_layout.addStretch()
        right_layout.addLayout(mode_layout)

        # -- 离线面板 --
        self._offline_panel = QWidget()
        offline_layout = QVBoxLayout(self._offline_panel)
        offline_layout.setContentsMargins(0, 8, 0, 0)

        type_layout = QHBoxLayout()
        self._test_type_combo = QComboBox()
        self._test_type_combo.addItems(["Jump Test"])
        type_layout.addWidget(MLabel("测试类型:"))
        type_layout.addWidget(self._test_type_combo)
        offline_layout.addLayout(type_layout)

        self._offline_btn = MPushButton("生成配置")
        self._offline_btn.set_dayu_type(MPushButton.PrimaryType)
        offline_layout.addWidget(self._offline_btn)
        offline_layout.addStretch()

        right_layout.addWidget(self._offline_panel)

        # -- 在线面板 --
        self._online_panel = QWidget()
        online_layout = QVBoxLayout(self._online_panel)
        online_layout.setContentsMargins(0, 8, 0, 0)

        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setPlaceholderText("对话记录...")
        self._chat_display.setStyleSheet("font-size: 18px;")
        self._chat_display.document().setDefaultStyleSheet(
            "table { border-collapse: collapse; margin: 8px 0; }"
            "td, th { border: 1px solid #999; padding: 4px 10px; }"
        )
        online_layout.addWidget(self._chat_display, 1)

        input_layout = QHBoxLayout()
        self._chat_input = MLineEdit()
        self._chat_input.setPlaceholderText("描述测试需求，如: 入门用户30次跳跃测试")
        self._chat_input.setStyleSheet("font-size: 18px;")
        
        self._send_btn = MPushButton("发送")
        self._send_btn.set_dayu_type(MPushButton.PrimaryType)
        self._reset_btn = MPushButton("重置对话")
        input_layout.addWidget(self._chat_input)
        input_layout.addWidget(self._send_btn)
        input_layout.addWidget(self._reset_btn)
        online_layout.addLayout(input_layout)

        right_layout.addWidget(self._online_panel, 1)
        self._online_panel.hide()

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

        # ===== 下半部分: 结果展示 =====
        main_layout.addWidget(MDivider("生成结果 (TestConfig)"))
        self._result_display = QTextEdit()
        self._result_display.setReadOnly(True)
        self._result_display.setMaximumHeight(100)
        self._result_display.setPlaceholderText("点击「生成配置」或「发送」后，结果显示在此处...")
        main_layout.addWidget(self._result_display)

    def _connect_signals(self):
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._offline_btn.clicked.connect(self._on_offline_generate)
        self._send_btn.clicked.connect(self._on_send_message)
        self._reset_btn.clicked.connect(self._on_reset_chat)
        self._chat_input.returnPressed.connect(self._on_send_message)

    def _start_warmup(self):
        if self._warmup_started:
            return
        self._warmup_started = True
        self._warmup_worker = WarmupWorker(self._agent)
        self._warmup_worker.ready.connect(self._on_warmup_ready)
        self._warmup_worker.error.connect(self._on_warmup_error)
        self._warmup_worker.start()

    def _sync_online_input_state(self):
        if self._mode_combo.currentIndex() == 0:
            return
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return
        if self._warmup_error:
            self._chat_input.setEnabled(False)
            self._send_btn.setEnabled(False)
            self._send_btn.setText("Agent初始化失败")
            return
        if not self._warmup_ready:
            self._chat_input.setEnabled(False)
            self._send_btn.setEnabled(False)
            self._send_btn.setText("Agent正在初始化")
            return
        self._chat_input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._send_btn.setText("发送")

    def _on_warmup_ready(self):
        self._warmup_ready = True
        if self._mode_combo.currentIndex() != 0:
            self._agent.switch_mode("online")
            self._sync_online_input_state()

    def _on_warmup_error(self, error_msg: str):
        self._warmup_error = error_msg
        self._chat_display.append(f"<b>错误:</b> Agent初始化失败: {error_msg}")
        self._sync_online_input_state()

    # ---- 模式切换 ----

    def _on_mode_changed(self, index: int):
        if index == 0:
            self._offline_panel.show()
            self._online_panel.hide()
            self._agent.switch_mode("offline")
        else:
            self._offline_panel.hide()
            self._online_panel.show()
            if self._warmup_ready:
                self._agent.switch_mode("online")
            self._sync_online_input_state()

    # ---- 离线模式 ----

    def _on_offline_generate(self):
        ctx = self._athlete_panel.get_context()
        test_type = self._test_type_combo.currentText()

        try:
            config = self._agent.configure_offline(test_type, ctx)
            self._show_config(config)
        except Exception as e:
            self._result_display.setPlainText(f"错误: {e}")

    # ---- 在线模式 ----

    def _on_send_message(self):
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return
        if not self._warmup_ready or self._warmup_error:
            self._sync_online_input_state()
            return

        message = self._chat_input.text().strip()
        if not message:
            return

        self._chat_display.append(f"<b>你:</b> {message}")
        self._stream_anchor = None
        self._stream_buffer = ""
        self._agent_label_inserted = False
        self._chat_input.clear()
        self._chat_input.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._send_btn.setText("等待中...")
        self._chat_start_time = time.perf_counter()

        ctx = self._athlete_panel.get_context()
        if self._llm_worker is not None:
            self._llm_worker.text_chunk.disconnect()
            self._llm_worker.finished.disconnect()
            self._llm_worker.error.disconnect()
        self._llm_worker = LLMWorker(self._agent, message, ctx)
        self._llm_worker.text_chunk.connect(self._on_text_chunk)
        self._llm_worker.finished.connect(self._on_llm_finished)
        self._llm_worker.error.connect(self._on_llm_error)
        self._llm_worker.start()

    def _on_text_chunk(self, text: str):
        if not self._agent_label_inserted:
            self._chat_display.append("<b>Agent:</b> ")
            self._stream_anchor = self._chat_display.textCursor().position()
            self._agent_label_inserted = True
        self._stream_buffer += text
        self._chat_display.insertPlainText(text)

    def _on_llm_finished(self, config, reply: str):
        self._chat_input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._send_btn.setText("发送")

        if self._stream_buffer:
            doc = self._chat_display.document()
            cursor = QTextCursor(doc)
            cursor.setPosition(self._stream_anchor)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            display_text = reply if config is not None else self._stream_buffer
            cursor.insertHtml(_md_to_html(display_text))
        else:
            self._chat_display.append("<b>Agent:</b> ")
            self._chat_display.insertHtml(_md_to_html(reply))

        if config is not None:
            self._show_config(config)
        elif self._stream_buffer:
            self._result_display.setPlainText(
                f"Agent 追问中，尚未生成配置\n\n回复: {reply}"
            )

    def _on_llm_error(self, error_msg: str):
        self._chat_input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._send_btn.setText("发送")
        self._chat_display.append(f"<b>错误:</b> {error_msg}")

    def _on_reset_chat(self):
        self._agent.reset_chat()
        self._chat_display.clear()
        self._result_display.clear()

    # ---- 结果展示 ----

    def _show_config(self, config):
        """将 TestConfig 格式化显示。"""
        lines = []
        d = config.to_dict()
        for key, value in d.items():
            lines.append(f"  {key}: {value}")
        text = "TestConfig {\n" + "\n".join(lines) + "\n}"
        self._result_display.setPlainText(text)


# ======================================================================
#  独立运行入口
# ======================================================================

if __name__ == "__main__":
    with application() as app:
        win = AgentTestWindow()
        dayu_theme.apply(win)
        win.show()

        screen = app.primaryScreen().availableGeometry()
        win.move(
            (screen.width() - win.width()) // 2,
            (screen.height() - win.height()) // 2,
        )
