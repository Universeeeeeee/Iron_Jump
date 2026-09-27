"""
setup_view.py — 测试配置页

复用现有 ParamPanel，提供配置摘要和"准备就绪"按钮。
用户确认配置后，发射 ready_signal(SessionSetup) 通知 MainWindow。
"""

from __future__ import annotations

import logging
from dataclasses import MISSING, dataclass
from datetime import datetime

from qtpy.QtCore import Signal, Qt
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QScrollArea, QFrame,
    QSizePolicy, QLineEdit, QComboBox, QDialog, QDialogButtonBox,
    QLabel, QMessageBox, QPushButton, QSpinBox, QStackedWidget, QMenu,
)

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton

from config.config_validation import validate_runtime_config
from config.test_config import AnyTestConfig
from data.subject_store import (
    SubjectProfile,
    SubjectSearchResult,
    SubjectStore,
    TeamProfile,
)
from ui.views.agent_config_panel import AgentConfigPanel
from ui.views.athletes_view import _DuplicateSubjectDialog, _SubjectDialog
from ui.param_panel import ParamPanel


log = logging.getLogger(__name__)

_TEAM_IDENTITY_PLACEHOLDER = "team_identity_placeholder"
_TEAM_IDENTITY_PERSONAL = "team_identity_personal"


SETUP_QSS = """
QWidget#SetupViewRoot {
  background-color: #0c1119;
  color: #e8edf5;
}
QFrame#TopSubjectBar,
QFrame#ModeBar {
  background-color: #121923;
  border: none;
  border-radius: 7px;
}
QFrame#ConfigWorkArea {
  background: transparent;
  border: none;
}
QFrame#ConfigSummaryCard {
  background-color: #121923;
  border: none;
  border-radius: 8px;
}
QLabel#PageTitle {
  color: #f5f7fb;
  font-size: 20px;
  font-weight: 700;
}
QLabel#PageSubtitle {
  color: #8f9bad;
  font-size: 13px;
}
QLabel#SummaryTitle {
  color: #f2f5f9;
  font-size: 18px;
  font-weight: 700;
}
QLabel#SummaryState {
  color: #ff9a3d;
  font-size: 14px;
  font-weight: 600;
}
QLabel#SummaryText {
  color: #c7cfdb;
  font-size: 14px;
}
QLabel#SummaryHint {
  color: #7f8a9a;
  font-size: 13px;
}
QLabel#SummarySectionLabel {
  color: #dfe5ee;
  font-size: 14px;
  font-weight: 700;
  margin-top: 2px;
}
QFrame#SummaryFilterRow {
  background: transparent;
  border: none;
  border-bottom: 1px solid #2b3746;
}
QLabel#SummaryRowLabel {
  color: #aeb8c7;
  font-size: 13px;
}
QLabel#FilterState {
  color: #c7cfdb;
  font-size: 13px;
  font-weight: 600;
}
QLabel#FilterDetails {
  color: #9eabba;
  font-size: 13px;
  padding: 0 0 5px 10px;
}
QFrame#DeviceStatusCard {
  background: transparent;
  border: none;
}
QLabel#DeviceState {
  font-size: 14px;
  font-weight: 700;
}
QLabel#DeviceMeta {
  color: #aeb8c7;
  font-size: 13px;
}
QLineEdit, QComboBox {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #e7ebf2;
  padding: 0 10px;
}
QPushButton {
  min-height: 32px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #d9dee8;
  padding: 0 16px;
}
QPushButton:hover {
  background-color: #232d3c;
}
QPushButton#SubjectPrimaryButton,
QPushButton#PrimaryStartButton,
QPushButton#SegmentButton:checked {
  background-color: #ff7a00;
  border-color: #ff7a00;
  color: white;
}
QPushButton#PrimaryStartButton {
  min-height: 46px;
  font-size: 14px;
  font-weight: 700;
  border-radius: 7px;
}
QPushButton#PrimaryStartButton:disabled {
  background-color: #242c37;
  border-color: #303946;
  color: #6f7a89;
}
QPushButton#SegmentButton {
  min-width: 112px;
  border: none;
  background-color: transparent;
  font-weight: 600;
}
QPushButton#SegmentButton:hover {
  background-color: rgba(255, 255, 255, 0.05);
}
QMenu {
  background-color: #242936;
  color: #e7ebf2;
  border: 1px solid rgba(105, 115, 135, 0.38);
  padding: 6px;
}
QMenu::item {
  padding: 8px 22px;
  border-radius: 5px;
}
QMenu::item:selected {
  background-color: rgba(255, 133, 15, 0.22);
}
QScrollArea#ManualConfigScroll,
QScrollArea#ManualConfigScroll QWidget#qt_scrollarea_viewport {
  background: #121923;
  border: none;
}
QScrollArea#ManualConfigScroll QScrollBar:vertical {
  width: 10px;
  margin: 0;
  border: none;
  background-color: #0c131d;
}
QScrollArea#ManualConfigScroll QScrollBar::handle:vertical {
  min-height: 32px;
  border-radius: 5px;
  background-color: #3a485a;
}
QScrollArea#ManualConfigScroll QScrollBar::handle:vertical:hover {
  background-color: #4b5b6f;
}
QScrollArea#ManualConfigScroll QScrollBar::add-line:vertical,
QScrollArea#ManualConfigScroll QScrollBar::sub-line:vertical {
  height: 0;
  border: none;
  background: transparent;
}
QScrollArea#ManualConfigScroll QScrollBar::add-page:vertical,
QScrollArea#ManualConfigScroll QScrollBar::sub-page:vertical {
  background: transparent;
}
"""

NEW_SUBJECT_DIALOG_QSS = """
QDialog#NewSubjectDialog {
  background-color: #121923;
  color: #e8edf5;
}
QDialog#NewSubjectDialog QLabel {
  color: #dfe5ee;
  font-size: 13px;
}
QDialog#NewSubjectDialog QLineEdit,
QDialog#NewSubjectDialog QComboBox,
QDialog#NewSubjectDialog QSpinBox {
  min-height: 34px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #e7ebf2;
  padding: 0 10px;
  selection-background-color: #ff7a00;
}
QDialog#NewSubjectDialog QComboBox::drop-down,
QDialog#NewSubjectDialog QSpinBox::up-button,
QDialog#NewSubjectDialog QSpinBox::down-button {
  border: none;
  background-color: #242e3c;
  width: 24px;
}
QDialog#NewSubjectDialog QPushButton {
  min-width: 80px;
  min-height: 34px;
  border-radius: 6px;
  border: 1px solid #354151;
  background-color: #1a2230;
  color: #e7ebf2;
  padding: 0 14px;
}
QDialog#NewSubjectDialog QPushButton:hover {
  background-color: #232d3c;
}
QDialog#NewSubjectDialog QPushButton:default {
  background-color: #ff7a00;
  border-color: #ff7a00;
  color: white;
}
"""


@dataclass(frozen=True)
class SessionSetup:
    config: AnyTestConfig
    subject_id: int | None = None
    subject: SubjectProfile | None = None
    subject_snapshot: dict | None = None
    team_id: int | None = None
    team_snapshot: dict | None = None
    config_source: str | None = None


class SetupView(QWidget):
    """测试配置视图 — 参数面板 + 配置摘要 + 准备就绪按钮。"""

    ready_signal = Signal(object)  # SessionSetup
    history_requested = Signal(object)  # SubjectSearchResult | None
    led_health_refresh_requested = Signal()

    def __init__(self, subject_store: SubjectStore | None = None,
                 llm_client=None, parent=None):
        super().__init__(parent)
        self._llm_client = llm_client
        self._subject_store = subject_store
        self._subject_search = None
        self._subject_combo = None
        self._team_identity_combo = None
        self._profile_update_baseline: SubjectProfile | None = None
        self._update_subject_profile_btn = None
        self._action_load_last_config = None
        self._action_history = None
        self._current_config: AnyTestConfig | None = None
        self._config_source: str | None = None
        self._config_errors: list[str] = []
        self._config_mode_index = 0
        self._syncing_config_to_panel = False
        self._device_state = "disconnected"
        self._device_state_message = ""
        self._led_health_result: dict | None = None
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("SetupViewRoot")
        self.setStyleSheet(SETUP_QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 22)
        layout.setSpacing(16)

        # ===== 页面标题 =====
        header = QHBoxLayout()
        header.setSpacing(12)
        title_column = QVBoxLayout()
        title_column.setSpacing(3)
        title = QLabel("测试")
        title.setObjectName("PageTitle")
        subtitle = QLabel("配置测试参数并连接设备")
        subtitle.setObjectName("PageSubtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch(1)
        layout.addLayout(header)

        workspace = QHBoxLayout()
        workspace.setSpacing(16)

        # ===== 左侧配置工作区 =====
        config_area = QFrame()
        config_area.setObjectName("ConfigWorkArea")
        config_layout = QVBoxLayout(config_area)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(12)

        if self._subject_store is not None:
            config_layout.addWidget(self._create_subject_bar())

        # ===== 配置方式 =====
        mode_bar = QFrame()
        mode_bar.setObjectName("ModeBar")
        mode_layout = QHBoxLayout(mode_bar)
        mode_layout.setContentsMargins(12, 6, 12, 6)
        mode_layout.setSpacing(8)
        mode_label = QLabel("配置方式")
        mode_label.setStyleSheet("font-size: 11pt; font-weight: 700; color: #e7ebf2;")
        mode_layout.addWidget(mode_label)

        self._btn_mode_agent = QPushButton("智能配置")
        self._btn_mode_manual = QPushButton("手动配置")
        for button in (self._btn_mode_agent, self._btn_mode_manual):
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(34)
        self._btn_mode_agent.setChecked(True)
        self._btn_mode_agent.clicked.connect(lambda: self._set_config_mode(0))
        self._btn_mode_manual.clicked.connect(lambda: self._set_config_mode(1))
        mode_layout.addWidget(self._btn_mode_agent)
        mode_layout.addWidget(self._btn_mode_manual)
        mode_layout.addStretch()
        self._mode_status_chip = QLabel("")
        self._mode_status_chip.setStyleSheet("color: #8f9bad; font-size: 12px;")
        mode_layout.addWidget(self._mode_status_chip)
        config_layout.addWidget(mode_bar)

        # ===== 配置工作区 =====
        self._config_stack = QStackedWidget()
        self._agent_panel = AgentConfigPanel(subject_store=self._subject_store, llm_client=self._llm_client)
        self._config_stack.addWidget(self._agent_panel)

        self.param_panel = ParamPanel()
        scroll = QScrollArea()
        scroll.setObjectName("ManualConfigScroll")
        scroll.setWidget(self.param_panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._config_stack.addWidget(scroll)
        config_layout.addWidget(self._config_stack, 1)
        workspace.addWidget(config_area, 1)

        # ===== 右侧配置摘要 =====
        self._status_bar = QFrame()
        self._status_bar.setObjectName("ConfigSummaryCard")
        self._status_bar.setFixedWidth(320)
        self._status_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        status_layout = QVBoxLayout(self._status_bar)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(10)
        status_title = QLabel("当前配置")
        status_title.setObjectName("SummaryTitle")
        status_layout.addWidget(status_title)
        self._summary_state_label = QLabel("等待确认")
        self._summary_state_label.setObjectName("SummaryState")
        status_layout.addWidget(self._summary_state_label)
        summary_section = QLabel("配置摘要")
        summary_section.setObjectName("SummarySectionLabel")
        status_layout.addWidget(summary_section)
        self._summary_label = QLabel("")
        self._summary_label.setObjectName("SummaryText")
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        status_layout.addWidget(self._summary_label)

        filter_row = QFrame()
        filter_row.setObjectName("SummaryFilterRow")
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 7, 0, 8)
        filter_layout.setSpacing(8)
        filter_label = QLabel("滤波参数")
        filter_label.setObjectName("SummaryRowLabel")
        filter_layout.addWidget(filter_label)
        filter_layout.addStretch(1)
        self._filter_state_label = QLabel("—")
        self._filter_state_label.setObjectName("FilterState")
        filter_layout.addWidget(self._filter_state_label)
        status_layout.addWidget(filter_row)

        self._filter_details_label = QLabel("")
        self._filter_details_label.setObjectName("FilterDetails")
        self._filter_details_label.setWordWrap(True)
        self._filter_details_label.hide()
        status_layout.addWidget(self._filter_details_label)

        device_section = QLabel("设备状态")
        device_section.setObjectName("SummarySectionLabel")
        status_layout.addWidget(device_section)

        device_card = QFrame()
        device_card.setObjectName("DeviceStatusCard")
        device_layout = QVBoxLayout(device_card)
        device_layout.setContentsMargins(0, 2, 0, 0)
        device_layout.setSpacing(7)
        device_state_row = QHBoxLayout()
        device_state_row.setContentsMargins(0, 0, 0, 0)
        self._device_state_label = QLabel("")
        self._device_state_label.setObjectName("DeviceState")
        device_state_row.addWidget(self._device_state_label)
        device_state_row.addStretch(1)
        self.btn_refresh_led_health = QPushButton("刷新")
        self.btn_refresh_led_health.setObjectName("DeviceRefreshButton")
        self.btn_refresh_led_health.setFixedWidth(72)
        self.btn_refresh_led_health.clicked.connect(
            self.led_health_refresh_requested.emit
        )
        device_state_row.addWidget(self.btn_refresh_led_health)
        device_layout.addLayout(device_state_row)
        self._device_meta_label = QLabel("")
        self._device_meta_label.setObjectName("DeviceMeta")
        self._device_meta_label.setWordWrap(True)
        device_layout.addWidget(self._device_meta_label)
        status_layout.addWidget(device_card)
        workspace.addWidget(self._status_bar, 0, Qt.AlignTop)
        layout.addLayout(workspace, 1)

        # ===== 准备就绪按钮 =====
        self.btn_ready = QPushButton("进入测试准备")
        self.btn_ready.setObjectName("PrimaryStartButton")
        self.btn_ready.setFixedWidth(330)
        self.btn_ready.clicked.connect(self._on_ready_clicked)
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.addStretch(1)
        action_layout.addWidget(self.btn_ready)
        layout.addLayout(action_layout)

        # ===== 连接参数变更 → 更新摘要 =====
        self._agent_panel.config_confirmed.connect(self._on_agent_config_confirmed)
        self._agent_panel.profile_changed.connect(self._sync_profile_update_action)
        self.param_panel.config_changed.connect(self._on_param_panel_changed)
        self._update_mode_status()
        self._update_summary()
        self.on_device_state("disconnected", "设备未连接")

    def _create_subject_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("TopSubjectBar")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        label = QLabel("测试对象")
        label.setMinimumWidth(64)
        label.setStyleSheet("font-size: 13px; font-weight: 700; color: #eef2f8;")

        self._subject_search = QLineEdit()
        self._subject_search.setPlaceholderText("搜索姓名")
        self._subject_search.setMinimumWidth(160)

        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(260)
        self._subject_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        identity_label = QLabel("测试身份")
        identity_label.setMinimumWidth(64)
        identity_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #eef2f8;"
        )
        self._team_identity_combo = QComboBox()
        self._team_identity_combo.setMinimumWidth(180)

        self._update_subject_profile_btn = QPushButton("更新运动员档案")
        self._update_subject_profile_btn.hide()

        btn_new = MPushButton("新建")
        btn_new.setObjectName("SubjectPrimaryButton")
        btn_new.setMinimumWidth(80)

        btn_more = MPushButton("更多")
        btn_more.setMinimumWidth(80)
        menu = QMenu(btn_more)
        self._action_load_last_config = menu.addAction("加载上次参数")
        self._action_history = menu.addAction("历史记录")
        btn_more.setMenu(menu)

        layout.addWidget(label)
        layout.addWidget(self._subject_search)
        layout.addWidget(self._subject_combo, 1)
        layout.addWidget(identity_label)
        layout.addWidget(self._team_identity_combo)
        layout.addWidget(self._update_subject_profile_btn)
        layout.addWidget(btn_new)
        layout.addWidget(btn_more)

        self._subject_search.textChanged.connect(self._refresh_subject_results)
        self._subject_combo.currentIndexChanged.connect(self._sync_subject_to_agent)
        self._team_identity_combo.currentIndexChanged.connect(self._on_team_identity_changed)
        self._update_subject_profile_btn.clicked.connect(
            self._on_update_subject_profile_clicked
        )
        btn_new.clicked.connect(self._on_new_subject_clicked)
        self._action_load_last_config.triggered.connect(self._on_load_last_config_clicked)
        self._action_history.triggered.connect(self._on_history_clicked)
        self._refresh_subject_results()

        return frame

    def _refresh_subject_results(self, query: str = "") -> None:
        if self._subject_store is None or self._subject_combo is None:
            return

        current_id = self._current_subject_id()
        self._subject_combo.blockSignals(True)
        self._subject_combo.clear()
        self._subject_combo.addItem("临时测试（通用参数）", None)

        try:
            results = self._subject_store.search_subjects(query)
        except Exception:
            log.exception("Failed to search subjects")
            self._subject_combo.blockSignals(False)
            return

        selected_index = 0
        for result in results:
            self._subject_combo.addItem(self._format_subject_result(result), result)
            if result.subject.id == current_id:
                selected_index = self._subject_combo.count() - 1

        self._subject_combo.setCurrentIndex(selected_index)
        self._subject_combo.blockSignals(False)
        self._sync_subject_to_agent()

    def refresh_subjects(self) -> None:
        query = self._subject_search.text() if self._subject_search is not None else ""
        self._refresh_subject_results(query)

    def current_subject_result(self) -> SubjectSearchResult | None:
        return self._current_subject_result()

    def select_subject(self, subject_id: int) -> bool:
        if self._subject_store is None or self._subject_combo is None:
            return False
        try:
            results = self._subject_store.search_subjects("")
        except Exception:
            log.exception("Failed to select subject")
            return False
        for result in results:
            if result.subject.id != subject_id:
                continue
            if self._subject_search is not None:
                self._subject_search.setText(result.subject.display_name)
            self._add_or_select_subject(result)
            self._sync_subject_to_agent()
            return True
        return False

    def _format_subject_result(self, result: SubjectSearchResult) -> str:
        labels = result.display_labels
        parts = [result.subject.display_name]
        for key in ("Age", "Level", "Focus", "Last test"):
            value = labels.get(key)
            if value:
                parts.append(f"{key}: {value}")
        return "  |  ".join(parts)

    def _current_subject_result(self) -> SubjectSearchResult | None:
        if self._subject_combo is None:
            return None
        data = self._subject_combo.itemData(self._subject_combo.currentIndex(), Qt.UserRole)
        return data if isinstance(data, SubjectSearchResult) else None

    def _current_subject_id(self) -> int | None:
        result = self._current_subject_result()
        return result.subject.id if result else None

    def _on_new_subject_clicked(self) -> None:
        if self._subject_store is None:
            return

        values = _SubjectDialog.get_values(self, store=self._subject_store)
        if values is None:
            return

        subject_values = dict(values)
        team_ids = subject_values.pop("team_ids", [])
        team_id = team_ids[0] if team_ids else None
        display_name = subject_values["display_name"]

        try:
            matches = self._subject_store.find_duplicate_subjects(
                display_name, subject_values["birth_year"]
            )
            if matches:
                duplicate_dialog = _DuplicateSubjectDialog(matches, self)
                if duplicate_dialog.exec_() != QDialog.Accepted:
                    return
                candidate = duplicate_dialog.selected_result()
                if duplicate_dialog.action == "reuse" and candidate is not None:
                    self._subject_store.restore_subject_and_add_to_team(
                        candidate.subject.id, team_id
                    )
                    subject_id = candidate.subject.id
                else:
                    subject_id = self._subject_store.create_subject(
                        **subject_values, team_id=team_id
                    )
            else:
                subject_id = self._subject_store.create_subject(
                    **subject_values, team_id=team_id
                )
        except Exception as exc:
            log.exception("Failed to create subject")
            QMessageBox.warning(self, "新建受试者", f"创建失败：{exc}")
            return

        try:
            created = self._find_subject_result(display_name, subject_id)
        except Exception:
            log.exception("Failed to reload created subject")
            created = None

        if self._subject_search is not None:
            self._subject_search.setText(display_name)
        if created is not None:
            self._add_or_select_subject(created)
        self._sync_subject_to_agent()

    def _build_new_subject_dialog(
        self,
    ) -> tuple[QDialog, QLineEdit, QSpinBox, QComboBox]:
        dialog = QDialog(self)
        dialog.setObjectName("NewSubjectDialog")
        dialog.setWindowTitle("新建受试者")
        dialog.setMinimumWidth(380)
        dialog.setStyleSheet(NEW_SUBJECT_DIALOG_QSS)
        form = QFormLayout(dialog)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        name_edit = QLineEdit()
        birth_year_spin = QSpinBox()
        birth_year_spin.setRange(1900, datetime.now().year)
        birth_year_spin.setValue(1990)

        level_combo = QComboBox()
        level_combo.addItems(["beginner", "intermediate", "advanced"])
        level_combo.setCurrentText("intermediate")

        form.addRow("姓名", name_edit)
        form.addRow("出生年份", birth_year_spin)
        form.addRow("训练水平", level_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        return dialog, name_edit, birth_year_spin, level_combo

    def _find_subject_result(
        self, query: str, subject_id: int
    ) -> SubjectSearchResult | None:
        if self._subject_store is None:
            return None
        for result in self._subject_store.search_subjects(query):
            if result.subject.id == subject_id:
                return result
        return None

    def _add_or_select_subject(self, result: SubjectSearchResult) -> None:
        if self._subject_combo is None:
            return
        for index in range(self._subject_combo.count()):
            data = self._subject_combo.itemData(index, Qt.UserRole)
            if isinstance(data, SubjectSearchResult) and data.subject.id == result.subject.id:
                self._subject_combo.setCurrentIndex(index)
                return

        self._subject_combo.addItem(self._format_subject_result(result), result)
        self._subject_combo.setCurrentIndex(self._subject_combo.count() - 1)

    def _sync_subject_to_agent(self, *_args) -> None:
        result = self._current_subject_result()
        self._profile_update_baseline = result.subject if result else None
        if hasattr(self, "_agent_panel"):
            self._agent_panel.set_subject_result(result)
        self._populate_team_identity_choices(result)
        self._sync_profile_update_action()
        selected = result is not None
        if self._action_history is not None:
            self._action_history.setEnabled(selected)
        if self._action_load_last_config is not None:
            self._action_load_last_config.setEnabled(selected)
        if hasattr(self, "_summary_label"):
            self._update_summary()

    def _populate_team_identity_choices(
        self, result: SubjectSearchResult | None
    ) -> None:
        if self._team_identity_combo is None:
            return
        self._team_identity_combo.blockSignals(True)
        try:
            self._team_identity_combo.clear()
            if result is None:
                self._team_identity_combo.addItem(
                    "不以团队身份测试", _TEAM_IDENTITY_PERSONAL
                )
                self._team_identity_combo.setCurrentIndex(0)
                self._team_identity_combo.setEnabled(False)
                return
            self._team_identity_combo.addItem(
                "请选择本次测试身份", _TEAM_IDENTITY_PLACEHOLDER
            )
            try:
                teams = self._subject_store.get_subject_teams(result.subject.id)
            except Exception:
                log.exception("Failed to load subject teams")
                teams = []
            for team in teams:
                self._team_identity_combo.addItem(team.name, team)
            self._team_identity_combo.addItem(
                "不以团队身份测试", _TEAM_IDENTITY_PERSONAL
            )
            self._team_identity_combo.setCurrentIndex(0)
            self._team_identity_combo.setEnabled(True)
        finally:
            self._team_identity_combo.blockSignals(False)

    def _on_team_identity_changed(self, *_args) -> None:
        self._sync_ready_button()

    def _selected_team_identity(self) -> tuple[int | None, dict | None] | None:
        result = self._current_subject_result()
        if result is None:
            return None, None
        if self._team_identity_combo is None:
            return None
        choice = self._team_identity_combo.currentData(Qt.UserRole)
        if isinstance(choice, TeamProfile):
            return choice.id, {"id": choice.id, "name": choice.name}
        if choice == _TEAM_IDENTITY_PERSONAL:
            return None, None
        return None

    def _current_safe_profile_values(self) -> dict[str, object] | None:
        baseline = self._profile_update_baseline
        if baseline is None:
            return None
        snapshot = self._agent_panel.current_profile_snapshot()

        def measurement_value(value: object, original: float | None) -> float | None:
            numeric = float(value)
            if original is None and numeric == 0.0:
                return None
            return numeric

        return {
            "height_cm": measurement_value(snapshot["height_cm"], baseline.height_cm),
            "weight_kg": measurement_value(snapshot["weight_kg"], baseline.weight_kg),
            "level": snapshot["level"],
            "focus_side": snapshot["focus_side"],
        }

    def _sync_profile_update_action(self, *_args) -> None:
        if self._update_subject_profile_btn is None:
            return
        baseline = self._profile_update_baseline
        values = self._current_safe_profile_values()
        changed = values is not None and any(
            values[name] != getattr(baseline, name)
            for name in values
        )
        self._update_subject_profile_btn.setHidden(not changed)

    def _on_update_subject_profile_clicked(self) -> None:
        baseline = self._profile_update_baseline
        values = self._current_safe_profile_values()
        if baseline is None or values is None or self._subject_store is None:
            return
        changes = [
            ("身高", baseline.height_cm, values["height_cm"]),
            ("体重", baseline.weight_kg, values["weight_kg"]),
            ("训练水平", baseline.level, values["level"]),
            ("侧重训练", baseline.focus_side, values["focus_side"]),
        ]
        changed_lines = [
            f"{label}：{old} → {new}"
            for label, old, new in changes
            if old != new
        ]
        if not changed_lines:
            return
        answer = QMessageBox.question(
            self,
            "更新运动员档案",
            "将整体更新运动员档案（不包含出生年份）：\n\n"
            + "\n".join(changed_lines),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._subject_store.update_subject_from_session_profile(
                baseline.id,
                height_cm=values["height_cm"],
                weight_kg=values["weight_kg"],
                level=values["level"],
                focus_side=values["focus_side"],
            )
            self._profile_update_baseline = self._subject_store.get_subject(baseline.id)
            updated = self._profile_update_baseline
            if updated is not None and self._subject_combo is not None:
                refreshed = self._find_subject_result(updated.display_name, updated.id)
                if refreshed is not None:
                    index = self._subject_combo.currentIndex()
                    self._subject_combo.setItemData(index, refreshed, Qt.UserRole)
                    self._subject_combo.setItemText(
                        index, self._format_subject_result(refreshed)
                    )
        except Exception as exc:
            log.exception("Failed to update subject profile from test setup")
            QMessageBox.warning(self, "更新运动员档案", f"更新失败：{exc}")
            return
        self._sync_profile_update_action()

    def _on_history_clicked(self) -> None:
        result = self._current_subject_result()
        if result is None:
            QMessageBox.information(self, "历史记录", "请先选择受试者。")
            return
        self.history_requested.emit(result)

    def _on_load_last_config_clicked(self) -> None:
        if self._subject_store is None:
            return

        result = self._current_subject_result()
        if result is None:
            QMessageBox.information(self, "加载上次参数", "请先选择受试者。")
            return

        try:
            session = self._subject_store.get_last_session(result.subject.id)
        except Exception as exc:
            log.exception("Failed to load last subject session")
            QMessageBox.warning(self, "加载上次参数", f"读取失败：{exc}")
            return

        if session is None:
            QMessageBox.information(self, "加载上次参数", "该受试者暂无历史测试。")
            return

        self._set_current_config(session.config, "last_session")

    def load_config_from_history(self, config: AnyTestConfig) -> None:
        self._set_current_config(config, "history")

    def _set_config_mode(self, index: int) -> None:
        if index == self._config_mode_index:
            self._btn_mode_agent.setChecked(index == 0)
            self._btn_mode_manual.setChecked(index == 1)
            return
        self._config_mode_index = index
        self._btn_mode_agent.setChecked(index == 0)
        self._btn_mode_manual.setChecked(index == 1)
        self._update_mode_status()
        self._config_stack.setCurrentIndex(index)
        if index == 0 and self._current_config is not None:
            combo = self._agent_panel._test_type_combo
            target = combo.findText(self._current_config.test_type)
            if target >= 0:
                self._agent_panel._clear_pending_config()
                combo.setCurrentIndex(target)
        if index == 1:
            if self._current_config is not None:
                self._syncing_config_to_panel = True
                try:
                    self.param_panel.set_config(self._current_config)
                finally:
                    self._syncing_config_to_panel = False
            elif self._current_config is None:
                self.param_panel.set_test_type(self._agent_panel.current_test_type())
                self._set_current_config(self.param_panel.get_config(), "manual")

    def _update_mode_status(self) -> None:
        mode = "智能配置" if self._config_mode_index == 0 else "手动配置"
        self._mode_status_chip.setText(f"●  {mode} · 测试准备")

    def _on_agent_config_confirmed(self, config: AnyTestConfig) -> None:
        self._set_current_config(config, "agent")

    def _on_param_panel_changed(self) -> None:
        if self._syncing_config_to_panel:
            return
        if self._config_mode_index == 1:
            self._set_current_config(self.param_panel.get_config(), "manual")

    def _set_current_config(self, config: AnyTestConfig, source: str) -> None:
        self._current_config = config
        self._config_source = source
        self._config_errors = validate_runtime_config(config)
        if source in {"last_session", "history"}:
            self._syncing_config_to_panel = True
            try:
                self.param_panel.set_config(config)
            finally:
                self._syncing_config_to_panel = False
        self._update_summary()

    def _update_summary(self):
        """根据已确认配置更新配置摘要。"""
        config = self._current_config
        if config is None:
            self._summary_label.setText("未确认，请生成建议配置或切换到手动配置。")
            self._summary_state_label.setText("等待确认")
            self._filter_state_label.setText("—")
            self._filter_details_label.clear()
            self._filter_details_label.hide()
            self._sync_summary_label_height()
            if hasattr(self, "btn_ready"):
                self.btn_ready.setEnabled(False)
            return

        source_labels = {
            "agent": "智能配置",
            "manual": "手动配置",
            "last_session": "上次参数",
            "history": "历史参数",
        }
        source = source_labels.get(self._config_source or "", "当前配置")
        mode = getattr(config, "mode_label", config.test_type)
        result = self._current_subject_result()
        subject_name = result.subject.display_name if result else "临时测试"
        parts = [
            f"测试对象：{subject_name}",
            f"配置方式：{source}",
            f"测试模式：{mode}",
        ]
        if hasattr(config, "start_type"):
            parts.append(f"启动：{config.start_type}")
        stop_text = config.stop_type
        if getattr(config, "test_length", None):
            stop_text += f" · {config.test_length}"
        parts.append(f"停止方式：{stop_text}")
        if getattr(config, "number_of_jumps", None):
            parts.append(f"目标：{config.number_of_jumps} 次")
        if hasattr(config, "treadmill_speed"):
            parts.append(f"跑步机速度：{config.treadmill_speed:g} km/h")
        if hasattr(config, "direction"):
            parts.append(f"行走方向：{config.direction}")
        if getattr(config, "metronome_enabled", False):
            parts.append(f"节拍器：{config.metronome_bpm} BPM")

        self._summary_label.setText("\n".join(parts))
        self._update_filter_summary(config)
        if self._config_errors:
            self._summary_state_label.setText("配置需要修正")
            self._summary_label.setText(
                self._summary_label.text()
                + "\n\n"
                + "\n".join(f"• {error}" for error in self._config_errors)
            )
        else:
            self._summary_state_label.setText("配置已确认")
        self._sync_summary_label_height()
        self._sync_ready_button()

    def _sync_ready_button(self) -> None:
        if not hasattr(self, "btn_ready"):
            return
        identity = self._selected_team_identity()
        self.btn_ready.setEnabled(
            self._current_config is not None
            and not self._config_errors
            and identity is not None
        )

    def _update_filter_summary(self, config: AnyTestConfig) -> None:
        changed = self._changed_filter_values(config)
        if not changed:
            self._filter_state_label.setText("默认配置")
            self._filter_state_label.setStyleSheet("")
            self._filter_details_label.clear()
            self._filter_details_label.hide()
            return

        self._filter_state_label.setText("已修改")
        self._filter_state_label.setStyleSheet("color: #ff9a3d;")
        self._filter_details_label.setText(
            "\n".join(
                f"{self._filter_display_name(name)}："
                f"{self._format_filter_value(name, value)}"
                for name, value in changed
            )
        )
        self._filter_details_label.show()

    @staticmethod
    def _changed_filter_values(config: AnyTestConfig) -> list[tuple[str, object]]:
        names = ParamPanel._LAYER3_ORDER.get(config.test_type, ())
        dataclass_fields = getattr(type(config), "__dataclass_fields__", {})
        changed = []
        for name in names:
            field = dataclass_fields.get(name)
            if field is None or field.default is MISSING:
                continue
            value = getattr(config, name, MISSING)
            if value is not MISSING and value != field.default:
                changed.append((name, value))
        return changed

    @staticmethod
    def _filter_display_name(name: str) -> str:
        return {
            "min_contact_time": "接触阈值",
            "min_flight_time": "腾空阈值",
            "max_flight_time": "最大腾空时间",
            "flight_time_review_threshold": "腾空复核阈值",
            "step_length_calculation": "步长计算方式",
            "min_step_length": "最小步长",
            "min_gap_between_feet": "两脚最小间距",
            "min_foot_length": "最小足长",
            "filter_gaitr_in": "GaitR 进入过滤",
            "filter_gaitr_out": "GaitR 离开过滤",
            "automatic_data_filter": "自动数据过滤",
        }.get(name, name)

    @staticmethod
    def _format_filter_value(name: str, value: object) -> str:
        if name in {
            "min_contact_time",
            "min_flight_time",
            "max_flight_time",
            "flight_time_review_threshold",
        }:
            return f"{value} ms"
        if name in {"min_step_length", "min_gap_between_feet", "min_foot_length"}:
            return f"{value:g} cm"
        if name in {"filter_gaitr_in", "filter_gaitr_out"}:
            return f"{value} LED"
        if name == "automatic_data_filter":
            return f"{value}%"
        return str(value)

    def on_device_state(self, state: str, message: str = "") -> None:
        """Show device information without gating entry to test preparation."""
        self._device_state = state
        self._device_state_message = message
        if state not in {"connected", "streaming"}:
            self._led_health_result = None
        self._render_device_status()

    def on_led_health(self, result: dict) -> None:
        self._led_health_result = dict(result)
        self._render_device_status()

    @staticmethod
    def _format_led_indices(indices: list[int]) -> str:
        values = [str(value) for value in indices[:16]]
        if len(indices) > 16:
            values.append(f"等{len(indices)}个")
        return "、".join(values)

    def _render_device_status(self) -> None:
        state = self._device_state
        message = self._device_state_message
        labels = {
            "disconnected": ("● 设备未连接", "#8f9bad", "未连接"),
            "connecting": ("● 正在连接设备", "#f0a24a", "连接中"),
            "connected": ("● 设备已连接", "#67c98b", "正常"),
            "streaming": ("● 正在采集", "#67c98b", "正常"),
            "error": ("● 设备异常", "#f06a6a", "异常"),
        }
        text, color, communication = labels.get(
            state, (message or state, "#8f9bad", message or state)
        )
        health_lines: list[str] = []
        health_status = (self._led_health_result or {}).get("status")
        self.btn_refresh_led_health.setEnabled(
            state not in {"connecting", "streaming"}
            and health_status != "checking"
        )
        if health_status == "checking":
            health_lines.append("LED状态：检测中…")
        elif health_status == "warning":
            color = "#f06a6a"
            text = "● 设备已连接 · LED异常"
            disconnected = self._led_health_result.get("disconnected_leds", [])
            flickering = self._led_health_result.get("flickering_leds", [])
            if disconnected:
                health_lines.append(
                    "未联通/持续遮挡 LED："
                    + self._format_led_indices(disconnected)
                )
            if flickering:
                health_lines.append(
                    "闪烁 LED：" + self._format_led_indices(flickering)
                )
        elif health_status == "insufficient":
            health_lines.append("LED状态：未获取到足够数据，请刷新")
        self._device_state_label.setText(text)
        self._device_state_label.setToolTip(message)
        self._device_state_label.setStyleSheet(f"color: {color};")
        meta_lines = [f"通信状态：{communication}", "标称采样率：1000 Hz"]
        meta_lines.extend(health_lines)
        self._device_meta_label.setText("\n".join(meta_lines))

    def _sync_summary_label_height(self) -> None:
        self._summary_label.ensurePolished()
        content_width = max(220, self._status_bar.minimumWidth() - 36)
        content_height = self._summary_label.heightForWidth(content_width)
        minimum_height = max(
            content_height,
            self._summary_label.fontMetrics().lineSpacing() * 2,
        )
        self._summary_label.setMinimumHeight(minimum_height)
        self._summary_label.updateGeometry()
        self._status_bar.updateGeometry()

    def _on_ready_clicked(self):
        """收集配置并发射信号。"""
        if self._current_config is None:
            QMessageBox.information(self, "准备就绪", "请先确认一份测试配置。")
            return
        self._config_errors = validate_runtime_config(self._current_config)
        if self._config_errors:
            QMessageBox.warning(
                self,
                "配置需要修正",
                "\n".join(self._config_errors),
            )
            self._update_summary()
            return
        config = self._current_config
        result = self._current_subject_result()
        identity = self._selected_team_identity()
        if identity is None:
            QMessageBox.information(self, "准备就绪", "请选择本次测试身份。")
            self._sync_ready_button()
            return
        team_id, team_snapshot = identity
        snapshot = self._agent_panel.current_profile_snapshot()
        snapshot["display_name"] = (
            result.subject.display_name if result else "临时测试"
        )
        self.ready_signal.emit(
            SessionSetup(
                config=config,
                subject_id=result.subject.id if result else None,
                subject=result.subject if result else None,
                subject_snapshot=snapshot,
                team_id=team_id,
                team_snapshot=team_snapshot,
                config_source=self._config_source,
            )
        )
