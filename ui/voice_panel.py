"""Compact voice controls embedded in the application's content area."""
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout,
)


class VoicePanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VoicePanel")
        self.setStyleSheet("""
            QFrame#VoicePanel { background: #141d29; border-top: 1px solid #354151; }
            QLabel { color: #cbd5e1; background: transparent; border: none; font-size: 12px; }
            QLabel#VoiceState { color: #ff9b2f; font-weight: 600; }
            QLabel#VoiceContext { color: #95a5b8; }
            QPushButton { color: #e7ebf2; background: #242e3c; border: 1px solid #354151;
                          border-radius: 6px; padding: 5px 12px; min-height: 24px; }
            QPushButton:hover { border-color: #ff8a1f; }
            QPushButton:disabled { color: #697587; background: #18212d; }
            QPushButton#VoiceToggle { background: #9b4a08; border-color: #cc6a16; color: white; }
            QPlainTextEdit { background: #0c1119; color: #aeb7c5; border: none; padding: 6px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.state_label = QLabel("麦克风已关闭")
        self.state_label.setObjectName("VoiceState")
        header.addWidget(self.state_label)
        self.context_label = QLabel()
        self.context_label.setObjectName("VoiceContext")
        self.context_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self.context_label, 1)
        self.interrupt_button = QPushButton("停止播报")
        self.interrupt_button.setToolTip("取消当前语音回复，继续聆听，不停止测试")
        self.interrupt_button.setEnabled(False)
        header.addWidget(self.interrupt_button)
        self.toggle_button = QPushButton("开启语音")
        self.toggle_button.setObjectName("VoiceToggle")
        self.toggle_button.setToolTip("开启后使用麦克风，并将音频发送至语音识别服务；再次点击关闭")
        header.addWidget(self.toggle_button)
        self.details_button = QPushButton("诊断")
        self.details_button.setCheckable(True)
        self.details_button.setToolTip("展开或收起诊断记录，不改变麦克风状态")
        header.addWidget(self.details_button)
        layout.addLayout(header)
        self._transcript_text = ""
        self._reply_text = ""
        self.transcript = QLabel()
        self.reply = QLabel()
        for label in (self.transcript, self.reply):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(False)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.hide()
            layout.addWidget(label)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(100)
        self.diagnostics.setFixedHeight(100)
        self.diagnostics.hide()
        self.details_button.toggled.connect(self.diagnostics.setVisible)
        layout.addWidget(self.diagnostics)

    def set_state(self, text):
        self.state_label.setText(text)

    def show_transcript(self, text, final):
        self._transcript_text = ("你：" if final else "正在识别：") + text
        self._refresh_text()
        self.transcript.setToolTip(text)
        self.transcript.show()

    def show_reply(self, text):
        self._reply_text = "助手：" + text
        self._refresh_text()
        self.reply.setToolTip(text)
        self.reply.show()

    def _refresh_text(self):
        for label, text in ((self.transcript, self._transcript_text), (self.reply, self._reply_text)):
            label.setText(label.fontMetrics().elidedText(text.replace("\n", " "), Qt.ElideRight, max(0, self.width() - 32)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_text()
