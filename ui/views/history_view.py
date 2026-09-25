"""
history_view.py — 受试者历史记录页

显示当前受试者的历史测试列表和摘要，并允许加载某次测试参数。
"""

from __future__ import annotations

import logging
from html import escape
from typing import Any

from qtpy.QtCore import QSignalBlocker, Signal, Qt
from qtpy.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHeaderView, QHBoxLayout, QLabel,
    QInputDialog, QMessageBox, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton

from data.subject_store import (
    SessionRecord,
    SubjectSearchResult,
    SubjectStore,
    TeamProfile,
)


log = logging.getLogger(__name__)

HISTORY_QSS = """
QWidget#HistoryViewRoot {
    background: #0c1119;
    color: #e7ebf2;
    font-size: 14px;
}
QLabel#HistoryTitle {
    color: #f5f7fb;
    font-size: 22px;
    font-weight: 700;
}
QLabel#HistoryContext {
    color: #aeb7c5;
    font-size: 13px;
}
QLabel#DetailTitle {
    color: #f2f5fa;
    font-size: 18px;
    font-weight: 700;
}
QFrame#HistoryDetailCard {
    background: #121923;
    border: 1px solid #293442;
    border-radius: 8px;
}
QLabel#HistoryDetailText {
    color: #dfe5ee;
    font-size: 14px;
    background: transparent;
}
QComboBox#HistoryFilter {
    min-width: 150px;
    min-height: 34px;
    padding: 0 10px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #e7ebf2;
}
QTableWidget {
    background: #121923;
    alternate-background-color: #151d28;
    color: #dfe5ee;
    border: 1px solid #293442;
    border-radius: 8px;
    gridline-color: #26313f;
    selection-background-color: #273446;
    selection-color: white;
    font-size: 14px;
}
QTableWidget::item {
    padding: 8px 10px;
}
QTableWidget::item:selected {
    background: #26364a;
    color: white;
}
QHeaderView::section {
    background: #171f2b;
    color: #9da8b8;
    border: none;
    border-bottom: 1px solid #2b3543;
    padding: 8px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton {
    min-height: 34px;
    border: 1px solid #354151;
    border-radius: 6px;
    background: #1a2230;
    color: #d9dee8;
    padding: 0 14px;
}
QPushButton:hover {
    background: #232d3c;
}
QPushButton:disabled {
    color: #677386;
    background: #151c26;
}
QPushButton#PrimaryHistoryAction {
    background: #ff7a00;
    border-color: #ff7a00;
    color: white;
    font-weight: 650;
}
"""


class HistoryView(QWidget):
    """只读历史记录视图。"""

    return_setup = Signal()
    load_config_requested = Signal(object)
    open_report_requested = Signal(object)

    def __init__(self, subject_store: SubjectStore | None = None, parent=None):
        super().__init__(parent)
        self._subject_store = subject_store
        self._subject_result: SubjectSearchResult | None = None
        self._team: TeamProfile | None = None
        self._sessions: list[SessionRecord] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("HistoryViewRoot")
        self.setStyleSheet(HISTORY_QSS)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 18, 24, 20)
        main_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        title = MLabel("历史记录")
        title.setObjectName("HistoryTitle")
        self._subject_label = MLabel("未选择受试者")
        self._subject_label.setObjectName("HistoryContext")

        self._btn_return = MPushButton("返回测试")
        self._btn_return.clicked.connect(self.return_setup)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(3)
        title_layout.addWidget(title)
        title_layout.addWidget(self._subject_label)
        header_layout.addLayout(title_layout)
        header_layout.addStretch(1)
        header_layout.addWidget(self._btn_return)
        main_layout.addLayout(header_layout)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)
        filter_layout.addStretch(1)
        filter_layout.addWidget(QLabel("运动员"))
        self._athlete_filter = QComboBox()
        self._athlete_filter.setObjectName("HistoryFilter")
        self._athlete_filter.currentIndexChanged.connect(self._populate_sessions)
        filter_layout.addWidget(self._athlete_filter)
        filter_layout.addWidget(QLabel("测试类型"))
        self._test_type_filter = QComboBox()
        self._test_type_filter.setObjectName("HistoryFilter")
        self._test_type_filter.currentIndexChanged.connect(self._populate_sessions)
        filter_layout.addWidget(self._test_type_filter)
        main_layout.addLayout(filter_layout)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        self._session_table = QTableWidget(0, 5)
        self._session_table.setHorizontalHeaderLabels(
            ["运动员", "测试身份", "时间", "测试类型", "结束原因"]
        )
        self._session_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._session_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._session_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._session_table.verticalHeader().setVisible(False)
        self._session_table.verticalHeader().setDefaultSectionSize(48)
        self._session_table.horizontalHeader().setStretchLastSection(True)
        self._session_table.horizontalHeader().setMinimumHeight(42)
        self._session_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self._session_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self._session_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self._session_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self._session_table.itemSelectionChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self._session_table, 5)

        detail_frame = QFrame()
        detail_frame.setObjectName("HistoryDetailCard")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(12)
        detail_title = QLabel("记录摘要")
        detail_title.setObjectName("DetailTitle")
        detail_layout.addWidget(detail_title)

        self._detail_label = QLabel("请选择一条历史记录。")
        self._detail_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._detail_label.setWordWrap(True)
        self._detail_label.setObjectName("HistoryDetailText")
        self._detail_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        detail_layout.addWidget(self._detail_label, 1)

        content_layout.addWidget(detail_frame, 4)
        main_layout.addLayout(content_layout, 1)

        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self._btn_link_subject = MPushButton("关联运动员")
        self._btn_link_subject.setMinimumHeight(42)
        self._btn_link_subject.clicked.connect(self._on_link_subject_clicked)
        footer_layout.addWidget(self._btn_link_subject)

        self._btn_load_config = MPushButton("加载该次参数").primary()
        self._btn_load_config.setMinimumHeight(42)
        self._btn_load_config.setMinimumWidth(160)
        self._btn_load_config.clicked.connect(self._on_load_config_clicked)
        footer_layout.addWidget(self._btn_load_config)

        self._btn_open_report = MPushButton("打开报告").primary()
        self._btn_open_report.setObjectName("PrimaryHistoryAction")
        self._btn_open_report.setMinimumHeight(42)
        self._btn_open_report.setMinimumWidth(140)
        self._btn_open_report.clicked.connect(self._on_open_report_clicked)
        footer_layout.addWidget(self._btn_open_report)
        main_layout.addLayout(footer_layout)

        self._set_empty_state("请从配置页选择受试者后查看历史记录。")

    def load_all(self) -> None:
        self._subject_result = None
        self._team = None
        self._subject_label.setText("全部本地测试")
        if self._subject_store is None:
            self._set_empty_state("历史数据存储不可用。")
            return
        try:
            self._sessions = self._subject_store.get_all_sessions()
        except Exception as exc:
            log.exception("Failed to load all sessions")
            self._set_empty_state("读取结果失败。")
            QMessageBox.warning(self, "结果", f"读取失败：{exc}")
            return
        self._refresh_filters()
        self._populate_sessions()

    def load_subject(self, result: SubjectSearchResult | None) -> None:
        self._subject_result = result
        self._team = None
        if result is None:
            self._subject_label.setText("未选择受试者")
            self._set_empty_state("请先选择受试者。")
            return
        if self._subject_store is None:
            self._subject_label.setText(f"受试者: {result.subject.display_name}")
            self._set_empty_state("历史数据存储不可用。")
            return

        self._subject_label.setText(f"受试者: {result.subject.display_name}")
        try:
            self._sessions = self._subject_store.get_sessions(result.subject.id)
        except Exception as exc:
            log.exception("Failed to load subject sessions")
            self._set_empty_state("读取历史记录失败。")
            QMessageBox.warning(self, "历史记录", f"读取失败：{exc}")
            return

        self._refresh_filters()
        self._populate_sessions()

    def load_team(self, team: TeamProfile) -> None:
        self._subject_result = None
        self._team = team
        self._subject_label.setText(f"团队: {team.name}")
        if self._subject_store is None:
            self._set_empty_state("历史数据存储不可用。")
            return
        try:
            self._sessions = self._subject_store.get_team_sessions(team.id)
        except Exception as exc:
            log.exception("Failed to load team sessions")
            self._set_empty_state("读取团队历史失败。")
            QMessageBox.warning(self, "团队历史", f"读取失败：{exc}")
            return
        self._refresh_filters()
        self._populate_sessions()

    def _populate_sessions(self) -> None:
        sessions = self._filtered_sessions()
        self._session_table.blockSignals(True)
        self._session_table.setRowCount(0)
        for row, session in enumerate(sessions):
            self._session_table.insertRow(row)
            values = [
                self._session_subject_name(session),
                self._session_identity_name(session),
                session.started_at[:16],
                session.test_type,
                _finish_reason_label(session.finish_reason),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, session)
                self._session_table.setItem(row, column, item)
        self._session_table.blockSignals(False)

        if sessions:
            self._session_table.selectRow(0)
            self._show_session_detail(sessions[0])
            self._btn_load_config.setEnabled(True)
            self._btn_open_report.setEnabled(bool(sessions[0].report_detail))
            self._btn_link_subject.setEnabled(sessions[0].subject_id is None)
        elif self._sessions:
            self._detail_label.setText("没有符合筛选条件的测试记录。")
            self._btn_load_config.setEnabled(False)
            self._btn_open_report.setEnabled(False)
            self._btn_link_subject.setEnabled(False)
        else:
            message = (
                "该团队暂无历史测试。"
                if self._team is not None
                else (
                    "暂无本地测试结果。"
                    if self._subject_result is None
                    else "该受试者暂无历史测试。"
                )
            )
            self._set_empty_state(message)

    def _refresh_filters(self) -> None:
        with QSignalBlocker(self._athlete_filter), QSignalBlocker(
            self._test_type_filter
        ):
            self._athlete_filter.clear()
            self._athlete_filter.addItem("全部运动员", None)
            athlete_names = {
                self._session_subject_name(item) for item in self._sessions
            }
            for name in sorted(athlete_names):
                self._athlete_filter.addItem(name, name)

            self._test_type_filter.clear()
            self._test_type_filter.addItem("全部测试类型", None)
            for test_type in sorted({item.test_type for item in self._sessions}):
                self._test_type_filter.addItem(test_type, test_type)

    def _filtered_sessions(self) -> list[SessionRecord]:
        athlete = self._athlete_filter.currentData()
        test_type = self._test_type_filter.currentData()
        return [
            session
            for session in self._sessions
            if (athlete is None or self._session_subject_name(session) == athlete)
            and (test_type is None or session.test_type == test_type)
        ]

    def _set_empty_state(self, message: str) -> None:
        self._sessions = []
        self._refresh_filters()
        self._session_table.setRowCount(0)
        self._detail_label.setText(message)
        self._btn_load_config.setEnabled(False)
        self._btn_open_report.setEnabled(False)
        self._btn_link_subject.setEnabled(False)

    def _on_selection_changed(self) -> None:
        session = self._selected_session()
        if session is None:
            self._detail_label.setText("请选择一条历史记录。")
            self._btn_load_config.setEnabled(False)
            self._btn_open_report.setEnabled(False)
            self._btn_link_subject.setEnabled(False)
            return
        self._show_session_detail(session)
        self._btn_load_config.setEnabled(True)
        self._btn_open_report.setEnabled(bool(session.report_detail))
        self._btn_link_subject.setEnabled(session.subject_id is None)

    def _selected_session(self) -> SessionRecord | None:
        row = self._session_table.currentRow()
        if row < 0:
            return None
        item = self._session_table.item(row, 0)
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return data if isinstance(data, SessionRecord) else None

    def _show_session_detail(self, session: SessionRecord) -> None:
        config = session.config
        summary = session.report_summary
        info_lines = [
            f"运动员: {self._session_subject_name(session)}",
            f"测试身份: {self._session_identity_name(session)}",
            f"测试时间: {session.started_at[:16]}",
            f"测试类型: {session.test_type}",
            f"结束原因: {_finish_reason_label(session.finish_reason)}",
        ]
        config_lines = _config_detail_lines(config)
        result_lines = [_session_summary(session)]
        if session.total_jumps is not None:
            result_lines.append(f"总跳跃: {session.total_jumps} 次")
        if summary.get("touch_count") is not None:
            result_lines.append(f"触地次数: {summary['touch_count']}")
        if summary.get("lift_count") is not None:
            result_lines.append(f"腾空次数: {summary['lift_count']}")
        if summary.get("std_jump_height") is not None:
            result_lines.append(f"跳高标准差: {summary['std_jump_height']:.3f} m")
        if summary.get("min_air_time") is not None and summary.get("max_air_time") is not None:
            result_lines.append(
                f"腾空范围: {summary['min_air_time']:.3f} - {summary['max_air_time']:.3f} s"
            )
        if (
            summary.get("min_contact_time") is not None
            and summary.get("max_contact_time") is not None
        ):
            result_lines.append(
                f"触地范围: {summary['min_contact_time']:.3f} - "
                f"{summary['max_contact_time']:.3f} s"
            )
        self._detail_label.setText(
            _detail_section_html("测试信息", info_lines)
            + _detail_section_html("参数摘要", config_lines)
            + _detail_section_html("结果摘要", result_lines)
        )

    def _on_load_config_clicked(self) -> None:
        session = self._selected_session()
        if session is None:
            QMessageBox.information(self, "加载该次参数", "请先选择一条历史记录。")
            return
        self.load_config_requested.emit(session.config)

    def _on_open_report_clicked(self) -> None:
        session = self._selected_session()
        if session is None:
            QMessageBox.information(self, "打开报告", "请先选择一条历史记录。")
            return
        try:
            session.report
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "打开报告", f"该记录无法重建报告：{exc}")
            return
        self.open_report_requested.emit(session)

    def _on_link_subject_clicked(self) -> None:
        session = self._selected_session()
        if session is None or session.subject_id is not None:
            return
        if self._subject_store is None:
            QMessageBox.warning(self, "关联运动员", "本地运动员数据不可用。")
            return
        results = self._subject_store.search_subjects()
        if not results:
            QMessageBox.information(
                self, "关联运动员", "请先在“运动员”模块创建运动员。"
            )
            return
        labels = [
            (
                f"{result.subject.display_name} · {result.subject.birth_year} · "
                f"{'、'.join(result.team_names) if result.team_names else '未加入团队'}"
                f" · 候选 {index + 1}"
            )
            for index, result in enumerate(results)
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            "关联运动员",
            "选择运动员：",
            labels,
            0,
            False,
        )
        if not accepted:
            return
        try:
            match = results[labels.index(selected)]
        except ValueError:
            name_matches = [
                result
                for result in results
                if result.subject.display_name == selected
            ]
            if len(name_matches) != 1:
                return
            match = name_matches[0]
        try:
            self._subject_store.link_session_to_subject(
                session.id, match.subject.id
            )
        except Exception as exc:
            log.exception("Failed to link session to subject")
            QMessageBox.warning(self, "关联运动员", f"关联失败：{exc}")
            return
        if self._subject_result is None:
            self.load_all()
        else:
            self.load_subject(self._subject_result)

    def _session_subject_name(self, session: SessionRecord) -> str:
        if self._subject_store is not None and session.subject_id is not None:
            subject = self._subject_store.get_subject(session.subject_id)
            if subject is not None:
                return subject.display_name
        return session.subject_snapshot.get("display_name") or "临时测试"

    @staticmethod
    def _session_identity_name(session: SessionRecord) -> str:
        if session.team_id is not None:
            return session.team_snapshot.get("name") or "团队测试"
        return "个人"


def _finish_reason_label(reason: str | None) -> str:
    labels = {
        "jump_count_reached": "跳跃次数已达标",
        "time_up": "测试时间到",
        "manual": "手动结束",
        "error": "异常结束",
    }
    if not reason:
        return "-"
    from reporting.overground_running import FINISH_LABELS
    return labels.get(reason, FINISH_LABELS.get(reason, reason))


def _detail_section_html(title: str, lines: list[str]) -> str:
    rows = "".join(
        f"<div style='margin-bottom:5px;'>{escape(line)}</div>" for line in lines
    )
    return (
        "<div style='margin-bottom:16px;'>"
        f"<div style='color:#ff9a3d;font-weight:700;margin-bottom:8px;'>{escape(title)}</div>"
        f"{rows}</div>"
    )


def _config_detail_lines(config: Any) -> list[str]:
    lines: list[str] = []
    if hasattr(config, "start_type"):
        lines.append(f"启动: {config.start_type} / {config.start_position}")

    stop_detail = getattr(config, "finish_position", None) or "-"
    lines.append(f"停止: {config.stop_type} / {stop_detail}")

    number_of_jumps = getattr(config, "number_of_jumps", None)
    if number_of_jumps is not None:
        lines.append(f"目标跳跃: {number_of_jumps or '-'} 次")

    if getattr(config, "test_length", None):
        lines.append(f"测试时长: {config.test_length}")
    if hasattr(config, "treadmill_speed"):
        lines.append(f"跑步机速度: {config.treadmill_speed:g} km/h")
    if hasattr(config, "direction"):
        lines.append(f"行进方向: {config.direction}")

    lines.append(
        f"接触/腾空阈值: >{config.min_contact_time}ms / >{config.min_flight_time}ms"
    )

    max_flight_time = getattr(config, "max_flight_time", None)
    if max_flight_time:
        lines.append(f"最大腾空过滤: <{max_flight_time}ms")
    min_foot_length = getattr(config, "min_foot_length", None)
    if min_foot_length is not None:
        lines.append(f"最小足长: {min_foot_length:g} cm")
    automatic_data_filter = getattr(config, "automatic_data_filter", None)
    if automatic_data_filter:
        lines.append(f"自动数据过滤: {automatic_data_filter}%")
    return lines


def _session_summary(session: SessionRecord) -> str:
    summary: dict[str, Any] = session.report_summary
    report_type = summary.get("report_type")
    if report_type == "jump":
        max_height = summary.get("max_jump_height")
        avg_height = summary.get("avg_jump_height")
        if max_height is not None and avg_height is not None:
            return f"最大跳高 {max_height:.3f}m / 平均 {avg_height:.3f}m"
        if session.total_jumps is not None:
            return f"跳跃 {session.total_jumps} 次"
    if report_type == "overground_running":
        speed = summary.get("running_speed_m_s")
        return f"地面跑步 {summary.get('valid_steps', 0)} 步 / " + (f"{speed:.3f} m/s" if speed is not None else "速度数据不足")
    if report_type == "gait":
        avg_stride = summary.get("avg_stride")
        avg_velocity = summary.get("avg_velocity")
        if avg_stride is not None and avg_velocity is not None:
            return f"平均步长 {avg_stride:.3f}m / 平均步速 {avg_velocity:.3f}m/s"
    if session.total_jumps is not None:
        return f"跳跃 {session.total_jumps} 次"
    return "-"
