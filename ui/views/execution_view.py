"""
execution_view.py — 实时测试核心页

用 MetricCard 仪表盘替代 MTextEdit 纯文本滚动，
支持远距离可读（48pt 大字号）。

设计约束:
  - 不管理 QThread / UsbWorker / GaitEngine
  - 所有数据通过公共方法接收 (on_hop_event, on_gait_snapshot 等)
  - reset() 由 MainWindow 在切入前显式调用
"""

from __future__ import annotations

import importlib
from typing import Optional

from qtpy.QtCore import Signal, Qt, QTimer
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout,
    QLabel, QFrame, QSizePolicy, QProgressBar,
)

from dayu_widgets.label import MLabel
from dayu_widgets.push_button import MPushButton
from dayu_widgets import dayu_theme

from config.test_config import TestConfig
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.footprint_channel import FootprintChannelWidget
from ui.ground_track import GroundTrackPanel

# pyqtgraph 可选导入
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


# ======================================================================
#  MetricCard — 单个指标仪表盘卡片
# ======================================================================

class MetricCard(QFrame):
    """单个指标卡片: 标题(小字灰色) + 数值(大字高亮) + 单位(小字灰色)"""

    def __init__(self, title: str, unit: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "MetricCard {"
            "  background-color: rgba(40, 40, 45, 0.85);"
            "  border: 1px solid rgba(80, 80, 85, 0.6);"
            "  border-radius: 10px;"
            "  padding: 0;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        # 标题
        self._title = MLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet("font-size: 11pt; color: #888888; border: none; background: transparent;")
        layout.addWidget(self._title)

        # 数值
        self._value = MLabel("--")
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet(
            "font-size: 42pt; font-weight: bold; "
            "color: #f0f0f0; border: none; background: transparent;"
        )
        layout.addWidget(self._value)

        # 单位
        if unit:
            self._unit = MLabel(unit)
            self._unit.setAlignment(Qt.AlignCenter)
            self._unit.setStyleSheet("font-size: 11pt; color: #666666; border: none; background: transparent;")
            layout.addWidget(self._unit)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(max(120, self.minimumSizeHint().height() + 4))

    def set_value(self, text: str):
        self._value.setText(text)

    def set_color(self, color: str):
        """设置数值颜色"""
        self._value.setStyleSheet(
            f"font-size: 42pt; font-weight: bold; "
            f"color: {color}; border: none; background: transparent;"
        )


# ======================================================================
#  ExecutionView — 实时测试视图
# ======================================================================

class ExecutionView(QWidget):
    """实时测试核心页 — 仪表盘 + 图表 + 控制栏。"""

    start_requested = Signal()
    return_config_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    camera_requested = Signal(str)
    ground_layout_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # 当前配置
        self._config: Optional[TestConfig] = None
        self._mode: str = "纵跳"

        # 图表数据
        self._h_x, self._h_y = [], []
        self._cadence_x, self._cadence_y = [], []
        self._initial_range = 10
        self._slide_window = 15

        # 实时统计 (从事件中累积)
        self._max_h = 0.0
        self._latest_h = 0.0
        self._latest_cadence = 0.0
        self._touch_count = 0

        # 纵跳事件辅助
        self._last_strike_centroid = None

        # 进度
        self._jump_target: Optional[int] = None
        self._countdown_remaining = 0
        self._countdown_timer: Optional[QTimer] = None
        self._camera_start_timer = QTimer(self)
        self._camera_start_timer.setSingleShot(True)
        self._camera_start_timer.timeout.connect(
            self._start_camera_preview_if_visible
        )

        # 暂停状态
        self._paused = False
        self._device_state = "disconnected"
        self._detected_segments = None
        self._latest_footprint_frame = None

        self._build_ui()
        self._apply_style()

    # ------------------------------------------------------------------
    #  UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        self._page_layout = QHBoxLayout(self)
        self._page_layout.setContentsMargins(0, 0, 0, 0)
        self._page_layout.setSpacing(0)
        self._body = QWidget()
        self._page_layout.addWidget(self._body, 1)
        main_layout = QVBoxLayout(self._body)
        self._main_layout = main_layout
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(10)

        # ===== 顶部状态栏 =====
        top_bar = QHBoxLayout()
        self._mode_label = MLabel("纵跳测试 · 实时")
        self._mode_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #e0e0e0;")
        top_bar.addWidget(self._mode_label)
        top_bar.addStretch()

        # 设备状态
        self._device_label = MLabel("等待连接...")
        self._device_label.setStyleSheet("font-size: 10pt; color: #888888;")
        top_bar.addWidget(self._device_label)

        # 相机按钮组 (三个独立按钮, 各对应固定相机实现)
        self.btn_logi_camera = MPushButton("📷 MX Brio")
        self.btn_logi_camera.setFixedHeight(36)
        self.btn_logi_camera.setStyleSheet(
            "font-size: 11pt; padding: 4px 12px; "
            "background-color: #424242; border: 1px solid #555; border-radius: 6px;"
        )
        self.btn_logi_camera.clicked.connect(lambda: self._select_camera("logi"))
        top_bar.addWidget(self.btn_logi_camera)

        self.btn_tinyse_camera = MPushButton("🤖 Tiny SE")
        self.btn_tinyse_camera.setFixedHeight(36)
        self.btn_tinyse_camera.setStyleSheet(
            "font-size: 11pt; padding: 4px 12px; "
            "background-color: #424242; border: 1px solid #555; border-radius: 6px;"
        )
        self.btn_tinyse_camera.clicked.connect(lambda: self._select_camera("tinyse"))
        self.btn_tinyse_camera.setToolTip("OBSBOT Tiny SE (100fps)")
        top_bar.addWidget(self.btn_tinyse_camera)

        self.btn_basic_camera = MPushButton("👁 预览")
        self.btn_basic_camera.setFixedHeight(36)
        self.btn_basic_camera.setStyleSheet(
            "font-size: 11pt; padding: 4px 12px; "
            "background-color: #424242; border: 1px solid #555; border-radius: 6px;"
        )
        self.btn_basic_camera.clicked.connect(lambda: self._select_camera("basic"))
        top_bar.addWidget(self.btn_basic_camera)

        main_layout.addLayout(top_bar)

        # ===== 仪表盘卡片区 =====
        self._cards_layout = QHBoxLayout()
        self._cards_layout.setSpacing(12)

        # 纵跳模式 4 卡片
        self._card_count = MetricCard("跳跃次数")
        self._card_current = MetricCard("当前跳高", "m")
        self._card_max = MetricCard("最大跳高", "m")
        self._card_cadence = MetricCard("实时步频", "spm")

        self._jump_cards = [self._card_count, self._card_current, self._card_max, self._card_cadence]
        for card in self._jump_cards:
            self._cards_layout.addWidget(card)

        # 步态模式 4 卡片 (初始隐藏)
        self._card_steps = MetricCard("步数")
        self._card_stride = MetricCard("最新步长", "cm")
        self._card_velocity = MetricCard("平均步速", "cm/s")
        self._card_imbalance = MetricCard("不平衡指数", "%")

        self._gait_cards = [self._card_steps, self._card_stride, self._card_velocity, self._card_imbalance]
        for card in self._gait_cards:
            self._cards_layout.addWidget(card)
            card.hide()

        main_layout.addLayout(self._cards_layout)
        self._ground_status = QLabel("等待完整数据帧，识别设备段数")
        self._ground_status.setWordWrap(True)
        self._ground_status.setStyleSheet("color: #aeb7c5; font-size: 11pt; border: none;")
        self._ground_status.hide()
        main_layout.addWidget(self._ground_status)

        # ===== 图表区 =====
        charts_layout = QHBoxLayout()
        charts_layout.setSpacing(10)

        if _PG_AVAILABLE:
            self._plot_h = pg.PlotWidget()
            self._plot_h.setBackground(dayu_theme.background_in_color)
            self._plot_h.showGrid(x=True, y=True, alpha=0.1)
            self._plot_h.setLabel('left', '跳高 h (m)')
            self._plot_h.setLabel('bottom', '跳跃次数')
            self._plot_h.enableAutoRange(axis='y')
            self._plot_h.setXRange(0, 10, padding=0)
            self._h_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self._plot_h.addItem(self._h_bar)
            charts_layout.addWidget(self._plot_h, 1)

            self._plot_cadence = pg.PlotWidget()
            self._plot_cadence.setBackground(dayu_theme.background_in_color)
            self._plot_cadence.showGrid(x=True, y=True, alpha=0.1)
            self._plot_cadence.setLabel('left', '步频 (步/分钟)')
            self._plot_cadence.setLabel('bottom', '跳跃次数')
            self._plot_cadence.enableAutoRange(axis='y')
            self._plot_cadence.setXRange(0, 10, padding=0)
            self._cadence_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush='#52c41a')
            self._plot_cadence.addItem(self._cadence_bar)
            charts_layout.addWidget(self._plot_cadence, 1)
            self._plot_cadence.hide()
        else:
            placeholder = QLabel("未安装 pyqtgraph — 图表不可用")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("font-size: 14pt; color: #666;")
            charts_layout.addWidget(placeholder)

        self._chart_container = QWidget()
        self._chart_container.setLayout(charts_layout)

        self._lower_split = QWidget()
        lower_layout = QGridLayout(self._lower_split)
        self._lower_layout = lower_layout
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(10)
        lower_layout.setColumnStretch(0, 3)
        lower_layout.setColumnStretch(2, 1)
        lower_layout.setRowStretch(0, 1)

        self._cycle_panel = QFrame()
        self._cycle_panel.setObjectName("CurrentCyclePanel")
        self._cycle_panel.setFixedHeight(72)
        self._cycle_panel.setStyleSheet(
            "QFrame#CurrentCyclePanel {"
            "  background-color: rgba(18, 18, 22, 0.92);"
            "  border: 1px solid rgba(90, 90, 95, 0.7);"
            "  border-radius: 8px;"
            "}"
        )
        cycle_layout = QHBoxLayout(self._cycle_panel)
        cycle_layout.setContentsMargins(14, 4, 14, 4)
        cycle_layout.setSpacing(14)

        state_layout = QVBoxLayout()
        state_layout.setContentsMargins(0, 0, 0, 0)
        state_layout.setSpacing(0)
        self._current_cycle_title = MLabel("当前周期")
        self._current_cycle_title.setStyleSheet(
            "font-size: 9pt; color: #ff9b3d; border: none; background: transparent;"
        )
        self._current_cycle_state = MLabel("等待触地事件")
        self._current_cycle_state.setStyleSheet(
            "font-size: 18pt; font-weight: bold; color: #f0f3f8; "
            "border: none; background: transparent;"
        )
        state_layout.addWidget(self._current_cycle_title)
        state_layout.addWidget(self._current_cycle_state)
        cycle_layout.addLayout(state_layout, 1)

        self._left_cycle_value = MLabel("左脚  --")
        self._left_cycle_value.setAlignment(Qt.AlignCenter)
        self._left_cycle_value.setStyleSheet(
            "font-size: 14pt; color: #d9dee8; border: none; background: transparent;"
        )
        cycle_layout.addWidget(self._left_cycle_value, 1)

        self._right_cycle_value = MLabel("右脚  --")
        self._right_cycle_value.setAlignment(Qt.AlignCenter)
        self._right_cycle_value.setStyleSheet(
            "font-size: 14pt; color: #d9dee8; border: none; background: transparent;"
        )
        cycle_layout.addWidget(self._right_cycle_value, 1)
        self._cycle_panel.hide()

        self._camera_panel = EmbeddedCameraPanel()
        self._camera_panel.playback_layout_changed.connect(
            self._update_cycle_panel_visibility
        )
        self._camera_column = QWidget()
        camera_layout = QVBoxLayout(self._camera_column)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(10)
        camera_layout.addWidget(self._camera_panel, 1)
        camera_layout.addWidget(self._cycle_panel)
        lower_layout.addWidget(self._camera_column, 0, 0, 2, 1)

        self._footprint_channel = FootprintChannelWidget()
        lower_layout.addWidget(self._footprint_channel, 0, 2)
        self._footprint_channel.hide()
        lower_layout.addWidget(self._chart_container, 0, 2)
        self._chart_container.hide()
        self._lower_split.hide()
        main_layout.addWidget(self._lower_split, 1)

        # ===== 进度条 =====
        self._progress_container = QFrame()
        progress_layout = QGridLayout(self._progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(0)

        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("")
        self._progress_bar.setValue(0)
        self._progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._progress_bar.setStyleSheet(
            "QProgressBar {"
            "  background-color: rgba(40, 40, 45, 0.8);"
            "  border: 1px solid #444;"
            "  border-radius: 6px;"
            "  text-align: center;"
            "  color: #e0e0e0;"
            "  font-size: 11pt;"
            "}"
            "QProgressBar::chunk {"
            "  background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "    stop:0 #1890ff, stop:1 #36cfc9);"
            "  border-radius: 5px;"
            "}"
        )
        progress_layout.addWidget(self._progress_bar, 0, 0)

        self._progress_overlay = QWidget()
        self._progress_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._progress_overlay.setStyleSheet("background: transparent;")
        self._progress_overlay.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        overlay_layout = QVBoxLayout(self._progress_overlay)
        overlay_layout.setContentsMargins(4, 8, 4, 8)
        overlay_layout.addStretch()
        self._progress_title = MLabel("剩余")
        self._progress_title.setAlignment(Qt.AlignCenter)
        self._progress_title.setStyleSheet(
            "font-size: 10pt; color: #e0e0e0; background: transparent; border: none;"
        )
        overlay_layout.addWidget(self._progress_title)
        self._progress_value = MLabel("--:--")
        self._progress_value.setAlignment(Qt.AlignCenter)
        self._progress_value.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #ffffff; "
            "background: transparent; border: none;"
        )
        overlay_layout.addWidget(self._progress_value)
        overlay_layout.addStretch()
        progress_layout.addWidget(self._progress_overlay, 0, 0)
        self._progress_overlay.hide()
        self._progress_container.setFixedHeight(28)
        self._progress_container.hide()
        main_layout.addWidget(self._progress_container)

        # ===== 控制按钮栏 =====
        self._controls_container = QWidget()
        self._controls_layout = QBoxLayout(
            QBoxLayout.LeftToRight, self._controls_container
        )
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_layout.setSpacing(12)

        self.btn_return_config = MPushButton("返回配置")
        self.btn_return_config.setMinimumHeight(50)
        self.btn_return_config.setMinimumWidth(120)
        self.btn_return_config.setStyleSheet(
            "background: #1a2230; border: 1px solid #354151;"
            "border-radius: 8px; color: #d9dee8; font-size: 13pt;"
        )
        self.btn_return_config.clicked.connect(self.return_config_requested)
        self._controls_layout.addWidget(self.btn_return_config)

        self.btn_start = MPushButton("▶ 开始采集").primary()
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet(
            "QPushButton {"
            "  background: #ff7a00;"
            "  border: 1px solid #ff7a00;"
            "  border-radius: 8px;"
            "  color: white;"
            "  font-size: 16pt;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover { background: #ff8a1f; }"
            "QPushButton:disabled {"
            "  background: #252d38;"
            "  border-color: #303a47;"
            "  color: #768294;"
            "}"
        )
        self.btn_start.clicked.connect(self._on_start)
        self._controls_layout.addWidget(self.btn_start, 1)

        self.btn_pause = MPushButton("⏸ 暂停")
        self.btn_pause.setMinimumHeight(50)
        self.btn_pause.setStyleSheet(
            "background: #1a2230; border: 1px solid #354151;"
            "border-radius: 8px; color: #e7ebf2; font-size: 14pt;"
        )
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_pause.hide()
        self._controls_layout.addWidget(self.btn_pause)

        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet(
            "background: #402226; border: 1px solid #704047;"
            "border-radius: 8px; color: #ffb2b2; font-size: 14pt;"
        )
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.hide()
        self._controls_layout.addWidget(self.btn_stop)

        main_layout.addWidget(self._controls_container)
        self._ground_track = GroundTrackPanel()
        self._page_layout.addWidget(self._ground_track)
        self._ground_track.hide()
        lower_layout.addWidget(self._ground_track.detail, 0, 2)

    @property
    def is_ground(self):
        return getattr(self._config, "test_type", "") in {"Sprint and Gait Test", "Overground Running Test"}

    def _apply_style(self):
        self.setStyleSheet(
            "QWidget { font-family: 'Microsoft YaHei UI', sans-serif; }"
        )

    # ------------------------------------------------------------------
    #  公共接口 (被 MainWindow / SessionController 调用)
    # ------------------------------------------------------------------

    def configure(self, config: TestConfig):
        """切入本视图前调用，初始化仪表盘标签和图表轴。"""
        self._config = config
        self._mode = "纵跳" if config.test_type == "Jump Test" else "步态分析"

        # 切换模式标签
        mode_text = "纵跳测试" if self._mode == "纵跳" else "步态分析"
        self._mode_label.setText(f"{mode_text} · 就绪")

        # 切换卡片可见性
        is_jump = self._mode == "纵跳"
        is_treadmill = config.test_type in (
            "Treadmill Gait Test",
            "Treadmill Running Test",
        )
        self._arrange_execution_area(is_jump)
        self._camera_panel.set_integrated_style(self.is_ground)
        self._ground_track.setVisible(self.is_ground)
        self._ground_track.detail.setVisible(self.is_ground)
        self._ground_status.setVisible(self.is_ground)
        self._device_label.setVisible(not self.is_ground)
        for c in self._jump_cards:
            c.setVisible(is_jump)
        for c in self._gait_cards:
            c.setVisible(not is_jump)
        self._chart_container.setVisible(is_jump)
        self._lower_split.show()
        self._footprint_channel.setVisible(not is_jump and not self.is_ground)
        self._cycle_panel.hide()
        self._card_imbalance._title.setText(
            "有效周期" if self.is_ground else "步态周期不对称率" if is_treadmill else "不平衡指数"
        )
        self._card_imbalance._unit.setText("个" if self.is_ground else "%")
        self._card_steps._title.setText("有效步数" if self.is_ground else "步数")
        self._footprint_channel.set_direction(getattr(config, "direction", None))
        self._camera_start_timer.start(0)
        if is_treadmill:
            QTimer.singleShot(0, self._update_cycle_panel_visibility)

        # 切换图表标签
        if _PG_AVAILABLE:
            if is_jump:
                self._plot_h.setLabel('left', '跳高 h (m)')
                self._plot_h.setLabel('bottom', '跳跃次数')
                self._plot_cadence.setLabel('left', '步频 (步/分钟)')
                self._plot_cadence.setLabel('bottom', '跳跃次数')
            else:
                self._plot_h.setLabel('left', '步长 (cm)')
                self._plot_h.setLabel('bottom', '步数')
                self._plot_cadence.setLabel('left', '步速 (cm/s)')
                self._plot_cadence.setLabel('bottom', '步数')

        # 初始化进度
        self._init_progress(config)

        # 按钮状态: 显示"开始"
        self.btn_start.show()
        self.btn_return_config.show()
        self.btn_start.setText("开始采集")
        self.btn_start.setEnabled(False)
        self.btn_pause.hide()
        self.btn_stop.hide()
        self._device_state = "connecting"
        self._device_label.setText("● 正在连接设备...")
        self._ground_status.setText("等待完整数据帧，识别设备段数")
        if self.is_ground:
            self._mode_label.setText(("地面跑步" if config.test_type == "Overground Running Test" else "地面走路") + " · 准备测试")
        self.ground_layout_changed.emit()

    def _update_cycle_panel_visibility(self):
        is_treadmill = self._config is not None and self._config.test_type in (
            "Treadmill Gait Test",
            "Treadmill Running Test",
        )
        if not is_treadmill or not self._lower_split.isVisible():
            self._cycle_panel.hide()
            return

        camera_layout = self._camera_column.layout()
        camera_margins = camera_layout.contentsMargins()
        panel_layout = self._camera_panel.layout()
        panel_margins = panel_layout.contentsMargins()
        panel_contents = self._camera_panel.contentsRect()
        frame_height = self._camera_panel.height() - panel_contents.height()
        preview_width = max(
            0,
            panel_contents.width()
            - panel_margins.left()
            - panel_margins.right(),
        )
        maximum_preview_height = (preview_width // 16) * 9
        camera_outer_height = (
            maximum_preview_height
            + self._camera_panel.playback_controls_height()
            + frame_height
            + panel_margins.top()
            + panel_margins.bottom()
        )
        required_height = (
            camera_margins.top()
            + camera_outer_height
            + camera_layout.spacing()
            + self._cycle_panel.height()
            + camera_margins.bottom()
        )
        self._cycle_panel.setVisible(
            self._camera_column.height() >= required_height
        )

    def _start_camera_preview_if_visible(self):
        if self.isVisible() and self._lower_split.isVisible():
            self._camera_panel.start_preview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mode != "纵跳":
            QTimer.singleShot(0, self._update_cycle_panel_visibility)

    def on_device_state(self, state: str, message: str):
        """Update acquisition controls from the structured device state."""
        self._device_state = state
        labels = {
            "disconnected": ("● 设备未连接", "#8f9bad"),
            "connecting": ("● 正在连接设备...", "#f0a24a"),
            "connected": ("● 设备已连接", "#7ecf68"),
            "streaming": ("● 正在采集", "#7ecf68"),
            "error": (f"● {message}", "#f06a6a"),
        }
        text, color = labels.get(state, (message or state, "#8f9bad"))
        self._device_label.setText(text)
        self._device_label.setToolTip(message)
        self._device_label.setStyleSheet(f"font-size: 10pt; color: {color};")
        if self.is_ground and state in {"connecting", "disconnected", "error"}:
            self._ground_status.setText(message or text)
        if state == "connected":
            self.btn_start.setText("开始采集")
            self.btn_start.setEnabled(getattr(self._config, "test_type", "") not in {"Sprint and Gait Test", "Overground Running Test"})
            if getattr(self, "_quality_preflight_required", False):
                self.btn_start.setText("等待自检通过")
                self.btn_start.setEnabled(False)
        elif state == "error":
            self.btn_start.setText("重试设备")
            self.btn_start.setEnabled(True)
            self.btn_start.show()
            self.btn_pause.hide()
            self.btn_stop.hide()
        elif state in {"disconnected", "connecting"}:
            self.btn_start.setText("开始采集")
            self.btn_start.setEnabled(False)
        if not self.is_ground and self._detected_segments and self._detected_segments > 1:
            self._show_unsupported_layout()

    def on_device_layout(self, layout):
        self._detected_segments = len(layout.segments) if layout is not None else None
        if not self.is_ground and self._detected_segments and self._detected_segments > 1:
            self._show_unsupported_layout()
        elif not self.is_ground and self._device_state == "connected":
            required = getattr(self, "_quality_preflight_required", False)
            self.btn_start.setText("等待自检通过" if required else "开始采集")
            self.btn_start.setEnabled(not required)

    def set_quality_preflight_required(self, required):
        self._quality_preflight_required = required
        if required:
            self.btn_start.setText("等待自检通过")
            self.btn_start.setEnabled(False)

    def _show_unsupported_layout(self):
        self._device_label.setText(f"已识别 {self._detected_segments} 段；当前模式仅支持单段设备")
        self.btn_start.setText("请连接单段设备或更换模式")
        self.btn_start.setEnabled(False)

    def on_walking_readiness(self, result):
        count = result.get("segment_count")
        prefix = f"{count} 段 / 标称 {count} 米 · " if count else ""
        self._device_label.setText(prefix + result["message"])
        details = result.get("details", "")
        self._device_label.setToolTip(details or result["message"])
        if self.is_ground:
            self._ground_status.setText(prefix + result["message"] + ("\n" + details if details else ""))
            self._ground_status.setToolTip(details or result["message"])
        ready_text = f"确认共 {count} 段并开始" if self.is_ground else "开始采集"
        if result.get("requires_acknowledgement"):
            ready_text = "核对异常并降级开始"
        self.btn_start.setText(ready_text if result["ready"] else "等待自检通过")
        self.btn_start.setEnabled(result["ready"])
        if self.is_ground and result.get("visual_frame"):
            self._ground_track.render_state(result["visual_frame"])

    def on_beam_quality_notice(self, notice):
        self._quality_warning = "设备质量提示：" + notice["impact"]
        self._device_label.setText(self._quality_warning)
        self._device_label.setStyleSheet("color: #ffb347;")
        self._device_label.setToolTip(str(notice))

    def on_session_started(self):
        """Enter the running UI only after the device confirms streaming."""
        label = "纵跳测试" if self._mode == "纵跳" else "步态分析"
        if getattr(self._config, "test_type", "") == "Overground Running Test":
            label = "地面跑步"
        elif self.is_ground:
            label = "地面走路"
        self._mode_label.setText(f"{label} · 运行中")
        self.btn_start.hide()
        self.btn_return_config.hide()
        self.btn_pause.setVisible(getattr(self._config, "test_type", "") not in {"Sprint and Gait Test", "Overground Running Test"})
        self.btn_stop.show()
        self._start_countdown()

    def set_tinyse_available(self, available: bool):
        """由 MainWindow 调用, 更新 Tiny SE 按钮提示."""
        if available:
            self.btn_tinyse_camera.setToolTip("OBSBOT Tiny SE (已检测到)")
        else:
            self.btn_tinyse_camera.setToolTip("OBSBOT Tiny SE (未检测到，点击可重试)")

    def _select_camera(self, camera_type: str):
        if camera_type == "basic":
            if self._lower_split.isVisible():
                self._camera_panel.start_preview()
            return
        self._camera_panel.set_camera_type(camera_type)
        if self._lower_split.isVisible():
            self._camera_panel.start_preview()

    def reset(self):
        """重置所有仪表盘和图表到初始状态。"""
        self._quality_warning = None
        # 仪表盘
        for card in self._jump_cards + self._gait_cards:
            card.set_value("--")
            card.set_color("#f0f0f0")

        # 图表数据
        self._h_x, self._h_y = [], []
        self._cadence_x, self._cadence_y = [], []
        if _PG_AVAILABLE:
            self._h_bar.setOpts(x=[], height=[])
            self._cadence_bar.setOpts(x=[], height=[])
            self._plot_h.setXRange(0, self._initial_range, padding=0)
            self._plot_cadence.setXRange(0, self._initial_range, padding=0)
        if hasattr(self, "_footprint_channel"):
            self._footprint_channel.clear()
            self._ground_track.clear()
        if hasattr(self, "_cycle_panel"):
            self._current_cycle_state.setText("等待触地事件")
            self._left_cycle_value.setText("左脚  --")
            self._right_cycle_value.setText("右脚  --")
        if hasattr(self, "_camera_panel"):
            self._camera_start_timer.stop()
            self._camera_panel.shutdown()

        # 实时统计
        self._max_h = 0.0
        self._latest_h = 0.0
        self._latest_cadence = 0.0
        self._touch_count = 0
        self._last_strike_centroid = None
        self._paused = False
        self._latest_footprint_frame = None

        # 进度
        self._stop_countdown()
        self._set_progress_visible(False)
        self._progress_bar.setValue(0)

    def on_hop_event(self, ev):
        """接收纵跳事件，更新仪表盘 + 图表。"""
        air_time = getattr(ev, '_air_time', None)
        if ev.kind.lower() == "touch" and air_time is not None:
            h = ev._hop_height
            contact_time = getattr(ev, '_contact_time', None)

            # 更新统计
            self._touch_count += 1
            self._latest_h = h
            if h > self._max_h:
                self._max_h = h

            # 计算步频
            if contact_time is not None and contact_time > 0:
                cadence = 60.0 / (air_time + contact_time)
            else:
                cadence = 60.0 / air_time if air_time > 0 else 0
            self._latest_cadence = cadence

            # 更新仪表盘
            target_str = f"/{self._jump_target}" if self._jump_target else ""
            self._card_count.set_value(f"{self._touch_count}{target_str}")
            self._card_current.set_value(f"{h:.3f}")
            self._card_max.set_value(f"{self._max_h:.3f}")
            self._card_max.set_color(dayu_theme.primary_color)
            self._card_cadence.set_value(f"{cadence:.0f}")

            # 更新图表
            self._update_charts(h, cadence)

            # 更新进度
            self._update_jump_progress()

        # 记录质心
        if ev.kind.lower() == "touch" and ev.centroid_cm:
            self._last_strike_centroid = ev.centroid_cm

    def on_jump_quality_notice(self, notice: dict):
        """显示不计入触地/跳跃的质量提示。"""
        if notice.get("kind") == "contact_cluster_above_limit":
            length = notice.get("cluster_length", "?")
            self._device_label.setText(f"⚠ 遮挡范围超过触地上限（{length}列）")

    def on_gait_step_event(self, ev):
        """接收步态事件。足迹通道替代了步态柱状图。"""
        return

    def on_gait_snapshot(self, snapshot: dict):
        """接收步态快照 (~10Hz)，更新仪表盘。"""
        self._card_steps.set_value(str(snapshot['touch_count']))
        if "walking" in snapshot or "running" in snapshot:
            self._mode_label.setText(("地面跑步" if "running" in snapshot else "地面走路") + " · " + snapshot["status"])
            data = snapshot.get("running", snapshot.get("walking"))
            self._device_label.setText(f"{data['segment_count']} 段 / 标称 {data['nominal_length_m']} 米 · 有效步数 {data['valid_steps']} · 异常 {len(data['issues'])}")
            self._ground_status.setText(self._device_label.text())
            if data["issues"]:
                self._ground_status.setText(self._ground_status.text() + " · 采集存在异常，详见报告")
            self._ground_track.set_summary(data)
            self._card_steps.set_value(str(data["valid_steps"]))
            self._card_imbalance.set_value(str(data["valid_cycles"]))
            self._card_stride.set_value(f"{snapshot['latest_stride']:.1f}" if snapshot.get("stride_count") else "--")
            self._card_velocity.set_value(f"{snapshot['velocity_sum'] / snapshot['velocity_count']:.1f}" if snapshot.get("velocity_count") else "--")
            return

        if snapshot.get("stride_count", 0) > 0:
            latest = snapshot.get("latest_stride", 0)
            self._card_stride.set_value(f"{latest:.1f}")

        if snapshot.get("velocity_count", 0) > 0:
            avg_vel = snapshot["velocity_sum"] / snapshot["velocity_count"]
            self._card_velocity.set_value(f"{avg_vel:.1f}")

        is_treadmill = self._config is not None and self._config.test_type in (
            "Treadmill Gait Test",
            "Treadmill Running Test",
        )
        if is_treadmill:
            asymmetry = snapshot.get("gait_cycle_asymmetry_percent", {})
            value = asymmetry.get("gait_cycle_s")
            self._card_imbalance.set_value(
                f"{value:.1f}" if value is not None else "N/A"
            )
        else:
            em = snapshot.get("latest_extra_metrics", {})
            if em and em.get("imbalance_index") is not None:
                self._card_imbalance.set_value(f"{em['imbalance_index']:.1f}")

        cycle_state = snapshot.get("gait_cycle_state")
        if cycle_state:
            self._render_gait_cycle_state(cycle_state)

    def _render_gait_cycle_state(self, state: dict):
        current = state.get("current_cycles", {})
        support_state = state.get("support_state") or "等待触地事件"
        self._current_cycle_state.setText(support_state)

        def phase_text(side: str, label: str) -> str:
            value = current.get(side)
            if not value:
                return f"{label}  --"
            phase = value.get("phase") or "--"
            elapsed = value.get("elapsed_s")
            elapsed_text = f"{elapsed:.3f} s" if elapsed is not None else "--"
            return f"{label}  {phase} {elapsed_text}"

        self._left_cycle_value.setText(phase_text("left", "左脚"))
        self._right_cycle_value.setText(phase_text("right", "右脚"))

    def on_footprint_visual_frame(self, frame: dict):
        self._latest_footprint_frame = frame
        if self.is_ground:
            self._ground_track.render_state(frame)
            return
        if self._mode != "纵跳":
            self._footprint_channel.render_state(frame)

    def on_device_message(self, msg: str):
        """显示设备状态。"""
        if getattr(self, "_quality_warning", None):
            self._device_label.setText(self._quality_warning)
            return
        if not self.is_ground and self._detected_segments and self._detected_segments > 1:
            self._show_unsupported_layout()
            return
        if getattr(self._config, "test_type", "") not in {"Sprint and Gait Test", "Overground Running Test"}:
            self._device_label.setText(msg[:50])

    # ------------------------------------------------------------------
    #  图表更新 (从 data_show.py 迁移)
    # ------------------------------------------------------------------

    def _update_charts(self, val1: float, val2: float):
        """更新两个柱状图。"""
        if not _PG_AVAILABLE:
            return

        self._h_x.append(len(self._h_x) + 1)
        self._h_y.append(val1)
        self._cadence_x.append(len(self._cadence_x) + 1)
        self._cadence_y.append(val2)

        # 滑动窗口
        sw = self._slide_window
        dh_x = self._h_x[-sw:] if len(self._h_x) > sw else self._h_x
        dh_y = self._h_y[-sw:] if len(self._h_y) > sw else self._h_y
        dc_x = self._cadence_x[-sw:] if len(self._cadence_x) > sw else self._cadence_x
        dc_y = self._cadence_y[-sw:] if len(self._cadence_y) > sw else self._cadence_y

        self._h_bar.setOpts(x=dh_x, height=dh_y, width=0.65, brush=dayu_theme.primary_color)
        self._cadence_bar.setOpts(x=dc_x, height=dc_y, width=0.65, brush='#52c41a')

        # X 轴范围
        idx = len(self._h_x)
        if idx <= self._initial_range:
            self._plot_h.setXRange(0, self._initial_range, padding=0)
            self._plot_cadence.setXRange(0, self._initial_range, padding=0)
        else:
            x_max = idx + 0.5
            x_min = max(0, idx - sw + 0.5)
            self._plot_h.setXRange(x_min, x_max, padding=0)
            self._plot_cadence.setXRange(x_min, x_max, padding=0)

    # ------------------------------------------------------------------
    #  进度显示
    # ------------------------------------------------------------------

    def _arrange_execution_area(self, is_jump: bool):
        if self.is_ground:
            self._lower_layout.removeWidget(self._controls_container)
            self._main_layout.addWidget(self._controls_container)
            self._controls_layout.setDirection(QBoxLayout.LeftToRight)
            self._controls_layout.setSpacing(12)
            self._controls_layout.setAlignment(Qt.AlignRight)
            self.btn_stop.setMinimumWidth(120)
            self.btn_stop.setMaximumWidth(180)
            self.btn_start.setMaximumWidth(360)
            self._controls_container.setMaximumWidth(520)
            self._main_layout.setAlignment(self._controls_container, Qt.AlignRight)
            return
        self._controls_layout.setAlignment(Qt.Alignment())
        self.btn_stop.setMaximumWidth(16777215)
        self.btn_start.setMaximumWidth(16777215)
        self._controls_container.setMaximumWidth(16777215)
        self._main_layout.removeWidget(self._progress_container)
        self._main_layout.removeWidget(self._controls_container)
        self._lower_layout.addWidget(self._progress_container, 0, 1, 2, 1)
        self._lower_layout.addWidget(self._controls_container, 1, 2)
        self._progress_container.setFixedWidth(72)
        self._progress_container.setMinimumHeight(0)
        self._progress_container.setMaximumHeight(16777215)
        self._progress_bar.setOrientation(Qt.Vertical)
        self._progress_bar.setTextVisible(False)
        self._progress_overlay.show()
        self._controls_layout.setDirection(QBoxLayout.TopToBottom)
        self._controls_layout.setSpacing(8)

    def _set_progress_visible(self, visible: bool):
        self._progress_container.setVisible(visible)

    def _set_progress_text(self, text: str):
        self._progress_bar.setFormat(text)
        if text.startswith("剩余 "):
            self._progress_title.setText("剩余")
            self._progress_value.setText(text.removeprefix("剩余 "))
        elif text == "时间到":
            self._progress_title.setText("时间")
            self._progress_value.setText("到")
        else:
            self._progress_title.setText("进度")
            self._progress_value.setText(text.removesuffix(" 跳"))

    def _init_progress(self, config: TestConfig):
        """初始化进度条。"""
        self._stop_countdown()
        self._jump_target = None

        if config.stop_type == "Status change" and getattr(config, "number_of_jumps", None):
            self._jump_target = config.number_of_jumps
            self._progress_bar.setMaximum(self._jump_target)
            self._progress_bar.setValue(0)
            self._set_progress_text(f"0 / {self._jump_target} 跳")
            self._set_progress_visible(True)
        elif config.stop_type == "End of Time" and config.test_length:
            total = config.get_test_length_seconds() or 0
            self._countdown_remaining = total
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(total)
            mm, ss = divmod(total, 60)
            self._set_progress_text(f"剩余 {mm:02d}:{ss:02d}")
            self._set_progress_visible(True)
        else:
            self._set_progress_visible(False)

    def _start_countdown(self):
        """启动倒计时定时器（在"开始采集"后调用）。"""
        if (
            not self._paused
            and self._countdown_remaining > 0
            and self._countdown_timer is None
        ):
            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._on_countdown_tick)
            self._countdown_timer.start(1000)

    def _on_countdown_tick(self):
        if self._paused:
            return
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._stop_countdown()
            self._set_progress_text("时间到")
            self._progress_bar.setValue(0)
        else:
            mm, ss = divmod(self._countdown_remaining, 60)
            self._set_progress_text(f"剩余 {mm:02d}:{ss:02d}")
            total = self._progress_bar.maximum()
            self._progress_bar.setValue(self._countdown_remaining)

    def _update_jump_progress(self):
        if self._jump_target is None:
            return
        self._progress_bar.setValue(self._touch_count)
        self._set_progress_text(f"{self._touch_count} / {self._jump_target} 跳")

    def _stop_countdown(self):
        if self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None

    # ------------------------------------------------------------------
    #  按钮事件
    # ------------------------------------------------------------------

    def _on_start(self):
        if self._device_state == "error":
            self._device_label.setText("● 正在重新连接设备...")
            self.btn_start.setText("正在重连…")
        else:
            self._mode_label.setText(
                f"{'纵跳测试' if self._mode == '纵跳' else '步态分析'} · 正在启动"
            )
            self.btn_start.setText("正在启动…")
        self.btn_start.setEnabled(False)
        self.start_requested.emit()

    def _on_pause(self):
        self.pause_requested.emit()

    def set_paused(self, paused: bool):
        """Reflect the engine acknowledgement for both buttons and voice commands."""
        if paused == self._paused:
            return
        if paused:
            self._paused = True
            self._stop_countdown()
            self.btn_pause.setText("▶ 继续分析")
            self._mode_label.setText(
                f"{'纵跳测试' if self._mode == '纵跳' else '步态分析'}"
                " · 暂停分析（计时已暂停）"
            )
        else:
            self._paused = False
            self._start_countdown()
            self.btn_pause.setText("⏸ 暂停")
            self._mode_label.setText(
                f"{'纵跳测试' if self._mode == '纵跳' else '步态分析'} · 运行中"
            )

    def _on_stop(self):
        self._stop_countdown()
        self.stop_requested.emit()
