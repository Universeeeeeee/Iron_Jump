"""Agent-assisted test configuration panel for SetupView."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime
from html import escape

from markdown_it import MarkdownIt
from qtpy.QtCore import Qt, QSignalBlocker, Signal, QThread, QTimer
from qtpy.QtGui import QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox, QTextEdit,
    QFrame, QScrollArea, QSizePolicy,
)

from dayu_widgets.label import MLabel
from dayu_widgets.line_edit import MLineEdit
from dayu_widgets.push_button import MPushButton
from dayu_widgets.spin_box import MDoubleSpinBox, MSpinBox

from agent.config.models import AthleteProfile
from agent.config.modes import MODE_TEST_TYPES
from agent.config.rule_engine import RuleEngine
from config.test_config import AnyTestConfig, config_from_dict
from data.subject_store import SubjectSearchResult, SubjectStore
from ui.llm_client import AgentWorkerClient


log = logging.getLogger(__name__)
_md = MarkdownIt().enable("table")


AGENT_PANEL_QSS = """
QWidget#AgentConfigPanelRoot {
  background: transparent;
}
QFrame#AgentCard {
  background-color: rgba(32, 37, 48, 0.72);
  border: none;
  border-radius: 8px;
}
QFrame#SuggestionCard {
  background-color: #1b222e;
  border: none;
  border-left: 1px solid #354151;
  border-radius: 8px;
}
QLabel#CardTitle {
  font-size: 12pt;
  font-weight: 700;
  color: #f0f3f8;
  background: transparent;
  border: none;
}
QLabel#SectionTitle {
  font-size: 10pt;
  font-weight: 700;
  color: #ff9b2f;
  background: transparent;
  border: none;
}
QLabel#FieldLabel {
  color: #cfd6e3;
  background: transparent;
  border: none;
}
QLabel#ServiceStatus {
  color: #9da8b8;
  background: transparent;
  border: none;
  font-size: 10pt;
}
QTextEdit {
  border: none;
  border-radius: 8px;
  background-color: rgba(17, 24, 34, 0.58);
  color: #e7ebf2;
  padding: 12px;
}
QScrollArea#SuggestionConfigScroll,
QScrollArea#SuggestionConfigScroll QWidget#qt_scrollarea_viewport {
  background: transparent;
  border: none;
}
QScrollArea#SuggestionConfigScroll QScrollBar:vertical {
  width: 8px;
  border: none;
  background: transparent;
}
QScrollArea#SuggestionConfigScroll QScrollBar::handle:vertical {
  min-height: 28px;
  border-radius: 4px;
  background: #3a485a;
}
QScrollArea#SuggestionConfigScroll QScrollBar::add-line:vertical,
QScrollArea#SuggestionConfigScroll QScrollBar::sub-line:vertical {
  height: 0;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid rgba(105, 115, 135, 0.35);
  background-color: rgba(43, 48, 60, 0.96);
  color: #e7ebf2;
  padding: 0 8px;
}
QComboBox QAbstractItemView {
  background: #1a2230;
  color: #e7ebf2;
  border: 1px solid #354151;
  selection-background-color: #273446;
}
QPushButton {
  min-height: 34px;
  border-radius: 6px;
  border: 1px solid rgba(105, 115, 135, 0.32);
  background-color: rgba(43, 48, 60, 0.94);
  color: #d9dee8;
  padding: 0 14px;
}
QPushButton:hover {
  background-color: rgba(58, 64, 79, 0.98);
}
QPushButton#PanelPrimaryButton {
  background-color: #ff850f;
  border-color: #ff850f;
  color: white;
  font-weight: 700;
}
QPushButton#PanelPrimaryButton:disabled {
  background-color: #252d38;
  border-color: #303a47;
  color: #768294;
}
QPushButton#PromptChip {
  min-height: 30px;
  border-radius: 15px;
  padding: 0 14px;
  background-color: rgba(43, 48, 60, 0.70);
}
QPushButton#SuggestionToggleButton,
QPushButton#SuggestionCloseButton {
  min-height: 28px;
  padding: 0 10px;
  background-color: transparent;
}
QPushButton#SuggestionCloseButton {
  min-width: 28px;
  max-width: 28px;
  padding: 0;
  font-size: 16px;
}
"""


_THREE_COLUMN_MIN_WIDTH = 1180
_SUGGESTION_DRAWER_MIN_WIDTH = 280
_SUGGESTION_DRAWER_MAX_WIDTH = 320
_AGENT_MODES = tuple(MODE_TEST_TYPES)
_CHAT_DOCUMENT_QSS = (
    "table { border-collapse: collapse; margin: 8px 0; }"
    "td, th { border: 1px solid #999; padding: 4px 10px; }"
)


def _md_to_html(text: str) -> str:
    return _md.render(text)


class _LLMHttpWorker(QThread):
    """在线模式：通过 HTTP 调用 llm_worker 进程（阻塞式，v1 无流式）。"""
    finished = Signal(object, str)  # (AnyTestConfig | None, reply_text)
    error = Signal(str)

    def __init__(self, client: AgentWorkerClient, message: str, athlete: AthleteProfile,
                 request_id: int = 0, agent_mode: str = "jump"):
        super().__init__()
        self._client = client
        self._message = message
        self._athlete = athlete
        self.request_id = request_id
        self._agent_mode = agent_mode
        self.resolved_mode = agent_mode
        self.pending_intent = None
        self.segment_count = None

    def run(self):
        try:
            profile_dict = {
                "age": self._athlete.age,
                "weight": self._athlete.weight,
                "height": self._athlete.height,
                "level": self._athlete.level,
                "focus_side": self._athlete.focus_side,
                "device_channels": self._athlete.device_channels,
                "history": self._athlete.history,
            }
            if hasattr(self._client, "chat_routed"):
                result = self._client.chat_routed(
                    self._message, profile_dict, self._agent_mode,
                    self.segment_count, self.pending_intent)
            else:
                result = self._client.chat(self._message, profile_dict, agent_mode=self._agent_mode)
            self.resolved_mode = result.get("mode", self._agent_mode)
            if self.resolved_mode not in MODE_TEST_TYPES:
                raise ValueError("服务返回了不支持的模式")
            self.pending_intent = result.get("pending")
            if "error" in result:
                self.error.emit(result["error"])
                return
            config_dict = result.get("config")
            if config_dict:
                config = config_from_dict(config_dict)
            else:
                config = None
            self.finished.emit(config, result.get("reply", ""))
        except Exception as e:
            self.error.emit(f"{e}\n{traceback.format_exc()}")


class AgentConfigPanel(QWidget):
    """智能配置面板：生成建议配置，确认后交给 SetupView。"""

    config_confirmed = Signal(object)  # AnyTestConfig
    profile_changed = Signal()
    configuration_invalidated = Signal(bool)  # True for a new request, False for selector synchronization.
    voice_reply = Signal(str)

    def __init__(
        self,
        subject_store: SubjectStore | None = None,
        llm_client: AgentWorkerClient | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._subject_store = subject_store
        self._llm_client = llm_client
        self._rule_engine = RuleEngine()
        self._llm_worker: _LLMHttpWorker | None = None
        self._worker_ready = False
        self._worker_error: str | None = None
        self._worker_start_requested = False
        self._pending_config: AnyTestConfig | None = None
        self._suggestion_drawer_dismissed = False
        self._history: list[dict] = []
        self._worker_status_timer = QTimer(self)
        self._worker_status_timer.setInterval(1000)
        self._worker_status_timer.timeout.connect(self._poll_llm_worker)
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._ensure_llm_worker_started)
        self._active_request_id = 0
        self._mode_revision = 0

        self._build_ui()
        self._connect_signals()
        self.set_subject_result(None)
        self._sync_mode_state()
        self._startup_timer.start(0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_subject_result(self, result: SubjectSearchResult | None) -> None:
        self._active_request_id += 1
        self._clear_pending_config()
        self._history = []
        if result is None:
            self._fill_athlete_fields(
                AthleteProfile(age=30, weight=70, height=170, level="intermediate")
            )
            self._age_spin.setEnabled(True)
            self._profile_note.setText("未选择受试者，请填写基础信息。仅用于本次配置。")
            self._history_label.setText("历史记录：暂无")
            return

        if self._subject_store is None:
            self._history = []
            profile = AthleteProfile(
                age=max(0, datetime.now().year - result.subject.birth_year),
                weight=float(result.subject.weight_kg or 0.0),
                height=float(result.subject.height_cm or 0.0),
                level=result.subject.level,
                focus_side=result.subject.focus_side,
            )
        else:
            try:
                self._history = self._subject_store.get_recent_history(result.subject.id)
                profile = self._subject_store.subject_to_athlete_profile(
                    result.subject, self._history,
                )
            except Exception:
                log.exception("Failed to load subject profile for agent panel")
                profile = AthleteProfile(age=30, weight=70, height=170)
                self._history = []

        self._fill_athlete_fields(profile)
        self._age_spin.setEnabled(False)
        self._profile_note.setText("已从受试者档案自动填入。年龄仅可在运动员管理中修改。")
        count_text = f"最近 {len(self._history)} 次已加载" if self._history else "暂无"
        self._history_label.setText(f"历史记录：{count_text}")

    def current_test_type(self) -> str:
        """Return the test type currently selected in the assistant panel."""
        return self._test_type_combo.currentText()

    def current_profile_snapshot(self) -> dict:
        """Return the editable, session-scoped athlete values."""
        profile = self._current_athlete_profile()
        return {
            "age": profile.age,
            "weight_kg": float(profile.weight),
            "height_cm": float(profile.height),
            "level": profile.level,
            "focus_side": profile.focus_side,
        }

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("AgentConfigPanelRoot")
        self.setStyleSheet(AGENT_PANEL_QSS)

        main_layout = QGridLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)
        self._main_layout = main_layout
        self._compact_layout: bool | None = None

        profile_card = self._create_card()
        self._profile_card = profile_card
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(16, 14, 16, 14)
        profile_layout.setSpacing(10)
        profile_layout.addWidget(self._card_title("运动档案"))

        self._profile_note = MLabel("")
        self._profile_note.setWordWrap(True)
        self._profile_note.setStyleSheet("color: #9f9f9f;")
        profile_layout.addWidget(self._profile_note)

        profile_layout.addWidget(self._section_title("基础信息"))
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(10)
        self._age_spin = MSpinBox()
        self._age_spin.setRange(1, 120)
        self._weight_spin = MDoubleSpinBox()
        self._weight_spin.setRange(0, 300)
        self._weight_spin.setSuffix(" kg")
        self._height_spin = MDoubleSpinBox()
        self._height_spin.setRange(0, 250)
        self._height_spin.setSuffix(" cm")
        self._level_combo = QComboBox()
        self._level_combo.addItems(["beginner", "intermediate", "advanced"])
        self._focus_combo = QComboBox()
        self._focus_combo.addItem("均衡", "")
        self._focus_combo.addItem("左侧", "left")
        self._focus_combo.addItem("右侧", "right")
        self._focus_combo.addItem("双侧", "both")

        self._add_form_row(form, 0, "年龄", self._age_spin)
        self._add_form_row(form, 1, "体重", self._weight_spin)
        self._add_form_row(form, 2, "身高", self._height_spin)
        profile_layout.addLayout(form)

        profile_layout.addWidget(self._section_title("训练信息"))
        training_form = QGridLayout()
        training_form.setHorizontalSpacing(10)
        training_form.setVerticalSpacing(10)
        self._add_form_row(training_form, 0, "训练水平", self._level_combo)
        self._add_form_row(training_form, 1, "侧重训练", self._focus_combo)
        profile_layout.addLayout(training_form)

        self._history_label = MLabel("")
        self._history_label.setStyleSheet("color: #aaaaaa;")
        profile_layout.addWidget(self._history_label)
        profile_layout.addStretch()

        chat_card = self._create_card()
        self._chat_card = chat_card
        chat_layout = QVBoxLayout(chat_card)
        chat_layout.setContentsMargins(16, 14, 16, 14)
        chat_layout.setSpacing(10)

        header = QHBoxLayout()
        self._assistant_title = self._card_title("配置助手")
        self._assistant_title.setMinimumWidth(
            self._assistant_title.sizeHint().width()
        )
        header.addWidget(self._assistant_title)
        header.addStretch()
        self._suggestion_toggle_btn = MPushButton("查看建议")
        self._suggestion_toggle_btn.setObjectName("SuggestionToggleButton")
        self._suggestion_toggle_btn.hide()
        header.addWidget(self._suggestion_toggle_btn)
        self._test_type_combo = QComboBox()
        for mode, test_type in MODE_TEST_TYPES.items():
            self._test_type_combo.addItem(test_type, mode)
        self._test_type_combo.setMinimumWidth(150)
        self._test_type_combo.setMaximumWidth(190)
        header.addWidget(self._test_type_combo)
        chat_layout.addLayout(header)

        self._status_label = MLabel("")
        self._status_label.setObjectName("ServiceStatus")
        self._status_label.setWordWrap(True)
        chat_layout.addWidget(self._status_label)

        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setPlaceholderText(
            "告诉我受试者情况和测试目标，我会生成测试参数建议。\n"
            "示例：为普通用户生成 5 次纵跳测试配置。"
        )
        self._chat_documents = {}
        for mode in _AGENT_MODES:
            document = QTextDocument(self)
            document.setDefaultStyleSheet(_CHAT_DOCUMENT_QSS)
            self._chat_documents[mode] = document
        self._chat_display.setDocument(self._chat_documents["jump"])
        chat_layout.addWidget(self._chat_display, 1)

        self._prompt_chips = QWidget()
        chip_layout = QGridLayout(self._prompt_chips)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setHorizontalSpacing(8)
        chip_layout.setVerticalSpacing(8)
        self._prompt_chip_buttons = []
        for index, text in enumerate(
            ("入门 3 次", "常规 5 次", "1 分钟测试", "轻量测试")
        ):
            chip = MPushButton(text)
            chip.setObjectName("PromptChip")
            chip.clicked.connect(lambda _, button=chip: self._chat_input.setText(button.text()))
            self._prompt_chip_buttons.append(chip)
            row, column = divmod(index, 2)
            chip_layout.addWidget(chip, row, column)
        chat_layout.addWidget(self._prompt_chips)

        input_layout = QHBoxLayout()
        self._chat_input = MLineEdit()
        self._chat_input.setPlaceholderText("描述测试需求...")
        self._send_btn = MPushButton("发送").primary()
        self._send_btn.setObjectName("PanelPrimaryButton")
        self._reset_btn = MPushButton("重置对话")
        input_layout.addWidget(self._chat_input, 1)
        input_layout.addWidget(self._send_btn)
        input_layout.addWidget(self._reset_btn)
        chat_layout.addLayout(input_layout)

        suggestion_card = self._create_card()
        suggestion_card.setObjectName("SuggestionCard")
        self._suggestion_card = suggestion_card
        suggestion_layout = QVBoxLayout(suggestion_card)
        suggestion_layout.setContentsMargins(16, 14, 16, 14)
        suggestion_layout.setSpacing(10)
        suggestion_header = QHBoxLayout()
        suggestion_header.addWidget(self._card_title("建议配置"))
        suggestion_header.addStretch()
        self._suggestion_close_btn = MPushButton("×")
        self._suggestion_close_btn.setObjectName("SuggestionCloseButton")
        self._suggestion_close_btn.setToolTip("收起建议配置")
        suggestion_header.addWidget(self._suggestion_close_btn)
        suggestion_layout.addLayout(suggestion_header)

        self._suggestion_text = MLabel("尚未生成建议配置。")
        self._suggestion_text.setWordWrap(True)
        self._suggestion_text.setTextFormat(Qt.RichText)
        self._suggestion_text.setStyleSheet(
            "font-size: 10.5pt; color: #d0d6e2; background: transparent; border: none;"
        )
        suggestion_scroll = QScrollArea()
        suggestion_scroll.setObjectName("SuggestionConfigScroll")
        suggestion_scroll.setWidgetResizable(True)
        suggestion_scroll.setFrameShape(QFrame.NoFrame)
        suggestion_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        suggestion_scroll.setWidget(self._suggestion_text)
        suggestion_layout.addWidget(suggestion_scroll, 1)

        self._confirm_btn = MPushButton("确认使用此配置").primary()
        self._confirm_btn.setObjectName("PanelPrimaryButton")
        self._confirm_btn.setMinimumHeight(42)
        self._confirm_btn.setEnabled(False)
        suggestion_layout.addWidget(self._confirm_btn)
        self._apply_responsive_layout(self.width() < _THREE_COLUMN_MIN_WIDTH)

    def _connect_signals(self) -> None:
        self._test_type_combo.currentIndexChanged.connect(self._on_test_type_changed)
        self._send_btn.clicked.connect(self._on_send_message)
        self._chat_input.returnPressed.connect(self._on_send_message)
        self._reset_btn.clicked.connect(self._on_reset_chat)
        self._suggestion_toggle_btn.clicked.connect(self._toggle_suggestion_drawer)
        self._suggestion_close_btn.clicked.connect(self._dismiss_suggestion_drawer)
        self._confirm_btn.clicked.connect(self._on_confirm_clicked)
        self._age_spin.valueChanged.connect(self._clear_pending_config)
        self._weight_spin.valueChanged.connect(self._on_profile_input_changed)
        self._height_spin.valueChanged.connect(self._on_profile_input_changed)
        self._level_combo.currentIndexChanged.connect(self._on_profile_input_changed)
        self._focus_combo.currentIndexChanged.connect(self._on_profile_input_changed)

    def _create_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("AgentCard")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return frame

    def resizeEvent(self, event) -> None:
        self._apply_responsive_layout(
            event.size().width() < _THREE_COLUMN_MIN_WIDTH
        )
        super().resizeEvent(event)

    def _apply_responsive_layout(self, compact: bool) -> None:
        if self._compact_layout is compact:
            return
        self._compact_layout = compact

        for card in (
            self._profile_card,
            self._chat_card,
            self._suggestion_card,
        ):
            self._main_layout.removeWidget(card)

        if compact:
            self._profile_card.setMinimumWidth(220)
            self._profile_card.setMaximumWidth(250)
            self._profile_card.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Expanding
            )
            self._chat_card.setMinimumWidth(0)
            self._suggestion_card.setMinimumWidth(_SUGGESTION_DRAWER_MIN_WIDTH)
            self._suggestion_card.setMaximumWidth(_SUGGESTION_DRAWER_MAX_WIDTH)
            self._suggestion_card.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Expanding
            )

            self._main_layout.addWidget(self._profile_card, 0, 0)
            self._main_layout.addWidget(self._chat_card, 0, 1)
            self._main_layout.addWidget(
                self._suggestion_card, 0, 1, Qt.AlignRight
            )
            self._main_layout.setColumnStretch(0, 0)
            self._main_layout.setColumnStretch(1, 1)
            self._main_layout.setColumnStretch(2, 0)
            self._main_layout.setRowStretch(0, 1)
            self._main_layout.setRowStretch(1, 0)
            self._sync_suggestion_presentation()
            return

        self._profile_card.setMinimumWidth(220)
        self._profile_card.setMaximumWidth(230)
        self._profile_card.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        self._chat_card.setMinimumWidth(560)
        self._suggestion_card.setMinimumWidth(250)
        self._suggestion_card.setMaximumWidth(270)
        self._suggestion_card.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding
        )

        self._main_layout.addWidget(self._profile_card, 0, 0)
        self._main_layout.addWidget(self._chat_card, 0, 1)
        self._main_layout.addWidget(self._suggestion_card, 0, 2)
        self._main_layout.setColumnStretch(0, 0)
        self._main_layout.setColumnStretch(1, 1)
        self._main_layout.setColumnStretch(2, 0)
        self._main_layout.setRowStretch(0, 1)
        self._main_layout.setRowStretch(1, 0)
        self._sync_suggestion_presentation()

    def _sync_suggestion_presentation(self) -> None:
        has_suggestion = self._pending_config is not None
        self._suggestion_toggle_btn.setVisible(
            has_suggestion and self._compact_layout
        )
        self._suggestion_close_btn.setVisible(bool(self._compact_layout))

        if not has_suggestion:
            self._suggestion_card.hide()
            return

        if self._compact_layout and self._suggestion_drawer_dismissed:
            self._suggestion_toggle_btn.setText("查看建议")
            self._suggestion_card.hide()
            return

        self._suggestion_toggle_btn.setText("收起建议")
        self._suggestion_card.show()

    def _toggle_suggestion_drawer(self) -> None:
        if self._pending_config is None or not self._compact_layout:
            return
        self._suggestion_drawer_dismissed = not self._suggestion_drawer_dismissed
        self._sync_suggestion_presentation()

    def _dismiss_suggestion_drawer(self) -> None:
        if not self._compact_layout:
            return
        self._suggestion_drawer_dismissed = True
        self._sync_suggestion_presentation()

    @staticmethod
    def _card_title(text: str) -> MLabel:
        label = MLabel(text)
        label.setObjectName("CardTitle")
        return label

    @staticmethod
    def _section_title(text: str) -> MLabel:
        label = MLabel(text)
        label.setObjectName("SectionTitle")
        return label

    @staticmethod
    def _add_form_row(layout: QGridLayout, row: int, label: str, widget: QWidget) -> None:
        label_widget = MLabel(label)
        label_widget.setObjectName("FieldLabel")
        layout.addWidget(label_widget, row, 0)
        layout.addWidget(widget, row, 1)

    def _append_chat_entry(
        self, label: str, body_html: str, *, mode: str | None = None
    ) -> None:
        target_mode = mode or self._current_agent_mode()
        document = self._chat_documents[target_mode]
        is_active_document = document is self._chat_display.document()
        scrollbar = self._chat_display.verticalScrollBar()
        follow_new_entries = (
            is_active_document and scrollbar.value() == scrollbar.maximum()
        )
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.End)
        if not document.isEmpty():
            cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        cursor.insertHtml(f"<b>{escape(label)}:</b> ")
        cursor.insertHtml(body_html)
        if follow_new_entries:
            scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _fill_athlete_fields(self, profile: AthleteProfile) -> None:
        widgets = (
            self._age_spin,
            self._weight_spin,
            self._height_spin,
            self._level_combo,
            self._focus_combo,
        )
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._age_spin.setValue(profile.age)
            self._weight_spin.setValue(float(profile.weight or 0.0))
            self._height_spin.setValue(float(profile.height or 0.0))
            index = self._level_combo.findText(profile.level)
            if index >= 0:
                self._level_combo.setCurrentIndex(index)
            focus_index = self._focus_combo.findData(profile.focus_side)
            self._focus_combo.setCurrentIndex(max(focus_index, 0))
        finally:
            del blockers

    def _on_profile_input_changed(self, *_args) -> None:
        self._clear_pending_config()
        self.profile_changed.emit()

    def _current_athlete_profile(self) -> AthleteProfile:
        return AthleteProfile(
            age=self._age_spin.value(),
            weight=float(self._weight_spin.value()),
            height=float(self._height_spin.value()),
            level=self._level_combo.currentText(),
            focus_side=self._focus_combo.currentData() or "",
            device_channels=(getattr(self, "_segment_count", None) or 0) * 96,
            history=list(self._history),
        )

    def _current_agent_mode(self) -> str:
        return self._test_type_combo.currentData() or "jump"

    def _clear_pending_config(self, *_args) -> None:
        if self._pending_config is None:
            return
        self._pending_config = None
        self._suggestion_drawer_dismissed = False
        self._confirm_btn.setEnabled(False)
        self._suggestion_text.setText("运动档案已变化，请重新生成建议配置。")
        self._sync_suggestion_presentation()

    def _sync_mode_state(self) -> None:
        busy = self._llm_worker is not None and self._llm_worker.isRunning()
        if self._llm_client is not None and not self._llm_client.is_running:
            self._worker_ready = False
        self._chat_input.setEnabled(self._llm_client is not None)
        self._send_btn.setEnabled(not busy and self._worker_ready)
        self._reset_btn.setEnabled(not busy and self._worker_ready)
        if self._llm_client is None:
            status = "智能服务不可用，请使用手动配置。"
        elif self._worker_error:
            status = f"智能服务初始化失败：{self._worker_error}"
        elif busy:
            status = "正在生成建议配置…"
        elif not self._worker_ready:
            status = "智能服务初始化中…"
        else:
            status = ""
        self._status_label.setText(status)
        self._status_label.setVisible(bool(status))

    def _ensure_llm_worker_started(self) -> None:
        if self._llm_client is None:
            self._sync_mode_state()
            return
        if self._worker_ready and self._llm_client.is_running:
            self._sync_mode_state()
            return
        if not self._llm_client.is_running:
            self._worker_start_requested = True
            self._worker_error = None
            if not self._llm_client.start():
                self._worker_error = "worker 进程启动失败"
                self._sync_mode_state()
                return
        if not self._worker_status_timer.isActive():
            self._worker_status_timer.start()
        self._poll_llm_worker()

    def _poll_llm_worker(self) -> None:
        if self._llm_client is None:
            return
        status = self._llm_client.worker_status(timeout=0.25)
        if status == "ready":
            self._worker_ready = True
            self._worker_error = None
            self._worker_status_timer.stop()
        elif status in {"starting", "warming"}:
            self._worker_ready = False
            self._worker_error = None
        else:
            self._worker_ready = False
            self._worker_error = status
            self._worker_status_timer.stop()
        self._sync_mode_state()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_test_type_changed(self, *_args) -> None:
        self._mode_revision += 1
        self._pending_intent = None
        self.configuration_invalidated.emit(False)
        self._clear_pending_config()
        mode = self._current_agent_mode()
        document = self._chat_documents[mode]
        examples = {
            "jump": ("入门 3 次", "常规 5 次", "1 分钟测试", "轻量测试"),
            "treadmill_gait": ("配置跑步机走路", "走路测试 1 分钟", "速度 3 公里每小时", "配置手动结束"),
            "treadmill_running": ("配置跑步机跑步", "跑步测试 1 分钟", "速度 6 公里每小时", "配置手动结束"),
            "walking": ("配置地面走路", "走路通过后自动结束", "配置左脚先进入", "配置手动结束"),
            "overground_running": ("配置地面跑步", "跑步通过后自动结束", "配置右脚先进入", "配置手动结束"),
        }
        for button, text in zip(self._prompt_chip_buttons, examples[mode]):
            button.setText(text)
        self._chat_display.setDocument(document)
        self._chat_input.clear()
        self._prompt_chips.setVisible(document.isEmpty())
        self._ensure_llm_worker_started()

    def _on_send_message(self) -> None:
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return
        if self._llm_client is None:
            return
        message = self._chat_input.text().strip()
        if not message:
            return
        status = self._llm_client.worker_status(timeout=0.25)
        if status != "ready":
            self._worker_ready = False
            self._worker_error = None if status in {"starting", "warming", "stopped"} else status
            self._ensure_llm_worker_started()
            return
        self._worker_ready = True
        self._worker_error = None

        self._clear_pending_config()
        self._append_chat_entry("你", escape(message))
        self.configuration_invalidated.emit(True)
        self._prompt_chips.hide()

        self._chat_input.clear()
        self._active_request_id += 1

        self._llm_worker = _LLMHttpWorker(
            self._llm_client, message, self._current_athlete_profile(),
            request_id=self._active_request_id,
            agent_mode=self._current_agent_mode(),
        )
        self._llm_worker.mode_revision = self._mode_revision
        self._llm_worker.segment_count = getattr(self, "_segment_count", None)
        self._llm_worker.pending_intent = getattr(self, "_pending_intent", None)
        self._llm_worker.finished.connect(self._on_llm_finished)
        self._llm_worker.error.connect(self._on_llm_error)
        self._chat_input.setEnabled(False)
        self._send_btn.setEnabled(False)
        self._status_label.setText("正在生成建议配置…")
        self._status_label.show()
        self._llm_worker.start()

    @property
    def voice_submission_status(self) -> str:
        if not getattr(self._llm_client, "configuration_enabled", True):
            return "disabled"
        if self._llm_worker is not None:
            return "busy"
        return "ready" if self._worker_ready else "unavailable"

    def submit_voice(self, message: str) -> bool:
        """Reuse the validated config worker and its visible conversation history."""
        if self.voice_submission_status in {"disabled", "busy"}:
            return False
        if not self._worker_ready:
            self._ensure_llm_worker_started()
            return False
        self._chat_input.setText(message)
        self._on_send_message()
        return self._llm_worker is not None

    def _on_llm_finished(self, config, reply: str) -> None:
        worker = self.sender()
        if getattr(worker, 'request_id', None) != self._active_request_id:
            if worker is self._llm_worker:
                self._llm_worker = None
                self._sync_mode_state()
            if worker is not None:
                worker.deleteLater()
            return
        mode = getattr(worker, "resolved_mode", getattr(worker, "_agent_mode", self._current_agent_mode()))
        current_selection = (getattr(worker, "mode_revision", self._mode_revision) == self._mode_revision)
        if current_selection:
            if mode != self._current_agent_mode():
                self._test_type_combo.setCurrentIndex(self._test_type_combo.findText(MODE_TEST_TYPES[mode]))
                self._append_chat_entry("你", escape(worker._message), mode=mode)
            self._pending_intent = getattr(worker, "pending_intent", None)
        self._append_chat_entry("AI", _md_to_html(reply), mode=mode)

        if config is not None and config.test_type != MODE_TEST_TYPES[mode]:
            if current_selection:
                self._clear_pending_config()
            config = None
            reply = "返回的配置与请求模式不一致，请重新生成。"
            self._append_chat_entry("错误", reply, mode=mode)
        if config is not None and current_selection:
            self._set_pending_config(config, "智能服务已生成建议配置。")

        self._llm_worker = None
        self._sync_mode_state()
        if current_selection:
            self.voice_reply.emit(
                self._spoken_config_summary(config) if config is not None else reply
            )

    @staticmethod
    def _spoken_config_summary(config: AnyTestConfig) -> str:
        parts = ["建议配置已生成", getattr(config, "mode_label", config.test_type)]
        if hasattr(config, "treadmill_speed"):
            parts.append(f"速度每小时{config.treadmill_speed:g}公里")
        if config.stop_type == "End of Time" and config.test_length:
            minutes, seconds = map(int, config.test_length.split(":"))
            parts.append(f"测试时长{minutes}分{seconds}秒")
        elif config.stop_type == "Software command":
            parts.append("通过结束测试指令停止")
        elif config.test_type in {"Sprint and Gait Test", "Overground Running Test"}:
            parts.append("单次通过后空场自动结束")
        elif getattr(config, "number_of_jumps", None):
            parts.append(f"跳跃{config.number_of_jumps}次")
        if config.test_type in {"Sprint and Gait Test", "Overground Running Test"}:
            parts.append("起始脚" + {"Left": "左脚", "Right": "右脚", "Not defined": "未指定"}[config.starting_foot])
        parts.append("请说确认配置后应用")
        return "。".join(parts) + "。"

    def _on_llm_error(self, message: str) -> None:
        worker = self.sender()
        if getattr(worker, 'request_id', None) != self._active_request_id:
            if worker is self._llm_worker:
                self._llm_worker = None
                self._sync_mode_state()
            if worker is not None:
                worker.deleteLater()
            return
        mode = getattr(worker, "_agent_mode", self._current_agent_mode())
        self._append_chat_entry("错误", escape(message), mode=mode)
        self._llm_worker = None
        self._sync_mode_state()
        if getattr(worker, "mode_revision", self._mode_revision) == self._mode_revision:
            self.voice_reply.emit("配置服务暂时不可用，请稍后重试。")

    def _on_reset_chat(self) -> None:
        self._active_request_id += 1
        self._pending_intent = None
        if self._llm_client is not None and self._worker_ready:
            self._llm_client.reset()
        self._pending_config = None
        self._suggestion_drawer_dismissed = False
        self._confirm_btn.setEnabled(False)
        self._suggestion_text.setText("尚未生成建议配置。")
        for document in self._chat_documents.values():
            document.clear()
        self._prompt_chips.show()
        self._sync_suggestion_presentation()

    def _on_offline_generate(self) -> None:
        try:
            config = self._rule_engine.configure(
                MODE_TEST_TYPES[self._current_agent_mode()],
                self._current_athlete_profile(),
            )
        except Exception as e:
            self._chat_display.append(f"<b>错误:</b> 离线推荐失败：{e}")
            return

        self._set_pending_config(config, "离线规则已生成建议配置。")
        self._chat_display.append("<b>AI:</b> 已根据运动档案生成离线规则推荐。")

    def _on_confirm_clicked(self) -> None:
        if self._pending_config is None:
            return
        if self._pending_config.test_type != self.current_test_type():
            self._clear_pending_config()
            return
        self._chat_display.append("<b>AI:</b> 配置已应用到参数面板。")
        self.config_confirmed.emit(self._pending_config)

    # ------------------------------------------------------------------
    # Suggestion card
    # ------------------------------------------------------------------

    def _set_pending_config(self, config: AnyTestConfig, reason: str) -> None:
        self._pending_config = config
        self._suggestion_drawer_dismissed = False
        self._confirm_btn.setEnabled(True)
        self._suggestion_text.setText(self._format_config(config, reason))
        self._sync_suggestion_presentation()

    def _format_config(self, config: AnyTestConfig, reason: str) -> str:
        is_ground = config.test_type in {"Sprint and Gait Test", "Overground Running Test"}
        stop_labels = {
            "Status change": "单次通过后空场自动结束" if is_ground else "按跳跃次数结束",
            "End of Time": f"按测试时长结束（{getattr(config, 'test_length', None)}）",
            "Software command": "软件指令停止",
        }
        start_labels = {
            "Status change": "踩上设备后开始",
        }
        position_labels = {
            "Inside area": "设备内",
            "Outside area": "设备外",
        }
        foot_labels = {
            "Not defined": "双脚 / 不限定",
            "Right": "右脚",
            "Left": "左脚",
        }
        rows = [
            ("测试类型", getattr(config, "mode_label", config.test_type)),
            ("结束方式", stop_labels.get(config.stop_type, config.stop_type)),
        ]
        if getattr(config, "number_of_jumps", None):
            rows.append(("测试次数", f"{config.number_of_jumps} 次"))
        if getattr(config, "test_length", None):
            rows.append(("测试时长", config.test_length))
        if hasattr(config, "treadmill_speed"):
            rows.append(("跑步机速度", f"{config.treadmill_speed:g} km/h"))
        if hasattr(config, "direction"):
            rows.append(("行进方向", config.direction))
        if hasattr(config, "start_type"):
            rows.append(("开始方式", start_labels.get(config.start_type, config.start_type)))
        if hasattr(config, "start_position"):
            rows.append(("起始位置", position_labels.get(config.start_position, config.start_position)))
        if hasattr(config, "starting_foot"):
            rows.append(("起始脚" if is_ground else "起跳脚",
                         "未指定" if is_ground and config.starting_foot == "Not defined"
                         else foot_labels.get(config.starting_foot, config.starting_foot)))
        if hasattr(config, "metronome_enabled"):
            rows.append(("节拍器", "开启" if config.metronome_enabled else "关闭"))
        if is_ground:
            rows.append(("设备段数", "准备页自动识别，开始前核对"))
        else:
            rows.append(("接触/腾空阈值", f">{config.min_contact_time}ms / >{config.min_flight_time}ms"))

        row_html = "".join(
            "<tr>"
            f"<td style='color:#8f9aab;padding:7px 0;'>{escape(label)}</td>"
            f"<td align='right' style='color:#edf2f8;padding:7px 0;'><b>{escape(str(value))}</b></td>"
            "</tr>"
            for label, value in rows
        )
        return (
            "<div>"
            "<table width='100%' cellspacing='0' cellpadding='0'>"
            f"{row_html}"
            "</table>"
            "<div style='margin-top:14px;color:#8f9aab;font-weight:700;'>推荐理由</div>"
            f"<div style='margin-top:6px;color:#d5dbe6;line-height:150%;'>{escape(reason)}</div>"
            "</div>"
        )
