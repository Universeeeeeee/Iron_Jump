"""
report_view.py — 测试报告页

接收 TestReport (不可变 dataclass) 展示统计汇总和图表回顾。
不依赖 GaitEngine，所有数据来自 TestReport。

功能:
  - MetricCard 网格展示核心统计指标
  - pyqtgraph 图表展示全量历史数据（非滑动窗口）
  - Excel 导出按钮
  - 返回首页按钮
"""

from __future__ import annotations

import importlib
import html
import math
import os
import time
from typing import Optional
from urllib.parse import urlparse

from openpyxl import Workbook

from qtpy.QtCore import QThread, Signal, Qt
from qtpy.QtGui import QColor, QPainter
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFrame, QSizePolicy, QMessageBox, QFileDialog,
    QComboBox, QTabWidget, QTableWidget, QToolButton, QTextBrowser, QLineEdit,
)

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets import dayu_theme

from config.test_report import TestReport, JumpTestReport, GaitTestReport
from config.overground_running_report import OvergroundRunningReport
from config.treadmill_report import (
    TreadmillGaitReport,
    TreadmillRunningReport,
    GaitCycleRecord,
    TreadmillStepResult,
)
from path_utils import get_base_dir as _get_base_dir
from ui.footprint_channel import FootprintReplayPanel

# pyqtgraph 可选
try:
    _pg_spec = importlib.util.find_spec("pyqtgraph")
    if _pg_spec is not None:
        pg = importlib.import_module("pyqtgraph")
        _PG_AVAILABLE = True
    else:
        pg = None
        _PG_AVAILABLE = False
except Exception:
    pg = None
    _PG_AVAILABLE = False

G = 9.81

REPORT_QSS = """
QWidget#ReportViewRoot {
    background-color: #0c1119;
    color: #e7ebf2;
}
QFrame#ReportAnalysisPanel {
    background-color: #151d28;
    border: 1px solid #354151;
    border-radius: 8px;
}
QTabWidget#ReportTabs,
QWidget#ReportOverviewPage {
    background-color: #0c1119;
}
QTabWidget#ReportTabs::pane {
    border: 1px solid #354151;
    border-radius: 6px;
    background-color: #0c1119;
}
QTabBar#ReportTabBar {
    background-color: #0c1119;
}
QTabBar#ReportTabBar::tab {
    min-width: 96px;
    min-height: 30px;
    padding: 4px 16px;
    border: 1px solid #354151;
    border-bottom: none;
    background-color: #171f2b;
    color: #aeb7c5;
}
QTabBar#ReportTabBar::tab:selected {
    background-color: #222d3c;
    color: #ff8a1f;
    font-weight: 650;
}
QTabBar#ReportTabBar::tab:hover {
    background-color: #1d2735;
    color: #f4f6f9;
}
QLabel#ReportSectionTitle {
    color: #8795a8;
    background: transparent;
    border: none;
    border-bottom: 1px solid #354151;
    padding: 0 0 8px 0;
    font-size: 10pt;
}
QWidget#StatsContent {
    background: transparent;
    border: none;
}
QWidget#ReportDetailsPage,
QWidget#ReportDetailPage,
QTabWidget#ReportDetailTabs {
    background-color: #0f1620;
    border: none;
}
QTabWidget#ReportDetailTabs::pane {
    border: 1px solid #2b394a;
    border-radius: 7px;
    background-color: #0f1620;
}
QTabBar#ReportDetailTabBar {
    background-color: #0f1620;
}
QTabWidget#ReportDetailTabs QTabBar::tab {
    min-width: 110px;
    min-height: 30px;
    padding: 4px 14px;
    border: 1px solid #354151;
    background-color: #171f2b;
    color: #aeb7c5;
}
QTabWidget#ReportDetailTabs QTabBar::tab:selected {
    background-color: #222d3c;
    color: #ff8a1f;
    font-weight: 650;
}
QComboBox#ReportFilterCombo,
QToolButton#ReportMoreStatsButton {
    min-height: 30px;
    padding: 2px 10px;
    border: 1px solid #354151;
    border-radius: 6px;
    background-color: #171f2b;
    color: #dce5f0;
}
QComboBox#ReportFilterCombo:hover,
QToolButton#ReportMoreStatsButton:hover,
QToolButton#ReportMoreStatsButton:checked {
    border-color: #ff7a00;
    color: #ff9a3d;
}
QComboBox#ReportFilterCombo QAbstractItemView {
    border: 1px solid #354151;
    background-color: #171f2b;
    color: #dce5f0;
    selection-background-color: #263d55;
}
QLabel#ReportFilterLabel {
    color: #aeb7c5;
    font-size: 10pt;
}
QTableWidget#ReportDetailTable {
    background-color: #111a25;
    alternate-background-color: #162130;
    color: #dce5f0;
    border: 1px solid #2b394a;
    border-radius: 7px;
    gridline-color: #2a3747;
    selection-background-color: #263d55;
    selection-color: #ffffff;
    font-size: 10pt;
}
QTableWidget#ReportDetailTable::item {
    padding: 6px 8px;
}
QTableWidget#ReportDetailTable::item:selected {
    background-color: #263d55;
    color: #ffffff;
}
QTableWidget#ReportDetailTable QHeaderView {
    background-color: #1b2735;
}
QTableWidget#ReportDetailTable QHeaderView::section {
    background-color: #1b2735;
    color: #c7d1df;
    border: none;
    border-right: 1px solid #2f3d4e;
    border-bottom: 1px solid #344356;
    padding: 7px 8px;
    font-weight: 650;
}
QTableWidget#ReportDetailTable QTableCornerButton::section {
    background-color: #1b2735;
    border: none;
    border-right: 1px solid #2f3d4e;
    border-bottom: 1px solid #344356;
}
QTableWidget#ReportDetailTable QScrollBar:vertical {
    width: 10px;
    margin: 0;
    border: none;
    background-color: #0c131d;
}
QTableWidget#ReportDetailTable QScrollBar:horizontal {
    height: 10px;
    margin: 0;
    border: none;
    background-color: #0c131d;
}
QTableWidget#ReportDetailTable QScrollBar::handle {
    min-width: 36px;
    min-height: 36px;
    border-radius: 5px;
    background-color: #3a485a;
}
QTableWidget#ReportDetailTable QScrollBar::handle:hover {
    background-color: #4b5b6f;
}
QTableWidget#ReportDetailTable QScrollBar::add-line,
QTableWidget#ReportDetailTable QScrollBar::sub-line {
    width: 0;
    height: 0;
    background: transparent;
}
QTableWidget#ReportDetailTable QScrollBar::add-page,
QTableWidget#ReportDetailTable QScrollBar::sub-page {
    background: transparent;
}
QPushButton#ReportSecondaryButton,
QPushButton#ReportPrimaryButton {
    min-height: 45px;
    min-width: 160px;
    border-radius: 8px;
    font-size: 14pt;
}
QPushButton#ReportSecondaryButton {
    background-color: #1a2230;
    border: 1px solid #354151;
    color: #d9dee8;
}
QPushButton#ReportSecondaryButton:hover {
    background-color: #232d3c;
}
QPushButton#ReportPrimaryButton {
    background-color: #ff7a00;
    border: 1px solid #ff7a00;
    color: white;
    font-weight: 700;
}
QPushButton#ReportPrimaryButton:hover {
    background-color: #ff8a1f;
}
"""


def _summary_mean(mapping, key):
    summary = mapping.get(key)
    return summary.mean if summary and summary.mean is not None else None


def _report_duration_s(report):
    if len(report.export_timestamps) >= 2:
        return max(report.export_timestamps) - min(report.export_timestamps)
    events = getattr(report, "raw_gait_events", ())
    if len(events) >= 2:
        times = [event.time_s for event in events]
        return max(times) - min(times)
    return None


def _treadmill_overview_stats(
    report: TreadmillGaitReport | TreadmillRunningReport,
) -> list[tuple[str, str, str]]:
    metric_summaries = report.metric_summaries
    cycle_summaries = report.cycle_metric_summaries
    stats: list[tuple[str, str, str]] = []

    candidates = [
        (
            "平均步长",
            _summary_mean(metric_summaries, "step_length_cm"),
            lambda value: f"{value:.1f} cm",
            "步长：一侧足触地到对侧足随后触地之间的前进距离。",
        ),
        (
            "平均步幅",
            _summary_mean(cycle_summaries, "stride_length_cm"),
            lambda value: f"{value:.1f} cm",
            "步幅（又称跨步长）：同侧足连续两次触地之间的前进距离。",
        ),
        (
            "平均步频",
            _summary_mean(metric_summaries, "cadence_steps_per_min"),
            lambda value: f"{value:.1f} steps/min",
            "纳入统计的逐步数据对应的平均步频。",
        ),
        (
            "平均步态周期",
            _summary_mean(cycle_summaries, "gait_cycle_s"),
            lambda value: f"{value:.3f} s",
            "同侧足连续两次触地之间的平均时间。",
        ),
        (
            "平均触地时间",
            _summary_mean(metric_summaries, "contact_time_s"),
            lambda value: f"{value * 1000:.0f} ms",
            "足部每次与测试区域保持接触的平均时间。",
        ),
    ]
    if isinstance(report, TreadmillRunningReport):
        candidates.append(
            (
                "平均腾空时间",
                _summary_mean(metric_summaries, "flight_time_s"),
                lambda value: f"{value * 1000:.0f} ms",
                "双脚均离开测试区域的平均持续时间。",
            )
        )
    candidates.extend(
        [
            (
                "平均支撑相",
                _summary_mean(cycle_summaries, "stance_phase_percent"),
                lambda value: f"{value:.1f}%",
                "支撑相占完整步态周期的平均比例。",
            ),
            (
                "平均摆动相",
                _summary_mean(cycle_summaries, "swing_phase_percent"),
                lambda value: f"{value:.1f}%",
                "摆动相占完整步态周期的平均比例。",
            ),
        ]
    )
    if isinstance(report, TreadmillGaitReport):
        candidates.append(
            (
                "平均双支撑时间",
                _summary_mean(
                    cycle_summaries, "total_double_support_s"
                ),
                lambda value: f"{value * 1000:.0f} ms",
                "一个完整步态周期内双脚同时支撑的平均总时长。",
            )
        )

    for label, value, formatter, tooltip in candidates:
        if value is not None:
            stats.append((label, formatter(value), tooltip))

    for metric_name, label in (
        ("stride_length_cm", "步幅不对称性"),
        ("gait_cycle_s", "步态周期不对称性"),
    ):
        left = report.cycle_side_summaries.get("left", {}).get(metric_name)
        right = report.cycle_side_summaries.get("right", {}).get(metric_name)
        value = report.cycle_asymmetry_percent.get(metric_name)
        if (
            left is not None
            and right is not None
            and left.count >= 3
            and right.count >= 3
            and value is not None
        ):
            stats.append(
                (
                    label,
                    f"{value:.1f}%",
                    "左右侧均至少三个有效完整周期时计算。",
                )
            )
            break

    total_count = len(report.per_step_results)
    if total_count:
        included_count = sum(
            1
            for row in report.per_step_results
            if row.is_event_valid and row.is_included_in_statistics
        )
        stats.append(
            (
                "有效步数",
                f"{included_count} / {total_count}",
                "纳入统计的逐步结果数 / 检测到的逐步结果总数。",
            )
        )

    speed = report.report_config_snapshot.get("treadmill_speed")
    try:
        speed_value = float(speed)
    except (TypeError, ValueError):
        speed_value = None
    if speed_value is not None and math.isfinite(speed_value):
        stats.append(
            (
                "跑带速度",
                f"{speed_value:g} km/h",
                "本次测试配置的跑步机带速。",
            )
        )

    duration = _report_duration_s(report)
    if duration is not None and math.isfinite(duration) and duration >= 0:
        stats.append(
            (
                "实际测试时长",
                f"{duration:.1f} s",
                "按采样时间戳或原始步态事件的时间跨度计算。",
            )
        )

    if report.resolved_starting_foot in ("left", "right"):
        stats.append(
            (
                "起始脚",
                _side_label(report.resolved_starting_foot),
                "测试中识别或手动指定的起始侧。",
            )
        )
    direction = report.report_config_snapshot.get("direction")
    if direction:
        stats.append(
            (
                "行进方向",
                str(direction),
                "受试者相对测试设备接口的行进方向。",
            )
        )

    return stats[:12]


# ======================================================================
#  StatCard — 报告页统计卡片 (比 ExecutionView 的 MetricCard 更紧凑)
# ======================================================================

class StatCard(QFrame):
    """统计指标卡片: 标签 + 数值，适合网格排列。"""

    def __init__(self, label: str, value: str = "--", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "StatCard {"
            "  background-color: rgba(40, 40, 45, 0.85);"
            "  border: 1px solid rgba(80, 80, 85, 0.5);"
            "  border-radius: 8px;"
            "  padding: 6px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        self._label = MLabel(label)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "font-size: 10pt; color: #888888; border: none; background: transparent;"
        )
        layout.addWidget(self._label)

        self._value = MLabel(value)
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet(
            "font-size: 26pt; font-weight: bold; "
            "color: #f0f0f0; border: none; background: transparent;"
        )
        layout.addWidget(self._value)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(85)

    def set_value(self, text: str):
        self._value.setText(text)
        self._apply_value_style("#f0f0f0")

    def set_color(self, color: str):
        self._apply_value_style(color)

    def _apply_value_style(self, color: str):
        text = self._value.text()
        font_size = 18 if len(text) >= 11 else 26
        self._value.setStyleSheet(
            f"font-size: {font_size}pt; font-weight: bold; "
            f"color: {color}; border: none; background: transparent;"
        )


class CyclePhaseBar(QWidget):
    """Compact horizontal rendering of one completed gait cycle."""

    _COLORS = {
        "负荷反应期": QColor("#8e44ad"),
        "单支撑": QColor("#16a085"),
        "摆动前期": QColor("#c0392b"),
        "支撑相": QColor("#2980b9"),
        "摆动相": QColor("#f39c12"),
    }

    def __init__(self, cycle: GaitCycleRecord, parent=None):
        super().__init__(parent)
        self._cycle = cycle
        self.setMinimumHeight(24)
        self.setStyleSheet("background: transparent;")
        if self._detailed_stance_is_complete():
            tooltip = "负荷反应期、单支撑、摆动前期和摆动相按实际时长绘制"
        else:
            tooltip = "子阶段无法可靠拆分，按支撑相和摆动相绘制"
        self.setToolTip(tooltip)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        total = self._cycle.gait_cycle_s
        if total <= 0:
            return
        segments = self._segments()
        x = 0.0
        for label, duration in segments:
            if duration is None or duration <= 0:
                continue
            width = self.width() * duration / total
            painter.fillRect(int(x), 2, max(int(width), 1), self.height() - 4, self._COLORS[label])
            x += width

    def _segments(self):
        if self._detailed_stance_is_complete():
            return [
                ("负荷反应期", self._cycle.load_response_s),
                ("单支撑", self._cycle.single_support_s),
                ("摆动前期", self._cycle.pre_swing_s),
                ("摆动相", self._cycle.swing_phase_s),
            ]
        return [
            ("支撑相", self._cycle.stance_phase_s),
            ("摆动相", self._cycle.swing_phase_s),
        ]

    def _detailed_stance_is_complete(self) -> bool:
        detailed = (
            self._cycle.load_response_s,
            self._cycle.single_support_s,
            self._cycle.pre_swing_s,
        )
        if (
            self._cycle.stance_phase_s is None
            or any(value is None or value < 0 for value in detailed)
        ):
            return False
        return math.isclose(
            sum(detailed),
            self._cycle.stance_phase_s,
            rel_tol=1e-6,
            abs_tol=1e-9,
        )


class _ReportAnalysisWorker(QThread):
    completed = Signal(int, str, object)
    failed = Signal(int, str, str)

    def __init__(self, client, session_id: int, action: str, parent=None):
        super().__init__(parent)
        self._client = client
        self._session_id = session_id
        self._action = action

    def run(self):
        scope = {
            "current_session": True,
            "longitudinal": False,
            "cohort": False,
        }
        try:
            if self._action == "latest":
                payload = self._client.get_latest_analysis(
                    self._session_id,
                    scope,
                )
            else:
                response = self._client.analyze_report(
                    self._session_id,
                    scope,
                )
                if response.get("error_code"):
                    self.failed.emit(
                        self._session_id,
                        self._action,
                        response["error_code"],
                    )
                    return
                payload = response.get("analysis")
            self.completed.emit(self._session_id, self._action, payload)
        except Exception:
            self.failed.emit(
                self._session_id,
                self._action,
                "analysis_unavailable",
            )


# ======================================================================
#  ReportView
# ======================================================================

class ReportView(QWidget):
    """测试报告视图 — 统计汇总 + 图表回顾 + 导出。"""

    voice_reply = Signal(str)
    return_home = Signal()
    export_requested = Signal()

    def __init__(self, parent=None, *, llm_client=None):
        super().__init__(parent)
        self._report: Optional[TestReport] = None
        self._session_id: int | None = None
        self._llm_client = llm_client
        self._analysis_available = False
        self._latest_requested_for: int | None = None
        self._analysis_workers: set[_ReportAnalysisWorker] = set()
        self._finished_analysis_workers: list[_ReportAnalysisWorker] = []
        self._dynamic_widgets: list[QWidget] = []
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("ReportViewRoot")
        self.setStyleSheet(REPORT_QSS)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 15, 20, 15)
        main_layout.setSpacing(12)

        # ===== 标题 =====
        self._title = MLabel("📊 测试报告")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "font-size: 22pt; font-weight: bold; color: #e0e0e0; padding: 6px 0;"
        )
        main_layout.addWidget(self._title)

        # ===== 结束原因 =====
        self._reason_label = MLabel("")
        self._reason_label.setAlignment(Qt.AlignCenter)
        self._reason_label.setStyleSheet(
            "font-size: 12pt; color: #52c41a; padding: 2px 0;"
        )
        main_layout.addWidget(self._reason_label)

        # ===== 内容区: 概览页 + 明细页 =====
        self._tabs = QTabWidget()
        self._tabs.setObjectName("ReportTabs")
        self._tabs.setDocumentMode(True)
        self._tabs.tabBar().setObjectName("ReportTabBar")

        self._overview_page = QWidget()
        self._overview_page.setObjectName("ReportOverviewPage")
        content_layout = QHBoxLayout(self._overview_page)
        content_layout.setContentsMargins(4, 8, 4, 4)
        content_layout.setSpacing(16)

        # --- 左侧: 统计卡片网格 ---
        left_container = QWidget()
        left_container.setObjectName("StatsContent")
        left_container.setMinimumWidth(480)
        left_container.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._stats_content = left_container
        self._stats_layout = QGridLayout(left_container)
        self._stats_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_layout.setSpacing(8)

        # 三列四行，按模式优先级动态展示至多 12 项。
        self._stat_cards: list[StatCard] = []
        for i in range(12):
            card = StatCard("")
            card.hide()
            row, col = divmod(i, 3)
            self._stats_layout.addWidget(card, row, col)
            self._stat_cards.append(card)

        content_layout.addWidget(left_container, 3)

        # --- 右侧: 图表回顾 ---
        right_container = QWidget()
        right_container.setMinimumWidth(460)
        right_container.setMaximumWidth(780)
        right_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self._right_layout = right_layout

        self._review_title = QLabel("数据回顾")
        self._review_title.setObjectName("ReportSectionTitle")
        right_layout.addWidget(self._review_title)

        self._replay_panel = FootprintReplayPanel()
        self._replay_panel.hide()
        self._replay_panel.setMinimumHeight(520)
        right_layout.addWidget(self._replay_panel, 1)
        right_layout.addWidget(self._replay_panel.ground_track.detail, 1)

        self._plot_container = QWidget()
        self._plot_container_layout = QVBoxLayout(self._plot_container)
        self._plot_container_layout.setContentsMargins(0, 0, 0, 0)
        self._plot_container_layout.setSpacing(8)

        if _PG_AVAILABLE:
            self._plot_1 = pg.PlotWidget()
            self._plot_1.setBackground(dayu_theme.background_in_color)
            self._plot_1.showGrid(x=True, y=True, alpha=0.1)
            self._plot_1.enableAutoRange()
            self._plot_container_layout.addWidget(self._plot_1, 1)

            self._plot_2 = pg.PlotWidget()
            self._plot_2.setBackground(dayu_theme.background_in_color)
            self._plot_2.showGrid(x=True, y=True, alpha=0.1)
            self._plot_2.enableAutoRange()
            self._plot_container_layout.addWidget(self._plot_2, 1)
        else:
            placeholder = QLabel("未安装 pyqtgraph — 图表不可用")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("font-size: 14pt; color: #666;")
            self._plot_container_layout.addWidget(placeholder)

        right_layout.addWidget(self._plot_container, 1)

        content_layout.addWidget(right_container, 2)
        self._tabs.addTab(self._overview_page, "概览")

        self._details_page = QWidget()
        self._details_page.setObjectName("ReportDetailsPage")
        details_layout = QVBoxLayout(self._details_page)
        details_layout.setContentsMargins(8, 8, 8, 8)
        details_layout.setSpacing(8)

        self._detail_tabs = QTabWidget()
        self._detail_tabs.setObjectName("ReportDetailTabs")
        self._detail_tabs.setDocumentMode(True)
        self._detail_tabs.tabBar().setObjectName("ReportDetailTabBar")
        details_layout.addWidget(self._detail_tabs)

        self._summary_page = QWidget()
        self._summary_page.setObjectName("ReportDetailPage")
        self._summary_layout = QVBoxLayout(self._summary_page)
        self._summary_layout.setContentsMargins(6, 8, 6, 6)
        self._summary_layout.setSpacing(8)
        summary_controls = QHBoxLayout()
        summary_controls.addStretch()
        self._more_stats_button = QToolButton()
        self._more_stats_button.setObjectName("ReportMoreStatsButton")
        self._more_stats_button.setText("更多统计")
        self._more_stats_button.setCheckable(True)
        self._more_stats_button.toggled.connect(
            self._toggle_extended_summary_columns
        )
        summary_controls.addWidget(self._more_stats_button)
        self._summary_layout.addLayout(summary_controls)
        self._detail_tabs.addTab(self._summary_page, "统计汇总")

        self._cycle_page = QWidget()
        self._cycle_page.setObjectName("ReportDetailPage")
        self._cycle_layout = QVBoxLayout(self._cycle_page)
        self._cycle_layout.setContentsMargins(6, 8, 6, 6)
        self._cycle_layout.setSpacing(8)
        self._cycle_filter = self._build_detail_filter()
        self._cycle_filter.currentIndexChanged.connect(
            self._rebuild_cycle_detail_table
        )
        self._cycle_layout.addLayout(
            self._filter_row("显示周期", self._cycle_filter)
        )
        self._detail_tabs.addTab(self._cycle_page, "周期明细")

        self._step_page = QWidget()
        self._step_page.setObjectName("ReportDetailPage")
        self._step_layout = QVBoxLayout(self._step_page)
        self._step_layout.setContentsMargins(6, 8, 6, 6)
        self._step_layout.setSpacing(8)
        self._step_filter = self._build_detail_filter()
        self._step_filter.currentIndexChanged.connect(
            self._rebuild_step_detail_table
        )
        self._step_layout.addLayout(
            self._filter_row("显示逐步数据", self._step_filter)
        )
        self._detail_tabs.addTab(self._step_page, "逐步数据")

        self._tabs.addTab(self._details_page, "明细")

        self._gait_question_page = QWidget()
        self._gait_question_page.setStyleSheet(
            "QLineEdit, QTextBrowser { background: #151e2a; color: #e7edf5;"
            "border: 1px solid #354151; border-radius: 5px; padding: 10px; font-size: 14px; }"
            "QPushButton { background: #242e3c; color: #e7edf5; padding: 8px;"
            "border: 1px solid #354151; border-radius: 5px; }"
        )
        question_layout = QVBoxLayout(self._gait_question_page)
        self._gait_question = QLineEdit()
        self._gait_question.setPlaceholderText("询问左右差异、步频稳定性、前后半程变化或排除数据")
        self._gait_question.returnPressed.connect(
            lambda: self.answer_gait_question(self._gait_question.text())
        )
        question_layout.addWidget(self._gait_question)
        suggestions = QHBoxLayout()
        for question in ("左右脚差异怎么样", "步频稳定吗", "前后半程有什么变化", "哪些数据没算进去"):
            button = MPushButton(question)
            button.clicked.connect(lambda checked=False, text=question: self.answer_gait_question(text))
            suggestions.addWidget(button)
        question_layout.addLayout(suggestions)
        self._gait_answer = QTextBrowser()
        self._gait_answer.document().setDefaultStyleSheet("a { color: #ffae55; }")
        self._gait_answer.setOpenLinks(False)
        self._gait_answer.anchorClicked.connect(self._locate_gait_evidence)
        question_layout.addWidget(self._gait_answer)
        self._gait_topic = ""
        self._gait_question_index = self._tabs.addTab(self._gait_question_page, "步态专项问答")

        main_layout.addWidget(self._tabs, 1)

        self._analysis_panel = QFrame()
        self._analysis_panel.setObjectName("ReportAnalysisPanel")
        analysis_layout = QVBoxLayout(self._analysis_panel)
        analysis_layout.setContentsMargins(14, 10, 14, 10)
        analysis_layout.setSpacing(8)
        analysis_header = QHBoxLayout()
        self._analysis_title = QLabel("智能分析")
        self._analysis_title.setObjectName("ReportSectionTitle")
        analysis_header.addWidget(self._analysis_title)
        analysis_header.addStretch()
        self._analysis_button = MPushButton("开始智能分析").primary()
        self._analysis_button.setObjectName("ReportAnalysisButton")
        self._analysis_button.clicked.connect(self._on_analysis_clicked)
        analysis_header.addWidget(self._analysis_button)
        analysis_layout.addLayout(analysis_header)
        self._analysis_status = QLabel("")
        self._analysis_status.setWordWrap(True)
        self._analysis_status.hide()
        analysis_layout.addWidget(self._analysis_status)
        self._analysis_result = QLabel("")
        self._analysis_result.setWordWrap(True)
        self._analysis_result.setTextFormat(Qt.RichText)
        self._analysis_result.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._analysis_result.setOpenExternalLinks(True)
        self._analysis_result.hide()
        analysis_layout.addWidget(self._analysis_result)
        self._analysis_panel.hide()
        main_layout.addWidget(self._analysis_panel)

        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        btn_layout.addStretch()

        self.btn_export = MPushButton("📥 导出 Excel")
        self.btn_export.setObjectName("ReportSecondaryButton")
        self.btn_export.setMinimumHeight(45)
        self.btn_export.setMinimumWidth(160)
        self.btn_export.clicked.connect(self._on_export)
        btn_layout.addWidget(self.btn_export)

        self.btn_home = MPushButton("返回测试").primary()
        self.btn_home.setObjectName("ReportPrimaryButton")
        self.btn_home.setMinimumHeight(45)
        self.btn_home.setMinimumWidth(160)
        self.btn_home.clicked.connect(self.return_home)
        btn_layout.addWidget(self.btn_home)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    #  公共接口
    # ------------------------------------------------------------------

    def load_report(self, report: TestReport, session_id: int | None = None):
        """填充统计卡片和图表。"""
        self._report = report
        self._gait_topic = ""
        self._gait_question.clear()
        self._gait_answer.clear()
        self._tabs.setTabVisible(self._gait_question_index, isinstance(report, TreadmillGaitReport))
        self._session_id = session_id
        self._latest_requested_for = None
        self.clear_analysis()
        self._refresh_analysis_visibility()

        # 结束原因
        reason_map = {
            "jump_count_reached": "测试已完成 · 跳跃次数已达标",
            "time_up": "测试已完成 · 测试时间到",
            "manual": "测试已完成 · 手动结束",
            "unsupported_layout": "测试中断 · 当前模式仅支持单段设备",
        }
        self._reason_label.setText(reason_map.get(report.finish_reason, report.finish_reason))
        self._replay_panel.hide()
        self._plot_container.show()
        self._tabs.setCurrentIndex(0)
        is_walking = (isinstance(report, GaitTestReport) and bool(report.walking_summary)) or isinstance(report, OvergroundRunningReport)
        summary = (getattr(report, "running_summary", None) or getattr(report, "walking_summary", None)) if is_walking else None
        self._replay_panel.set_ground_context(
            report.report_config_snapshot.get("device", {}), summary
        )
        self._tabs.setTabVisible(1, is_walking or isinstance(
            report, (TreadmillGaitReport, TreadmillRunningReport)
        ))
        for i in range(1, self._detail_tabs.count()):
            self._detail_tabs.setTabVisible(i, not is_walking)
        self._detail_tabs.setCurrentIndex(0)
        self._more_stats_button.setChecked(False)
        for detail_filter in (self._cycle_filter, self._step_filter):
            detail_filter.blockSignals(True)
            detail_filter.setCurrentIndex(0)
            detail_filter.blockSignals(False)
        self._clear_dynamic_widgets()

        if isinstance(report, JumpTestReport):
            self._load_jump_report(report)
        elif isinstance(report, OvergroundRunningReport):
            self._load_overground_running(report)
        elif isinstance(report, GaitTestReport):
            self._load_gait_report(report)
        elif isinstance(report, (TreadmillGaitReport, TreadmillRunningReport)):
            self._load_treadmill_report(report)

        if getattr(report, "report_config_snapshot", {}).get("data_source") == "simulation":
            self._title.setText(self._title.text() + " · 模拟数据（非实测）")

        quality = report.report_config_snapshot.get("beam_quality")
        transient_pulses = (quality or {}).get("preflight", {}).get("stability", {}).get("transient_beam_pulses", 0)
        if quality and (quality.get("degraded") or quality.get("events") or transient_pulses):
            count = len(quality.get("preflight", {}).get("bad_indices", ()))
            self._reason_label.setText(self._reason_label.text() +
                f"\n设备质量：冻结 {count} 束不可用，运行中 {quality.get('event_count', 0)} 项记录。" +
                (f"自检短时变化 {transient_pulses} 次（按光束计数，未计入坏灯），原始运动数据保留。" if transient_pulses else "") +
                quality.get("limitation", ""))
            self._reason_label.setWordWrap(True)
        self._reason_label.setToolTip("未记录设备质量信息" if quality is None else
                                      __import__("json").dumps(quality, ensure_ascii=False, indent=2))

        self._request_latest_if_available()

    def answer_gait_question(self, question: str) -> str:
        from reporting.gait_insights import answer_gait_question

        answer = answer_gait_question(self._report, question, self._gait_topic)
        self._gait_topic = answer.topic or self._gait_topic
        self._gait_question.setText(question)
        links = " · ".join(
            f'<a href="{kind}:{index}">{"逐步" if kind == "step" else "周期"} {index + 1}</a>'
            for kind, index in answer.references
        )
        self._gait_answer.setHtml(
            "<p>" + html.escape(answer.text).replace("\n", "<br>") + "</p>"
            + ("<p>点击定位证据：<br>" + links + "</p>" if links else "")
        )
        if isinstance(self._report, TreadmillGaitReport):
            self._tabs.setCurrentIndex(self._gait_question_index)
        return answer.text

    def _locate_gait_evidence(self, url):
        if url.scheme() not in {"cycle", "step"} or not url.path().isdigit():
            return
        cycle = url.scheme() == "cycle"
        detail_filter = self._cycle_filter if cycle else self._step_filter
        detail_filter.setCurrentIndex(0)
        table = self._cycle_detail_table if cycle else self._treadmill_step_table
        self._tabs.setCurrentWidget(self._details_page)
        self._detail_tabs.setCurrentWidget(self._cycle_page if cycle else self._step_page)
        number = str(int(url.path()) + 1)
        for row in range(table.rowCount()):
            if table.item(row, 0).text() == number:
                table.setCurrentCell(row, 0)
                table.scrollToItem(table.item(row, 0))
                table.item(row, 0).setBackground(QColor("#805018"))
                break

    def set_analysis_availability(self, available: bool) -> None:
        self._analysis_available = available
        self._refresh_analysis_visibility()
        self._request_latest_if_available()

    def set_analysis_loading(self, loading: bool) -> None:
        self._analysis_button.setEnabled(not loading)
        self._analysis_status.setText("正在分析本次测试记录…" if loading else "")
        self._analysis_status.setVisible(loading)

    def show_validated_analysis(self, analysis: dict) -> None:
        claims = analysis.get("claims", [])
        sections = []
        claim_lines = []
        for claim in claims:
            text = claim.get("text", "").strip()
            if not text:
                continue
            text = html.escape(text)
            claim_limitations = claim.get("limitations", [])
            if claim_limitations:
                text += "<br><span style='color:#aeb7c5'>证据限制：" + "；".join(
                    html.escape(str(item)) for item in claim_limitations
                ) + "</span>"
            claim_lines.append(f"<div style='margin-bottom:8px'>{text}</div>")
        if claim_lines:
            sections.append("<h3>分析结论</h3>" + "".join(claim_lines))

        references = analysis.get("references", [])
        reference_by_id = {
            item.get("citation_id"): (index, item)
            for index, item in enumerate(references, start=1)
            if item.get("citation_id")
        }
        recommendation_lines = []
        for recommendation in analysis.get("recommendations", []):
            text = html.escape(str(recommendation.get("text", "")).strip())
            if not text:
                continue
            links = []
            for citation_id in recommendation.get("citation_refs", []):
                resolved = reference_by_id.get(citation_id)
                if resolved is not None:
                    links.append(f"[{resolved[0]}]")
            suffix = " " + " ".join(links) if links else ""
            recommendation_limitations = recommendation.get(
                "limitations", []
            )
            limitation_text = ""
            if recommendation_limitations:
                limitation_text = (
                    "<br><span style='color:#aeb7c5'>建议限制："
                    + "；".join(
                        html.escape(str(item))
                        for item in recommendation_limitations
                    )
                    + "</span>"
                )
            recommendation_lines.append(
                f"<div style='margin-bottom:8px'>{text}{suffix}"
                f"{limitation_text}</div>"
            )
        if recommendation_lines:
            sections.append(
                "<h3>循证行动建议</h3>" + "".join(recommendation_lines)
            )

        reference_lines = []
        for index, reference in enumerate(references, start=1):
            title = html.escape(str(reference.get("title", "参考资料")))
            url = str(reference.get("url", ""))
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            locator = html.escape(str(reference.get("locator", "")))
            details = f" — {locator}" if locator else ""
            reference_lines.append(
                f"<div>[{index}] <a href='{html.escape(url, quote=True)}'>{title}</a>{details}</div>"
            )
        if reference_lines:
            sections.append("<h3>参考资料</h3>" + "".join(reference_lines))

        rag_audit = analysis.get("rag_audit")
        if isinstance(rag_audit, dict):
            rag_status = rag_audit.get("status")
            if rag_status == "degraded":
                error_code = html.escape(
                    str(rag_audit.get("error_code") or "unknown")
                )
                sections.append(
                    "<div style='color:#aeb7c5'>循证建议暂时不可用，"
                    "确定性分析不受影响。"
                    f"（{error_code}）</div>"
                )
            elif rag_status == "no_evidence":
                message = (
                    "当前测试场景或已验证指标尚无适用的循证建议，因此未生成建议。"
                    if rag_audit.get("error_code") == "no_supported_query"
                    else "未检索到满足条件的文献证据，因此未生成建议。"
                )
                sections.append(
                    f"<div style='color:#aeb7c5'>{message}</div>"
                )

        limitations = analysis.get("overall_limitations", [])
        if limitations:
            sections.append(
                "<div><b>限制：</b>" + "；".join(
                    html.escape(str(item)) for item in limitations
                )
                + "</div>"
            )
        self._analysis_result.setText(
            "".join(sections) if sections else "未形成可验证的分析结论。"
        )
        self._analysis_result.show()
        self._analysis_button.setText("重新分析")

    def clear_analysis(self) -> None:
        self.set_analysis_loading(False)
        self._analysis_result.clear()
        self._analysis_result.hide()
        self._analysis_button.setText("开始智能分析")

    def _refresh_analysis_visibility(self) -> None:
        supported = isinstance(
            self._report,
            (JumpTestReport, TreadmillGaitReport, TreadmillRunningReport),
        )
        visible = (
            self._analysis_available
            and self._llm_client is not None
            and self._session_id is not None
            and supported
        )
        self._analysis_panel.setVisible(visible)
        if not visible:
            self.clear_analysis()

    def _on_analysis_clicked(self) -> None:
        if self._analysis_panel.isHidden() or self._session_id is None:
            return
        if any(worker.isRunning() for worker in self._analysis_workers):
            return
        self._start_analysis_request("analyze")

    def request_voice_analysis(self) -> bool:
        if self._analysis_panel.isHidden() or self._session_id is None:
            return False
        if any(worker.isRunning() for worker in self._analysis_workers):
            return False
        self._start_analysis_request("analyze")
        return True

    def _start_analysis_request(self, action: str) -> None:
        if self._llm_client is None or self._session_id is None:
            return
        worker = _ReportAnalysisWorker(
            self._llm_client,
            self._session_id,
            action,
            self,
        )
        self._analysis_workers.add(worker)
        worker.completed.connect(self._on_analysis_completed)
        worker.failed.connect(self._on_analysis_failed)
        worker.finished.connect(
            lambda worker=worker: self._release_analysis_worker(worker)
        )
        if action == "analyze":
            self.set_analysis_loading(True)
        worker.start()

    def _request_latest_if_available(self) -> None:
        if (
            self._session_id is None
            or self._analysis_panel.isHidden()
            or self._latest_requested_for == self._session_id
        ):
            return
        self._latest_requested_for = self._session_id
        self._start_analysis_request("latest")

    def _release_analysis_worker(self, worker: _ReportAnalysisWorker) -> None:
        self._analysis_workers.discard(worker)
        # Keep the finished QThread wrapper alive until this view is destroyed.
        # Deleting it from its own ``finished`` delivery can leave queued Qt
        # events targeting a partially destroyed Python subclass.
        self._finished_analysis_workers.append(worker)

    def _on_analysis_completed(
        self,
        session_id: int,
        action: str,
        analysis: object,
    ) -> None:
        if session_id != self._session_id or not self._analysis_available:
            return
        self.set_analysis_loading(False)
        if isinstance(analysis, dict):
            self.show_validated_analysis(analysis)
            if action == "analyze":
                from voice.responses import analysis_speech
                self.voice_reply.emit(analysis_speech(analysis))

    def _on_analysis_failed(
        self,
        session_id: int,
        action: str,
        error_code: str,
    ) -> None:
        if session_id != self._session_id or not self._analysis_available:
            return
        self.set_analysis_loading(False)
        if action == "analyze":
            self.voice_reply.emit("报告分析暂时不可用，请查看界面提示后重试。")
            messages = {
                "worker_not_ready": "智能分析服务尚未就绪。",
                "external_scope_not_implemented": "当前版本仅支持本次记录分析。",
                "analysis_unavailable": "暂时无法读取智能分析结果。",
                "analysis_timeout": "智能分析超过服务端时间限制，请重试。",
                "analysis_client_timeout": "智能分析服务未在预期时间内响应，请重试。",
            }
            self._analysis_status.setText(
                messages.get(error_code, "智能分析未能生成通过验证的结果。")
            )
            self._analysis_status.show()

    # ------------------------------------------------------------------
    #  纵跳报告
    # ------------------------------------------------------------------

    def _load_jump_report(self, r: JumpTestReport):
        self._title.setText("📊 测试报告 — 纵跳测试")

        stats: list[tuple[str, str, str]] = [
            (
                "有效跳跃次数",
                str(len(r.jump_heights)),
                "形成完整有效结果的跳跃次数。",
            ),
        ]
        if r.jump_heights:
            stats.extend(
                [
                    (
                        "平均跳高",
                        f"{r.avg_jump_height:.3f} m",
                        "全部有效跳跃高度的平均值。",
                    ),
                    (
                        "最大跳高",
                        f"{r.max_jump_height:.3f} m",
                        "本次测试记录到的最大跳跃高度。",
                    ),
                ]
            )
        if r.air_times:
            stats.append(
                (
                    "平均腾空时间",
                    f"{r.avg_air_time:.3f} s",
                    "全部有效跳跃腾空时间的平均值。",
                )
            )
        if r.contact_times:
            stats.append(
                (
                    "平均触地时间",
                    f"{r.avg_contact_time:.3f} s",
                    "全部有效触地阶段持续时间的平均值。",
                )
            )
        if r.avg_cadence is not None:
            stats.append(
                (
                    "平均跳跃节奏",
                    f"{r.avg_cadence:.1f} jumps/min",
                    "按完整跳跃周期计算的平均每分钟跳跃次数。",
                )
            )
        excluded_count = sum(
            not row.is_included_in_statistics for row in r.jump_results
        )
        flagged_count = sum(bool(row.quality_flags) for row in r.jump_results)
        if excluded_count or flagged_count or r.quality_notices:
            stats.append(
                (
                    "质量提示",
                    f"{excluded_count} 条排除 / {flagged_count + len(r.quality_notices)} 条标记",
                    "异常配对、超长腾空、帧间隔或超限遮挡的复核摘要。",
                )
            )
        reason = {
            "jump_count_reached": "达到设定跳跃次数",
            "time_up": "测试时间到",
            "manual": "手动结束",
        }.get(r.finish_reason, r.finish_reason)
        stats.extend(
            [
                ("触地次数", str(r.touch_count), "检测到的触地事件总数。"),
                ("离地次数", str(r.lift_count), "检测到的离地事件总数。"),
                ("测试结束原因", reason, "本次测试停止的触发条件。"),
            ]
        )
        self._fill_stat_cards(stats)

        # 高亮最大跳高
        if r.jump_heights and len(self._stat_cards) > 2:
            self._stat_cards[2].set_color(dayu_theme.primary_color)

        # 图表: 全量数据
        if _PG_AVAILABLE and r.jump_heights:
            heights = list(r.jump_heights)
            x = list(range(1, len(heights) + 1))

            self._plot_1.clear()
            self._plot_1.setLabel('left', '跳高 (m)')
            self._plot_1.setLabel('bottom', '跳跃次数')
            bar1 = pg.BarGraphItem(x=x, height=heights, width=0.65, brush=dayu_theme.primary_color)
            self._plot_1.addItem(bar1)

            self._plot_2.clear()
            self._plot_2.setLabel('left', '腾空时间 (s)')
            self._plot_2.setLabel('bottom', '跳跃次数')
            bar2 = pg.BarGraphItem(x=x, height=list(r.air_times), width=0.65, brush='#52c41a')
            self._plot_2.addItem(bar2)

    # ------------------------------------------------------------------
    #  步态报告
    # ------------------------------------------------------------------

    def _load_gait_report(self, r: GaitTestReport):
        self._title.setText("📊 测试报告 — 步态分析")
        self._plot_container.hide()
        self._replay_panel.show()
        self._replay_panel.set_direction("Interface side")
        self._replay_panel.set_timeline(getattr(r, "visual_timeline", ()))

        if r.walking_summary:
            self._load_walking_stats(r)
            return
        stats = [
            ("总步数", f"{r.touch_count}", "检测到的触地事件总数。"),
            ("离地次数", f"{r.lift_count}", "检测到的离地事件总数。"),
            ("平均步长", f"{r.avg_stride:.2f} cm", "全部步长的平均值。"),
            ("最大步长", f"{r.max_stride:.2f} cm", "本次测试的最大步长。"),
            ("平均步速", f"{r.avg_velocity:.2f} cm/s", "全部步速的平均值。"),
            ("最大步速", f"{r.max_velocity:.2f} cm/s", "本次测试的最大步速。"),
        ]

        if r.imbalance_index is not None:
            stats.append(
                (
                    "不平衡指数",
                    f"{r.imbalance_index:.1f}%",
                    "左右侧支撑时间的相对差异。",
                )
            )
        if r.avg_double_support is not None:
            stats.append(
                (
                    "双支撑期",
                    f"{r.avg_double_support:.3f} s",
                    "双脚同时接触测试区域的平均时间。",
                )
            )

        self._fill_stat_cards(stats)

        # 图表
        if _PG_AVAILABLE and r.stride_lengths:
            x = list(range(1, len(r.stride_lengths) + 1))

            self._plot_1.clear()
            self._plot_1.setLabel('left', '步长 (cm)')
            self._plot_1.setLabel('bottom', '步数')
            bar1 = pg.BarGraphItem(x=x, height=list(r.stride_lengths), width=0.65, brush=dayu_theme.primary_color)
            self._plot_1.addItem(bar1)

        if _PG_AVAILABLE and r.velocities:
            x2 = list(range(1, len(r.velocities) + 1))
            self._plot_2.clear()
            self._plot_2.setLabel('left', '步速 (cm/s)')
            self._plot_2.setLabel('bottom', '步数')
            bar2 = pg.BarGraphItem(x=x2, height=list(r.velocities), width=0.65, brush='#52c41a')
            self._plot_2.addItem(bar2)

    # ------------------------------------------------------------------
    #  跑步机报告
    # ------------------------------------------------------------------

    def _load_overground_running(self, r):
        from reporting.overground_running import detail_html, FINISH_LABELS
        self._reason_label.setText(FINISH_LABELS.get(r.finish_reason, r.finish_reason))
        self._title.setText("测试报告 — 地面跑步")
        self._plot_container.hide()
        self._replay_panel.show()
        self._replay_panel.set_direction("Interface side")
        self._replay_panel.set_timeline(r.visual_timeline)
        s = r.running_summary
        def value(x, unit=""):
            return f"{x:.3f} {unit}" if x is not None else "数据不足"
        group = s["groups"]["all"]
        stats = [
            ("设备长度", f"{s['segment_count']} 段 / {s['nominal_length_m']} 米", "距离使用实际光束坐标"),
            ("有效步数 / 周期", f"{s['valid_steps']} / {s['valid_cycles']}", "时间指标有效的记录数；各空间指标独立筛选"),
            ("平均步长", value(s['step_statistics']['length_m']['mean'], "m"), "脚尖到脚尖"),
            ("平均跨步长", value(group['length_m']['mean'], "m"), "同脚脚尖到脚尖"),
            ("平均速度", value(s['running_speed_m_s'], "m/s"), "有效距离总和除以对应时间总和"),
            ("平均接触", value(group['contact_s']['mean'], "s"), "有效同脚周期接触时间"),
            ("平均摆动", value(group['swing_s']['mean'], "s"), "同脚离地至再次触地"),
            ("平均腾空", value(group['flight_s']['mean'], "s"), "完整同脚周期内腾空总和"),
            ("单 / 双支撑", value(group['single_support_s']['mean'], "s") + " / " + value(group['double_support_s']['mean'], "s"), "各指标独立有效"),
            ("测量时长", value(s['duration_s'], "s"), "包含停步，不含等待进入和结束确认"),
            ("有腾空 / 无腾空 / 不确定", f"{s['flight_cycle_count']} / {s['zero_flight_cycle_count']} / {s['unknown_flight_cycle_count']}", "不据此判定走路"),
            ("停步 / 异常", f"{len(s['stops'])} / {len(s['issues'])}", "原因与分组、左右比较见明细；实测待验证"),
        ]
        self._fill_stat_cards(stats)
        details = QTextBrowser()
        details.setHtml(detail_html(r))
        self._add_detail_widget(details, self._summary_layout)

    def _load_walking_stats(self, r):
        s = r.walking_summary
        self._title.setText("测试报告 — 地面走路")
        def metric(label, key, unit, note):
            value = s.get(key)
            return (label, f"{value:.3f} {unit}" if value is not None else "数据不足", note)
        stats = [
            ("设备长度", f"{s['segment_count']} 段 / {s['nominal_length_m']} 米", "本次通过自检的标称长度；距离计算使用光束坐标。"),
            ("有效步数 / 周期", f"{s['valid_steps']} / {s['valid_cycles']}", "仅统计完整、连续且身份关系明确的数据。"),
            metric("平均步长", "mean_step_m", "m", "相邻有效落脚点距离。"),
            metric("平均跨步长", "mean_stride_m", "m", "同脚连续两次有效落脚点距离。"),
            metric("步频", "cadence_per_min", "步/min", "有效行走片段的步频，排除停步候选区间。"),
            metric("平均接触时间", "mean_contact_s", "s", "完整光学遮挡接触区间，排除停步候选区间。"),
            metric("单支撑时间", "single_support_s", "s", "完整步态周期内单支撑总时长的平均值。"),
            metric("双支撑时间", "double_support_s", "s", "完整步态周期内双支撑总时长的平均值。"),
            metric("测量时长", "duration_s", "s", "首次有效触地至最后遮挡结束，包含停步。"),
            metric("整趟前进速度", "passage_speed_m_s", "m/s", "首末落脚点位移除以测量时长，包含停步；非人体质心速度，有采集缺口时留空。"),
            metric("行走阶段速度", "walking_speed_m_s", "m/s", "有效步长总和除以对应步间时间总和。"),
            ("停步 / 排除接触 / 异常", f"{len(s['stops'])} / {s['excluded_contacts']} / {len(s['issues'])}", "保留停步，不跨异常拼接周期；详细原因见测量明细。"),
        ]
        self._fill_stat_cards(stats)
        reasons = {"passage_complete": "测试完成 · 已通过测量区域", "manual": "手动结束",
                   "disconnected": "测试中断 · 设备断连", "data_timeout": "测试中断 · 数据超时",
                   "layout_mismatch": "测试中断 · 段数变化", "device_changed": "测试中断 · 设备变化",
                   "out_of_order_or_reset": "测试中断 · 帧序号异常", "turn_detected": "测试中断 · 检测到反向行走"}
        self._reason_label.setText(reasons.get(r.finish_reason, "测试中断 · " + r.finish_reason))
        details = QTextBrowser()
        details.setOpenExternalLinks(False)
        def table(title, headers, rows):
            cells = lambda row: "".join("<td>" + html.escape(str(v) if v is not None else "数据不足") + "</td>" for v in row)
            return "<h3>" + title + "</h3><table cellspacing='8'><tr>" + cells(headers) + "</tr>" + "".join("<tr>" + cells(row) + "</tr>" for row in rows) + "</table>"
        reasons_cn = {"boundary_contact": "边缘接触不完整", "incomplete_contact": "接触尚未结束",
                      "frame_gap": "丢帧", "unknown_touch_after_gap": "缺口后触地时间未知",
                      "ambiguous_contacts": "遮挡合并或身份不确定", "simultaneous_contacts": "同时出现，身份不确定",
                      "short_contact": "接触过短或足迹不足", "pending_touch_order": "较早接触尚未确认"}
        content = table("接触记录", ["序号", "脚 / 身份段", "触地(s)", "离地(s)", "位置(m)", "短中断合并", "排除原因"],
                        [[c["id"], c["side"] if c["side"] != "unknown" else f"{c['label']} / {c['epoch']}",
                          c["start"], c["end"], round(c["position_m"], 4),
                          f"{len(c.get('merged_interruptions', []))} 次 / "
                          f"{sum(x['end_sample'] - x['start_sample'] for x in c.get('merged_interruptions', []))} ms",
                          reasons_cn.get(c["exclusion"], c["exclusion"]) or ""]
                         for c in s["contacts"]])
        content += table("停步候选区间", ["开始(s)", "结束(s)"], [[x["start_s"], x["end_s"]] for x in s["stops"]])
        content += table("采集异常", ["时间(s)", "原因", "帧标识"],
                         [[x["time_s"], reasons_cn.get(x["code"], x["code"]), x["frame_index"]] for x in s["issues"]])
        if r.report_config_snapshot.get("raw_buffer", {}).get("truncated"):
            content = "<p>原始帧缓存已达到容量上限，导出仅包含末尾保留帧；统计结果仍基于完整处理过程。</p>" + content
        details.setHtml(content)
        self._add_detail_widget(details, self._summary_layout)

    def _load_treadmill_report(self, r: TreadmillGaitReport | TreadmillRunningReport):
        test_type_label = "跑步机步态" if isinstance(r, TreadmillGaitReport) else "跑步机跑步"
        self._title.setText(f"测试报告 — {test_type_label}")
        self._plot_container.hide()
        self._replay_panel.show()

        # 配置快照
        snap = r.report_config_snapshot
        direction = snap.get("direction", "--")
        self._replay_panel.set_direction(direction)
        self._replay_panel.set_timeline(getattr(r, "visual_timeline", ()))

        self._fill_stat_cards(_treadmill_overview_stats(r))

        self._build_treadmill_summary_table(r)
        self._rebuild_cycle_detail_table()
        self._rebuild_step_detail_table()

    def _build_cycle_detail_table(self, cycles: tuple[GaitCycleRecord, ...]):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        columns = [
            "序号",
            "脚",
            "周期阶段图",
            "步态周期(s)",
            "支撑相(%)",
            "摆动相(%)",
            "步幅(cm)",
            "纳入统计",
            "统计说明",
        ]
        table = QTableWidget(len(cycles), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row, cycle in enumerate(cycles):
            values = [
                str(cycle.index + 1),
                _side_label(cycle.side),
                None,
                _fmt(cycle.gait_cycle_s),
                _fmt(cycle.stance_phase_percent),
                _fmt(cycle.swing_phase_percent),
                _fmt(cycle.stride_length_cm),
                "是" if cycle.is_included_in_statistics else "否",
                _statistics_note(
                    cycle.is_included_in_statistics,
                    cycle.statistics_exclusion_reason,
                    cycle.quality_flags,
                ),
            ]
            for column, text in enumerate(values):
                if column == 2:
                    table.setCellWidget(row, column, CyclePhaseBar(cycle))
                    continue
                item = QTableWidgetItem(text or "N/A")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, column, item)
        header = table.horizontalHeader()
        for column in range(len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.Stretch)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._cycle_detail_table = table
        self._cycle_timeline_table = table
        self._add_detail_widget(table, self._cycle_layout)

    def _build_treadmill_summary_table(
        self, report: TreadmillGaitReport | TreadmillRunningReport
    ):
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        step_rows = [
            ("step_length_cm", "步长 (cm)", 1.0),
            ("cadence_steps_per_min", "步频 (steps/min)", 1.0),
            ("contact_time_s", "触地时间 (ms)", 1000.0),
        ]
        cycle_rows = [
            ("stride_length_cm", "步幅 (cm)", 1.0),
            ("gait_cycle_s", "步态周期 (s)", 1.0),
        ]
        if isinstance(report, TreadmillRunningReport):
            step_rows.append(("flight_time_s", "腾空时间 (ms)", 1000.0))
        cycle_rows.extend(
            [
                ("stance_phase_percent", "支撑相 (%)", 1.0),
                ("swing_phase_percent", "摆动相 (%)", 1.0),
            ]
        )
        if isinstance(report, TreadmillGaitReport):
            cycle_rows.extend(
                [
                    (
                        "total_double_support_s",
                        "双支撑时间 (ms)",
                        1000.0,
                    ),
                    ("single_support_s", "单支撑时间 (ms)", 1000.0),
                ]
            )

        ordered_rows = [
            ("step", *step_rows[0]),
            ("cycle", *cycle_rows[0]),
            ("step", *step_rows[1]),
            ("cycle", *cycle_rows[1]),
            ("step", *step_rows[2]),
        ]
        if isinstance(report, TreadmillRunningReport):
            ordered_rows.append(("step", *step_rows[3]))
        ordered_rows.extend(
            ("cycle", *row) for row in cycle_rows[2:]
        )

        rows = []
        for source, key, label, scale in ordered_rows:
            if source == "step":
                summary = report.metric_summaries.get(key)
                left = report.left_right_results.get(f"left_{key}")
                right = report.left_right_results.get(f"right_{key}")
                asymmetry = report.asymmetry_metrics.get(f"{key}_percent")
            else:
                summary = report.cycle_metric_summaries.get(key)
                left = report.cycle_side_summaries.get("left", {}).get(key)
                right = report.cycle_side_summaries.get("right", {}).get(key)
                asymmetry = report.cycle_asymmetry_percent.get(key)
            if summary is None or summary.count == 0:
                continue

            side_samples_sufficient = (
                left is not None
                and right is not None
                and left.count >= 3
                and right.count >= 3
            )
            if not side_samples_sufficient:
                asymmetry_text = "样本不足"
            elif asymmetry is not None:
                asymmetry_text = f"{asymmetry:.1f}%"
            else:
                asymmetry_text = "—"
            rows.append(
                [
                    label,
                    str(summary.count),
                    _scaled_fmt(summary.mean, scale),
                    _scaled_fmt(left.mean if left else None, scale),
                    _scaled_fmt(right.mean if right else None, scale),
                    asymmetry_text,
                    _scaled_fmt(summary.min, scale),
                    _scaled_fmt(summary.max, scale),
                    _scaled_fmt(summary.std, scale),
                    _fmt(summary.cv_percent),
                ]
            )

        columns = [
            "指标",
            "有效样本数",
            "总体均值",
            "左脚均值",
            "右脚均值",
            "不对称性",
            "最小值",
            "最大值",
            "标准差",
            "CV(%)",
        ]
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row_index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text or "—")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, item)
        header = table.horizontalHeader()
        for column in range(len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.Stretch)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._summary_table = table
        self._cycle_summary_table = table
        self._add_detail_widget(table, self._summary_layout)
        self._toggle_extended_summary_columns(
            self._more_stats_button.isChecked()
        )

    def _build_treadmill_step_table(self, steps: tuple[TreadmillStepResult, ...]):
        """Build the mode-specific per-step detail table."""
        from qtpy.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

        is_running = isinstance(self._report, TreadmillRunningReport)
        show_flight = is_running and any(
            step.flight_time_s is not None
            for step in getattr(self._report, "per_step_results", ())
        )
        columns = [
            "序号",
            "脚",
            "步长(cm)",
            "触地时间(ms)",
        ]
        if show_flight:
            columns.append("腾空时间(ms)")
        columns.extend(["纳入统计", "统计说明"])

        table = QTableWidget(len(steps), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        for row_idx, step in enumerate(steps):
            items = [
                str(step.index + 1),
                _side_label(step.side),
                _fmt(step.step_length_cm),
                _scaled_fmt(step.contact_time_s, 1000.0),
            ]
            if show_flight:
                items.append(_scaled_fmt(step.flight_time_s, 1000.0))
            items.extend(
                [
                    "是" if step.is_included_in_statistics else "否",
                    _statistics_note(
                        step.is_included_in_statistics,
                        step.statistics_exclusion_reason,
                        step.quality_flags,
                    ),
                ]
            )
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text or "N/A")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, col_idx, item)

        header = table.horizontalHeader()
        for col in range(len(columns)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(columns) - 1, QHeaderView.Stretch)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._treadmill_step_table = table
        self._add_detail_widget(table, self._step_layout)

    # ------------------------------------------------------------------
    #  辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_detail_filter() -> QComboBox:
        detail_filter = QComboBox()
        detail_filter.setObjectName("ReportFilterCombo")
        detail_filter.addItem("已纳入", "included")
        detail_filter.addItem("已排除", "excluded")
        detail_filter.addItem("全部", "all")
        detail_filter.setMinimumWidth(120)
        return detail_filter

    @staticmethod
    def _filter_row(label: str, detail_filter: QComboBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        filter_label = QLabel(label)
        filter_label.setObjectName("ReportFilterLabel")
        row.addWidget(filter_label)
        row.addWidget(detail_filter)
        row.addStretch()
        return row

    @staticmethod
    def _filter_items(items: tuple, filter_value: str) -> tuple:
        if filter_value == "included":
            return tuple(
                item
                for item in items
                if item.is_included_in_statistics
            )
        if filter_value == "excluded":
            return tuple(
                item
                for item in items
                if not item.is_included_in_statistics
            )
        return items

    def _rebuild_cycle_detail_table(self, _index=None):
        if not isinstance(
            self._report, (TreadmillGaitReport, TreadmillRunningReport)
        ):
            return
        self._drop_dynamic_table(
            "_cycle_detail_table", "_cycle_timeline_table"
        )
        cycles = self._filter_items(
            self._report.gait_cycles,
            self._cycle_filter.currentData(),
        )
        self._build_cycle_detail_table(cycles)

    def _rebuild_step_detail_table(self, _index=None):
        if not isinstance(
            self._report, (TreadmillGaitReport, TreadmillRunningReport)
        ):
            return
        self._drop_dynamic_table("_treadmill_step_table")
        steps = self._filter_items(
            self._report.per_step_results,
            self._step_filter.currentData(),
        )
        self._build_treadmill_step_table(steps)

    def _toggle_extended_summary_columns(self, checked: bool):
        table = getattr(self, "_summary_table", None)
        if table is None:
            return
        for column in range(6, 10):
            table.setColumnHidden(column, not checked)

    def _drop_dynamic_table(self, *attribute_names: str):
        table = next(
            (
                getattr(self, name, None)
                for name in attribute_names
                if getattr(self, name, None) is not None
            ),
            None,
        )
        if table is not None:
            if table in self._dynamic_widgets:
                self._dynamic_widgets.remove(table)
            table.setParent(None)
            table.deleteLater()
        for name in attribute_names:
            setattr(self, name, None)

    def _clear_dynamic_widgets(self):
        """Remove and delete all dynamically-added widgets to avoid stale tables."""
        for w in self._dynamic_widgets:
            w.setParent(None)
            w.deleteLater()
        self._dynamic_widgets.clear()
        for name in (
            "_summary_table",
            "_cycle_summary_table",
            "_cycle_detail_table",
            "_cycle_timeline_table",
            "_treadmill_step_table",
        ):
            setattr(self, name, None)

    def _add_detail_widget(self, widget: QWidget, layout: QVBoxLayout):
        if isinstance(widget, QTableWidget):
            widget.setObjectName("ReportDetailTable")
            widget.verticalHeader().setDefaultSectionSize(34)
            widget.verticalHeader().setMinimumSectionSize(30)
            widget.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(widget, 1)
        self._dynamic_widgets.append(widget)

    def _fill_stat_cards(self, stats: list[tuple[str, str, str]]):
        """填充至多 12 张统计卡片。"""
        for i, card in enumerate(self._stat_cards):
            if i < min(len(stats), 12):
                label, value, tooltip = stats[i]
                card._label.setText(label)
                card.set_value(value)
                card.set_color("#f0f0f0")
                card.setToolTip(tooltip)
                card._label.setToolTip(tooltip)
                card._value.setToolTip(tooltip)
                card.show()
            else:
                card.setToolTip("")
                card._label.setToolTip("")
                card._value.setToolTip("")
                card.hide()
        self._stats_layout.invalidate()
        self._stats_content.updateGeometry()

    def _on_export(self):
        """导出原始帧数据为 Excel。"""
        if self._report is None:
            return

        frames = self._report.export_frames
        timestamps = self._report.export_timestamps
        has_jump_metrics = isinstance(self._report, JumpTestReport) and any(
            (
                self._report.air_times,
                self._report.contact_times,
                self._report.cycle_times,
                self._report.jump_heights,
                self._report.cadences,
            )
        )

        has_treadmill_steps = isinstance(
            self._report, (TreadmillGaitReport, TreadmillRunningReport)
        ) and bool(
            self._report.per_step_results
            or self._report.gait_cycles
            or self._report.raw_gait_events
        )

        has_walking = isinstance(self._report, GaitTestReport) and bool(self._report.walking_summary)
        has_running = isinstance(self._report, OvergroundRunningReport)
        if not frames and not has_jump_metrics and not has_treadmill_steps and not has_walking and not has_running:
            QMessageBox.information(self, "导出", "本次测试无可导出数据。")
            return

        reply = QMessageBox.question(
            self, "导出数据",
            f"本次采集共 {len(frames)} 帧数据，是否保存？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        save_dir = os.path.join(_get_base_dir(), "data")
        os.makedirs(save_dir, exist_ok=True)
        filename = time.strftime("led_frames_%Y%m%d_%H%M%S.xlsx")
        path = os.path.join(save_dir, filename)

        try:
            wb = Workbook()
            snapshot = getattr(self._report, "report_config_snapshot", {})
            import json
            quality_sheet = wb.create_sheet("设备质量")
            quality = snapshot.get("beam_quality")
            if quality is None:
                quality_sheet.append(["状态", "未记录（不代表无异常）"])
            else:
                def append_quality(path, value):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            append_quality(f"{path}.{key}" if path else key, item)
                    elif isinstance(value, (list, tuple)):
                        for index, item in enumerate(value):
                            append_quality(f"{path}[{index}]", item)
                    else:
                        quality_sheet.append([path, value])
                append_quality("", quality)
            if snapshot.get("data_source") == "simulation":
                provenance = wb.create_sheet("数据来源")
                provenance.append(["数据来源", "模拟演示数据，非受试者实测"])
                provenance.append(["说明", snapshot.get("simulation_description", "")])
            default_ws = wb.active
            if frames:
                default_ws.title = "LED Frames"
                default_ws.append(["timestamp", "hex_string"])
                for ts, bits in zip(timestamps, frames):
                    hex_bytes = []
                    for i in range(0, len(bits), 8):
                        byte_val = 0
                        for j in range(8):
                            if i + j < len(bits):
                                byte_val |= (bits[i + j] << j)
                        hex_bytes.append(byte_val)
                    hex_str = " ".join(f"{b:02x}" for b in hex_bytes)
                    default_ws.append([ts, hex_str])
            else:
                wb.remove(default_ws)

            if has_running:
                from reporting.overground_running import export_sheets
                export_sheets(wb, self._report)

            if has_walking:
                import json
                summary = self._report.walking_summary
                ws_summary = wb.create_sheet("Walking Summary")
                ws_summary.append(["metric", "value"])
                for key, value in summary.items():
                    if not isinstance(value, (list, dict)):
                        ws_summary.append([key, value])
                ws_device = wb.create_sheet("Device and Config")
                for key, value in snapshot.items():
                    ws_device.append([key, json.dumps(value, ensure_ascii=False)])
                for key in ("contacts", "steps", "cycles", "stops", "issues"):
                    records = summary[key]
                    ws = wb.create_sheet("Walking " + key)
                    if records:
                        columns = list(records[0])
                        ws.append(columns)
                        for record in records:
                            ws.append([json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                                       for value in (record.get(column) for column in columns)])

            if isinstance(self._report, JumpTestReport):
                ws = wb.create_sheet("Jump Metrics")
                ws.append(
                    [
                        "index",
                        "air_time_s",
                        "contact_time_s",
                        "cycle_time_s",
                        "jump_height_m",
                        "cadence_jumps_per_min",
                        "lift_time_s",
                        "touch_time_s",
                        "is_included_in_statistics",
                        "statistics_exclusion_reason",
                        "quality_flags",
                    ]
                )
                for row in _jump_metric_rows(self._report):
                    ws.append(row)
                if self._report.quality_notices:
                    notice_ws = wb.create_sheet("Jump Quality Notices")
                    notice_ws.append(
                        ["kind", "time_s", "cluster_length", "ratio"]
                    )
                    for notice in self._report.quality_notices:
                        notice_ws.append(
                            [
                                notice.kind,
                                notice.time_s,
                                notice.cluster_length,
                                notice.ratio,
                            ]
                        )

            if isinstance(self._report, (TreadmillGaitReport, TreadmillRunningReport)):
                # Sheet 2: Treadmill Steps
                ws_steps = wb.create_sheet("Treadmill Steps")
                ws_steps.append(TREADMILL_EXPORT_COLUMNS)
                for row in _treadmill_metric_rows(self._report):
                    ws_steps.append(row)

                if self._report.gait_cycles:
                    ws_cycles = wb.create_sheet("步态周期")
                    ws_cycles.append(GAIT_CYCLE_EXPORT_HEADERS)
                    for row in _gait_cycle_rows(self._report):
                        ws_cycles.append(row)

                if self._report.raw_gait_events:
                    ws_events = wb.create_sheet("原始步态事件")
                    ws_events.append(["序号", "时间(s)", "脚", "事件"])
                    for event in self._report.raw_gait_events:
                        ws_events.append([
                            event.index + 1,
                            event.time_s,
                            _side_label(event.side),
                            "触地" if event.kind == "touch" else "离地",
                        ])

                if self._report.cycle_metric_summaries:
                    ws_cycle_summary = wb.create_sheet("步态周期统计")
                    ws_cycle_summary.append([
                        "指标", "总体数量", "总体均值",
                        "左脚数量", "左脚均值", "右脚数量", "右脚均值",
                        "不对称率(%)",
                    ])
                    for name, summary in self._report.cycle_metric_summaries.items():
                        left = self._report.cycle_side_summaries.get("left", {}).get(name)
                        right = self._report.cycle_side_summaries.get("right", {}).get(name)
                        ws_cycle_summary.append([
                            GAIT_CYCLE_METRIC_LABELS.get(name, name),
                            summary.count, _excel_cycle_value(summary.mean),
                            left.count if left else 0,
                            _excel_cycle_value(left.mean if left else None),
                            right.count if right else 0,
                            _excel_cycle_value(right.mean if right else None),
                            _excel_cycle_value(
                                self._report.cycle_asymmetry_percent.get(name)
                            ),
                        ])

                # Sheet 3 (optional): Metric Summaries
                metric_summaries = self._report.metric_summaries
                if metric_summaries:
                    ws_metrics = wb.create_sheet("Metric Summaries")
                    ws_metrics.append(["metric", "count", "mean", "min", "max", "std", "cv_percent"])
                    for name, sm in metric_summaries.items():
                        ws_metrics.append([
                            name, sm.count,
                            _fmt(sm.mean), _fmt(sm.min), _fmt(sm.max),
                            _fmt(sm.std), _fmt(sm.cv_percent),
                        ])

            wb.save(path)
            QMessageBox.information(self, "导出成功", f"数据已保存至：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")


TREADMILL_EXPORT_COLUMNS = [
    "index",
    "side",
    "row_status",
    "is_event_valid",
    "is_included_in_statistics",
    "contact_time_s",
    "flight_time_s",
    "step_time_s",
    "step_length_cm",
    "gap_between_feet_cm",
    "distance_cm",
    "speed_m_s",
    "correction_source",
    "statistics_exclusion_reason",
    "quality_flags",
    "step_reference_cm",
]

GAIT_CYCLE_EXPORT_FIELDS = [
    "index", "side", "start_time_s", "end_time_s", "gait_cycle_s",
    "stride_length_cm", "stance_phase_s", "stance_phase_percent",
    "swing_phase_s",
    "swing_phase_percent", "step_time_s", "single_support_s",
    "single_support_percent", "total_double_support_s",
    "total_double_support_percent", "load_response_s",
    "load_response_percent", "pre_swing_s", "pre_swing_percent",
    "total_flight_time_s", "is_included_in_statistics",
    "statistics_exclusion_reason", "quality_flags",
]

GAIT_CYCLE_EXPORT_HEADERS = [
    "序号", "脚", "开始时间(s)", "结束时间(s)", "步态周期(s)",
    "步幅(cm)", "支撑相(s)", "支撑相(%)", "摆动相(s)", "摆动相(%)",
    "步时间(s)", "单支撑(s)", "单支撑(%)", "总双支撑(s)",
    "总双支撑(%)", "负荷反应期(s)", "负荷反应期(%)",
    "摆动前期(s)", "摆动前期(%)", "腾空时间(s)", "纳入统计",
    "未纳入原因", "质量提示",
]

GAIT_CYCLE_METRIC_LABELS = {
    "gait_cycle_s": "步态周期 (s)",
    "stride_length_cm": "步幅 (cm)",
    "stance_phase_s": "支撑相 (s)",
    "stance_phase_percent": "支撑相 (%)",
    "swing_phase_s": "摆动相 (s)",
    "swing_phase_percent": "摆动相 (%)",
    "step_time_s": "步时间 (s)",
    "single_support_s": "单支撑 (s)",
    "single_support_percent": "单支撑 (%)",
    "total_double_support_s": "总双支撑 (s)",
    "total_double_support_percent": "总双支撑 (%)",
    "load_response_s": "负荷反应期 (s)",
    "load_response_percent": "负荷反应期 (%)",
    "pre_swing_s": "摆动前期 (s)",
    "pre_swing_percent": "摆动前期 (%)",
    "total_flight_time_s": "腾空时间 (s)",
}


def _jump_metric_rows(report: JumpTestReport) -> list[list[object]]:
    if report.jump_results:
        return [
            [
                record.index,
                _optional_excel_value(record.air_time_s),
                _optional_excel_value(record.contact_time_s),
                _optional_excel_value(record.cycle_time_s),
                _optional_excel_value(record.jump_height_m),
                _optional_excel_value(record.cadence_jumps_per_min),
                _optional_excel_value(record.lift_time_s),
                _optional_excel_value(record.touch_time_s),
                record.is_included_in_statistics,
                record.statistics_exclusion_reason or "",
                ",".join(record.quality_flags),
            ]
            for record in report.jump_results
        ]

    max_len = max(
        len(report.air_times),
        len(report.jump_heights),
        len(report.contact_times) + (1 if report.contact_times else 0),
        len(report.cycle_times) + (1 if report.cycle_times else 0),
        len(report.cadences) + (1 if report.cadences else 0),
        0,
    )
    rows = []
    for index in range(max_len):
        prior_index = index - 1
        rows.append(
            [
                index + 1,
                _value_at(report.air_times, index),
                _value_at(report.contact_times, prior_index),
                _value_at(report.cycle_times, prior_index),
                _value_at(report.jump_heights, index),
                _value_at(report.cadences, prior_index),
                "",
                "",
                True,
                "",
                "",
            ]
        )
    return rows


def _value_at(values: tuple, index: int):
    return values[index] if 0 <= index < len(values) else ""


def _optional_excel_value(value):
    return value if value is not None else ""


def _fmt(value: float | None) -> str:
    """Format an optional float value for table display."""
    if value is None:
        return ""
    return f"{value:.3f}"


def _scaled_fmt(value: float | None, scale: float) -> str:
    if value is None:
        return ""
    return f"{value * scale:.3f}"


def _side_label(side: str) -> str:
    return {"left": "左脚", "right": "右脚", "unknown": "未知"}.get(side, side)


def _excel_cycle_value(value):
    return "N/A" if value is None else value


_STATISTICS_REASON_LABELS = {
    "Touch was replaced before lift": "重复触地前未检测到正常离地",
    "Missing same-side lift event": "缺少同侧离地事件",
    "Contact time below minimum threshold": "触地时间低于最小阈值",
    "Flight time outside acceptable range": "腾空时间不在允许范围",
    "Step length below minimum threshold": "步长低于最小阈值",
    "Excluded by automatic_data_filter": "被自动数据过滤排除",
}

_QUALITY_FLAG_LABELS = {
    "gap_below_minimum": "两脚间距低于最小阈值",
    "running_overlap_above_tolerance": "跑步时双脚重叠超过容差",
    "non_positive_stride_length": "步幅计算结果非正值",
}


def _statistics_note(
    is_included: bool,
    exclusion_reason: str | None,
    quality_flags: tuple[str, ...],
) -> str:
    parts = []
    if not is_included:
        parts.append(
            f"未纳入：{_statistics_reason_label(exclusion_reason)}"
        )
    if quality_flags:
        parts.append(f"质量提示：{_quality_flags_text(quality_flags)}")
    return "；".join(parts) or "—"


def _statistics_reason_label(reason: str | None) -> str:
    if reason is None:
        return "原因未知"
    return _STATISTICS_REASON_LABELS.get(reason, reason)


def _quality_flags_text(quality_flags: tuple[str, ...]) -> str:
    return "、".join(
        _QUALITY_FLAG_LABELS.get(flag, flag)
        for flag in quality_flags
    )


def _treadmill_metric_rows(report: TreadmillGaitReport | TreadmillRunningReport) -> list[list[object]]:
    """Extract key columns from per_step_results for Excel export and testing."""
    rows = []
    for step in report.per_step_results:
        rows.append(
            [
                step.index,
                step.side,
                step.row_status,
                step.is_event_valid,
                step.is_included_in_statistics,
                _excel_cycle_value(step.contact_time_s),
                _excel_cycle_value(step.flight_time_s),
                _excel_cycle_value(step.step_time_s),
                _excel_cycle_value(step.step_length_cm),
                _excel_cycle_value(step.gap_between_feet_cm),
                _excel_cycle_value(step.distance_cm),
                _excel_cycle_value(step.speed_m_s),
                step.correction_source,
                (
                    _statistics_reason_label(step.statistics_exclusion_reason)
                    if step.statistics_exclusion_reason is not None
                    else "N/A"
                ),
                _quality_flags_text(step.quality_flags) or "N/A",
                _excel_cycle_value(step.step_reference_cm),
            ]
        )
    return rows


def _gait_cycle_rows(report: TreadmillGaitReport | TreadmillRunningReport) -> list[list[object]]:
    rows = []
    for cycle in report.gait_cycles:
        row = [
            _excel_cycle_value(getattr(cycle, name))
            for name in GAIT_CYCLE_EXPORT_FIELDS
        ]
        row[0] = cycle.index + 1
        row[1] = _side_label(cycle.side)
        included_index = GAIT_CYCLE_EXPORT_FIELDS.index(
            "is_included_in_statistics"
        )
        exclusion_reason_index = GAIT_CYCLE_EXPORT_FIELDS.index(
            "statistics_exclusion_reason"
        )
        quality_flags_index = GAIT_CYCLE_EXPORT_FIELDS.index("quality_flags")
        row[included_index] = (
            "是" if cycle.is_included_in_statistics else "否"
        )
        if cycle.statistics_exclusion_reason is not None:
            row[exclusion_reason_index] = _statistics_reason_label(
                cycle.statistics_exclusion_reason
            )
        row[quality_flags_index] = (
            _quality_flags_text(cycle.quality_flags) or "N/A"
        )
        rows.append(row)
    return rows
