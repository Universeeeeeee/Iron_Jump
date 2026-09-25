"""Local athlete-management module."""

from __future__ import annotations

import logging
import sys
from datetime import datetime

from qtpy.QtCore import QSignalBlocker, QTimer, Signal, Qt
from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from data.subject_store import (
    SubjectProfile,
    SubjectSearchResult,
    SubjectStore,
    TeamProfile,
)
from hardware.rc200u import STATUS_NO_CARD, Rc200uReader, Rc200uUnavailable


log = logging.getLogger(__name__)


ATHLETES_QSS = """
QWidget#AthletesViewRoot {
    background: #0c1119;
    color: #e7ebf2;
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
QFrame#AthleteToolbar,
QFrame#AthleteTableCard {
    background: #121923;
    border: 1px solid #293442;
    border-radius: 8px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 32px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #e7ebf2;
    padding: 0 9px;
}
QPushButton {
    min-height: 32px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #d9dee8;
    padding: 0 14px;
}
QPushButton:hover {
    background: #232d3c;
}
QPushButton#PrimaryButton {
    background: #ff7a00;
    border-color: #ff7a00;
    color: white;
    font-weight: 650;
}
QTableWidget {
    background: #121923;
    alternate-background-color: #151d28;
    color: #dfe5ee;
    border: none;
    gridline-color: #26313f;
    selection-background-color: #273446;
    selection-color: white;
}
QHeaderView::section {
    background: #171f2b;
    color: #9da8b8;
    border: none;
    border-bottom: 1px solid #2b3543;
    padding: 8px;
}
"""


class AthletesView(QWidget):
    """Search and maintain athletes stored in the local SQLite database."""

    test_requested = Signal(object)  # SubjectSearchResult
    results_requested = Signal(object)  # SubjectSearchResult
    team_results_requested = Signal(object)  # TeamProfile
    ALL_TEAMS = "all-teams"
    WITHOUT_TEAM = "without-team"

    def __init__(
        self,
        subject_store: SubjectStore | None,
        parent=None,
        *,
        rfid_reader=None,
    ):
        super().__init__(parent)
        self._subject_store = subject_store
        self._results: list[SubjectSearchResult] = []
        self._rfid_reader = rfid_reader
        self._rfid_uid: str | None = None
        self._rfid_read_status: int | None = None
        self._rfid_error: str | None = None
        if self._rfid_reader is None and sys.platform == "win32":
            try:
                self._rfid_reader = Rc200uReader()
            except Rc200uUnavailable as exc:
                self._rfid_reader = None
                self._rfid_error = str(exc)
        self._build_ui()
        self.refresh()
        self._rfid_timer = QTimer(self)
        self._rfid_timer.setInterval(250)
        self._rfid_timer.timeout.connect(self._poll_rfid)
        if self._rfid_reader is not None:
            self._rfid_timer.start()
        self._sync_rfid_status()

    def _build_ui(self) -> None:
        self.setObjectName("AthletesViewRoot")
        self.setStyleSheet(ATHLETES_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 22)
        layout.setSpacing(16)

        title = QLabel("运动员")
        title.setObjectName("PageTitle")
        subtitle = QLabel("管理保存在本机的运动员档案和测试入口")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        rfid_bar = QFrame()
        rfid_bar.setObjectName("AthleteToolbar")
        rfid_layout = QHBoxLayout(rfid_bar)
        rfid_layout.setContentsMargins(12, 8, 12, 8)
        rfid_layout.setSpacing(8)
        self._rfid_status = QLabel()
        self._btn_bind_card = QPushButton("绑定当前卡")
        self._btn_bind_card.clicked.connect(self._bind_current_card)
        self._btn_unbind_card = QPushButton("解绑卡片")
        self._btn_unbind_card.clicked.connect(self._unbind_selected_card)
        rfid_layout.addWidget(self._rfid_status, 1)
        rfid_layout.addWidget(self._btn_bind_card)
        rfid_layout.addWidget(self._btn_unbind_card)
        layout.addWidget(rfid_bar)

        toolbar = QFrame()
        toolbar.setObjectName("AthleteToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索运动员姓名")
        self._search.textChanged.connect(self.refresh)
        toolbar_layout.addWidget(self._search, 1)

        self._team_filter = QComboBox()
        self._team_filter.currentIndexChanged.connect(self.refresh)
        toolbar_layout.addWidget(self._team_filter)

        self._btn_new = QPushButton("新建运动员")
        self._btn_new.setObjectName("PrimaryButton")
        self._btn_new.clicked.connect(self._create_subject)
        toolbar_layout.addWidget(self._btn_new)

        self._btn_team_results = QPushButton("查看团队结果")
        self._btn_team_results.clicked.connect(self._show_filtered_team_results)
        toolbar_layout.addWidget(self._btn_team_results)

        self._btn_edit = QPushButton("编辑")
        self._btn_edit.clicked.connect(self._edit_selected)
        toolbar_layout.addWidget(self._btn_edit)

        self._btn_archive = QPushButton("归档")
        self._btn_archive.clicked.connect(self._archive_selected)
        toolbar_layout.addWidget(self._btn_archive)
        layout.addWidget(toolbar)

        table_card = QFrame()
        table_card.setObjectName("AthleteTableCard")
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(1, 1, 1, 12)
        card_layout.setSpacing(10)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels(
            [
                "姓名",
                "年龄",
                "身高 / 体重",
                "训练水平",
                "训练侧重",
                "所属团队",
                "最近测试",
                "RFID",
            ]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._sync_actions)
        self._table.itemDoubleClicked.connect(lambda _item: self._start_selected_test())
        card_layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(12, 0, 12, 0)
        actions.addStretch(1)
        self._btn_results = QPushButton("查看结果")
        self._btn_results.clicked.connect(self._show_selected_results)
        actions.addWidget(self._btn_results)
        self._btn_test = QPushButton("使用该运动员测试")
        self._btn_test.setObjectName("PrimaryButton")
        self._btn_test.clicked.connect(self._start_selected_test)
        actions.addWidget(self._btn_test)
        card_layout.addLayout(actions)
        layout.addWidget(table_card, 1)
        self._sync_actions()

    def refresh(self, _query: str | None = None) -> None:
        selected_id = None
        selected = self._selected_result()
        if selected is not None:
            selected_id = selected.subject.id

        if self._subject_store is None:
            self._results = []
        else:
            try:
                self._populate_team_filter()
                team_filter = self._team_filter.currentData()
                team_id = team_filter if isinstance(team_filter, int) else None
                self._results = self._subject_store.search_subjects(
                    self._search.text().strip(),
                    team_id=team_id,
                    without_team=team_filter == self.WITHOUT_TEAM,
                )
            except Exception:
                log.exception("Failed to refresh athlete list")
                self._results = []

        self._table.setRowCount(0)
        selected_row = -1
        current_year = datetime.now().year
        focus_labels = {
            "": "均衡",
            "left": "左侧",
            "right": "右侧",
            "both": "双侧",
        }
        for row, result in enumerate(self._results):
            subject = result.subject
            self._table.insertRow(row)
            measurements = _measurement_text(subject)
            values = [
                subject.display_name,
                str(max(0, current_year - subject.birth_year)),
                measurements,
                subject.level,
                focus_labels.get(subject.focus_side, subject.focus_side),
                "、".join(result.team_names) if result.team_names else "未加入团队",
                result.last_session_at[:16] if result.last_session_at else "暂无",
                subject.card_uid or "未绑卡",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, result)
                self._table.setItem(row, column, item)
            if subject.id == selected_id:
                selected_row = row

        if selected_row >= 0:
            self._table.selectRow(selected_row)
        elif self._results:
            self._table.selectRow(0)
        self._sync_actions()
        self._sync_rfid_status()

    def _poll_rfid(self) -> None:
        if self._rfid_reader is None:
            return
        result = self._rfid_reader.request_uid()
        uid = result.uid
        if uid == self._rfid_uid and result.status == self._rfid_read_status:
            return
        self._rfid_uid = uid
        self._rfid_read_status = result.status
        self._rfid_error = (
            f"读卡异常（{result.status}）：{result.message}"
            if uid is None and result.status != STATUS_NO_CARD else None
        )
        self._sync_rfid_status()
        if uid is None or self._subject_store is None:
            return
        subject = self._subject_store.get_subject_by_card_uid(uid)
        if subject is None:
            return
        if not self._select_subject_id(subject.id):
            self._search.clear()
            self._team_filter.setCurrentIndex(0)
            self.refresh()
            self._select_subject_id(subject.id)

    def _select_subject_id(self, subject_id: int) -> bool:
        for row, result in enumerate(self._results):
            if result.subject.id == subject_id:
                self._table.selectRow(row)
                return True
        return False

    def _sync_rfid_status(self) -> None:
        if not hasattr(self, "_rfid_status"):
            return
        if self._rfid_reader is None:
            self._rfid_status.setText(
                f"RFID：{self._rfid_error}"
                if self._rfid_error else "RFID：读卡功能需要 Windows + CH375 驱动"
            )
            self._btn_bind_card.setEnabled(False)
            self._btn_unbind_card.setEnabled(False)
            return
        if self._rfid_error:
            self._rfid_status.setText(f"RFID：{self._rfid_error}")
        elif self._rfid_uid:
            subject = (
                self._subject_store.get_subject_by_card_uid(self._rfid_uid)
                if self._subject_store is not None
                else None
            )
            if subject is None:
                self._rfid_status.setText(f"RFID：已读到 {self._rfid_uid}，未绑定运动员")
            else:
                self._rfid_status.setText(
                    f"RFID：已识别 {subject.display_name}  ({self._rfid_uid})"
                )
        else:
            self._rfid_status.setText("RFID：等待贴卡")
        selected = self._selected_result()
        self._btn_bind_card.setEnabled(self._rfid_uid is not None and selected is not None)
        self._btn_unbind_card.setEnabled(
            selected is not None and bool(selected.subject.card_uid)
        )

    def _bind_current_card(self) -> None:
        selected = self._selected_result()
        if selected is None or not self._rfid_uid or self._subject_store is None:
            return
        try:
            self._subject_store.bind_card_uid(selected.subject.id, self._rfid_uid)
        except ValueError as exc:
            QMessageBox.warning(self, "RFID", str(exc))
            return
        self.refresh()

    def _unbind_selected_card(self) -> None:
        selected = self._selected_result()
        if selected is None or self._subject_store is None:
            return
        self._subject_store.unbind_card_uid(selected.subject.id)
        self.refresh()

    def _populate_team_filter(self) -> None:
        if self._subject_store is None:
            return
        selected = self._team_filter.currentData()
        with QSignalBlocker(self._team_filter):
            self._team_filter.clear()
            self._team_filter.addItem("全部团队", self.ALL_TEAMS)
            self._team_filter.addItem("未加入团队", self.WITHOUT_TEAM)
            for team in self._subject_store.search_teams():
                self._team_filter.addItem(team.name, team.id)
            index = self._team_filter.findData(selected)
            self._team_filter.setCurrentIndex(index if index >= 0 else 0)

    def _selected_result(self) -> SubjectSearchResult | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return value if isinstance(value, SubjectSearchResult) else None

    def _sync_actions(self) -> None:
        enabled = self._selected_result() is not None
        self._btn_edit.setEnabled(enabled)
        self._btn_archive.setEnabled(enabled)
        self._btn_results.setEnabled(enabled)
        self._btn_test.setEnabled(enabled)
        self._btn_team_results.setEnabled(
            isinstance(self._team_filter.currentData(), int)
        )
        self._sync_rfid_status()

    def _create_subject(self) -> None:
        if self._subject_store is None:
            return
        values = _SubjectDialog.get_values(self, store=self._subject_store)
        if values is None:
            return
        self._create_subject_from_values(values)

    def _create_subject_from_values(self, values: dict) -> None:
        if self._subject_store is None:
            return
        subject_values = dict(values)
        team_ids = subject_values.pop("team_ids", [])
        team_id = team_ids[0] if team_ids else None
        try:
            matches = self._subject_store.find_duplicate_subjects(
                subject_values["display_name"], subject_values["birth_year"]
            )
            if matches:
                action, candidate = self._ask_duplicate_action(matches)
                if action == "cancel":
                    return
                if action == "reuse" and candidate is not None:
                    self._subject_store.restore_subject_and_add_to_team(
                        candidate.subject.id, team_id
                    )
                    self._search.clear()
                    self.refresh()
                    return
            self._subject_store.create_subject(**subject_values, team_id=team_id)
        except Exception as exc:
            QMessageBox.warning(self, "新建运动员", f"保存失败：{exc}")
            return
        self._search.clear()
        self.refresh()

    def _ask_duplicate_action(
        self, matches: list[SubjectSearchResult]
    ) -> tuple[str, SubjectSearchResult | None]:
        dialog = _DuplicateSubjectDialog(matches, self)
        if dialog.exec_() != QDialog.Accepted:
            return "cancel", None
        return dialog.action, dialog.selected_result()

    def _edit_selected(self) -> None:
        if self._subject_store is None:
            return
        result = self._selected_result()
        if result is None:
            return
        values = _SubjectDialog.get_values(
            self, result.subject, store=self._subject_store
        )
        if values is None:
            return
        try:
            team_ids = values.pop("team_ids", [])
            self._subject_store.update_subject_and_sync_teams(
                result.subject.id, team_ids=team_ids, **values
            )
        except Exception as exc:
            QMessageBox.warning(self, "编辑运动员", f"保存失败：{exc}")
            return
        self.refresh()

    def _archive_selected(self) -> None:
        if self._subject_store is None:
            return
        result = self._selected_result()
        if result is None:
            return
        answer = QMessageBox.question(
            self,
            "归档运动员",
            f"归档“{result.subject.display_name}”？历史测试不会删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._subject_store.archive_subject(result.subject.id)
        self.refresh()

    def _start_selected_test(self) -> None:
        result = self._selected_result()
        if result is not None:
            self.test_requested.emit(result)

    def _show_selected_results(self) -> None:
        result = self._selected_result()
        if result is not None:
            self.results_requested.emit(result)

    def _show_filtered_team_results(self) -> None:
        if self._subject_store is None:
            return
        team_id = self._team_filter.currentData()
        if not isinstance(team_id, int):
            return
        team = next(
            (item for item in self._subject_store.search_teams() if item.id == team_id),
            None,
        )
        if isinstance(team, TeamProfile):
            self.team_results_requested.emit(team)


class _SubjectDialog(QDialog):
    NEW_TEAM = "new-team"

    def __init__(
        self,
        store: SubjectStore | None = None,
        subject: SubjectProfile | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._store = store
        self._subject = subject
        self.setWindowTitle("编辑运动员" if subject else "新建运动员")
        form = QFormLayout(self)

        self.name = QLineEdit(subject.display_name if subject else "")
        self.birth_year = QSpinBox()
        self.birth_year.setRange(1900, datetime.now().year)
        self.birth_year.setValue(subject.birth_year if subject else 1990)
        self.height = QDoubleSpinBox()
        self.height.setRange(0, 250)
        self.height.setSuffix(" cm")
        self.height.setValue(float(subject.height_cm or 0.0) if subject else 0.0)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, 300)
        self.weight.setSuffix(" kg")
        self.weight.setValue(float(subject.weight_kg or 0.0) if subject else 0.0)
        self.level = QComboBox()
        self.level.addItems(["beginner", "intermediate", "advanced"])
        self.level.setCurrentText(subject.level if subject else "intermediate")
        self.focus = QComboBox()
        self.focus.addItem("均衡", "")
        self.focus.addItem("左侧", "left")
        self.focus.addItem("右侧", "right")
        self.focus.addItem("双侧", "both")
        if subject:
            self.focus.setCurrentIndex(max(self.focus.findData(subject.focus_side), 0))

        form.addRow("姓名", self.name)
        form.addRow("出生年份", self.birth_year)
        form.addRow("身高", self.height)
        form.addRow("体重", self.weight)
        form.addRow("训练水平", self.level)
        form.addRow("训练侧重", self.focus)

        self._initial_team: QComboBox | None = None
        self._team_list: QListWidget | None = None
        if subject is None:
            self._initial_team = QComboBox()
            self._initial_team.addItem("暂不加入团队", None)
            if store is not None:
                for team in store.search_teams():
                    self._initial_team.addItem(team.name, team.id)
            self._initial_team.addItem("新建团队…", self.NEW_TEAM)
            self._initial_team.activated.connect(self._handle_initial_team_choice)
            form.addRow("所属团队", self._initial_team)
        else:
            self._team_list = QListWidget()
            active_team_ids = (
                {team.id for team in store.get_subject_teams(subject.id)}
                if store is not None
                else set()
            )
            if store is not None:
                for team in store.search_teams():
                    item = QListWidgetItem(team.name)
                    item.setData(Qt.UserRole, team.id)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(
                        Qt.Checked if team.id in active_team_ids else Qt.Unchecked
                    )
                    self._team_list.addItem(item)
            form.addRow("所属团队", self._team_list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept_if_valid(self) -> None:
        if not self.name.text().strip():
            QMessageBox.information(self, self.windowTitle(), "姓名不能为空。")
            return
        self.accept()

    def values(self) -> dict:
        values = {
            "display_name": self.name.text().strip(),
            "birth_year": self.birth_year.value(),
            "height_cm": self.height.value() or None,
            "weight_kg": self.weight.value() or None,
            "level": self.level.currentText(),
            "focus_side": self.focus.currentData() or "",
        }
        if self._initial_team is not None:
            team_id = self._initial_team.currentData()
            values["team_ids"] = [team_id] if isinstance(team_id, int) else []
        elif self._team_list is not None:
            values["team_ids"] = [
                self._team_list.item(index).data(Qt.UserRole)
                for index in range(self._team_list.count())
                if self._team_list.item(index).checkState() == Qt.Checked
            ]
        else:
            values["team_ids"] = []
        return values

    def _handle_initial_team_choice(self) -> None:
        if self._initial_team is None or self._initial_team.currentData() != self.NEW_TEAM:
            return
        if self._store is None:
            self._initial_team.setCurrentIndex(0)
            return
        name, accepted = QInputDialog.getText(self, "新建团队", "团队名称")
        if not accepted:
            self._initial_team.setCurrentIndex(0)
            return
        try:
            team_id = self._store.create_team(name)
        except Exception as exc:
            QMessageBox.warning(self, "新建团队", f"保存失败：{exc}")
            self._initial_team.setCurrentIndex(0)
            return
        team = next(
            (item for item in self._store.search_teams() if item.id == team_id), None
        )
        if team is None:
            self._initial_team.setCurrentIndex(0)
            return
        insert_index = self._initial_team.count() - 1
        self._initial_team.insertItem(insert_index, team.name, team.id)
        self._initial_team.setCurrentIndex(insert_index)

    @classmethod
    def get_values(
        cls,
        parent: QWidget,
        subject: SubjectProfile | None = None,
        *,
        store: SubjectStore | None = None,
    ) -> dict | None:
        dialog = cls(store=store, subject=subject, parent=parent)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return dialog.values()


class _DuplicateSubjectDialog(QDialog):
    def __init__(self, matches: list[SubjectSearchResult], parent=None):
        super().__init__(parent)
        self.setWindowTitle("发现相同姓名和出生年份的运动员")
        self.action = "cancel"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请选择已有档案，或确认仍然新建。"))
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["姓名", "出生年份", "所属团队", "创建时间", "最近测试"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, result in enumerate(matches):
            self._table.insertRow(row)
            values = [
                result.subject.display_name,
                str(result.subject.birth_year),
                "、".join(result.team_names) if result.team_names else "未加入团队",
                result.subject.created_at[:16],
                result.last_session_at[:16] if result.last_session_at else "暂无",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, result)
                self._table.setItem(row, column, item)
        if matches:
            self._table.selectRow(0)
        layout.addWidget(self._table)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        reuse = buttons.addButton("使用已有档案", QDialogButtonBox.AcceptRole)
        create = buttons.addButton("仍然新建", QDialogButtonBox.ActionRole)
        reuse.clicked.connect(self._reuse)
        create.clicked.connect(self._create)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reuse(self) -> None:
        if self.selected_result() is None:
            return
        self.action = "reuse"
        self.accept()

    def _create(self) -> None:
        self.action = "create"
        self.accept()

    def selected_result(self) -> SubjectSearchResult | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        value = item.data(Qt.UserRole) if item is not None else None
        return value if isinstance(value, SubjectSearchResult) else None


def _measurement_text(subject: SubjectProfile) -> str:
    height = f"{subject.height_cm:g} cm" if subject.height_cm else "身高未填"
    weight = f"{subject.weight_kg:g} kg" if subject.weight_kg else "体重未填"
    return f"{height} / {weight}"
