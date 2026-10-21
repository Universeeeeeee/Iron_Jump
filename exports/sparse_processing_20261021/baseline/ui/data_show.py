"""
2data_show.py - 实时步态分析前端

完全复用 1data_show.py 的计算方案:
- 使用 SingleFootDetector.consume() 进行流式事件检测
- 使用相同的跳高/步频公式
- 数据源从 NPZ 文件变为 USB 实时采集
"""
from __future__ import annotations

import importlib
import os
import time


from openpyxl import Workbook

from qtpy import QtWidgets
from qtpy.QtCore import QThread, Qt
from qtpy.QtGui import QTextCursor, QTextBlockFormat
from dayu_widgets.divider import MDivider
from dayu_widgets.push_button import MPushButton
from dayu_widgets.text_edit import MTextEdit
from dayu_widgets import dayu_theme
from dayu_widgets.qt import application

# 导入 UsbWorker 和算法引擎
from hardware.usb_worker import UsbWorker
from engine.gait_engine import GaitEngine
from config.test_config import TestConfig, default_jump_config
from ui.param_panel import ParamPanel
from .camera import Camera

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

G = 9.81  # 重力加速度

# 路径工具（兼容开发环境和 PyInstaller 打包环境）
from path_utils import get_base_dir as _get_base_dir, find_dll as _find_dll


class RealTimeGaitWidget(QtWidgets.QWidget):
    """
    实时步态分析界面。
    
    完全复用 1data_show.py 的计算方案:
    - SingleFootDetector.consume(frame) 进行流式事件检测
    - 相同的跳高公式: h = 0.5 * G * (air_time / 2) ** 2
    - 相同的步频公式: cadence = 60 / (air_time + contact_time)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paused = False
        
        # 模式: "纵跳" 或 "步态分析"
        self.current_mode = "纵跳"
        
        # 图表数据 (与 1data_show.py 完全一致)
        self.h_x, self.h_y = [], []
        self.cadence_x, self.cadence_y = [], []
        self.initial_range = 10
        self.slide_window = 15

        # 纵跳事件显示辅助
        self._last_strike_centroid = None
        
        # ===== 性能优化: UI 节流 =====
        self._last_ui_update = 0.0
        self._ui_update_interval = 0.1
        self._last_chart_update = 0.0
        self._chart_update_interval = 0.15
        self._pending_chart_data = None
        
        # ===== 性能优化: 行距设置标记 =====
        self._line_spacing_applied = False
        
        # 相机实例
        self.camera = None
        
        # 算法引擎 (L2 层，位于后台线程)
        self.gait_engine = None

        # USB 配置
        self.dll_path = _find_dll()
        self.vid = self._parse_int_env("DAYU_VID", 0x04B4)
        self.pid = self._parse_int_env("DAYU_PID", 0x1004)
        self.timeout_ms = self._parse_int_env("DAYU_TIMEOUT", 30)
        self.chunk_size = self._parse_int_env("DAYU_CHUNK", 512)
        
        # Worker, Engine 和线程
        self.engine_thread = None
        self.serial_worker = None
        
        # 时间基准
        self._start_time = None

        self._init_ui()
        self._apply_global_style()
        self.setWindowTitle("运动步态分析系统")
        self.setMinimumSize(1000, 600)
        self.resize(1000, 600)

    @staticmethod
    def _parse_int_env(name, default):
        v = os.getenv(name)
        if not v:
            return default
        try:
            return int(v, 0)
        except Exception:
            return default

    def _init_ui(self):
        """UI 布局 - 优化版"""
        self.main_lay = QtWidgets.QHBoxLayout()
        
        # 左侧面板容器 - 添加内边距
        left_container = QtWidgets.QWidget()
        left_container.setMinimumWidth(380)
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(15, 10, 15, 10)  # 左右内边距 15px

        # 参数配置面板 (带滚动条)
        self.param_panel = ParamPanel()
        param_scroll = QtWidgets.QScrollArea()
        param_scroll.setWidget(self.param_panel)
        param_scroll.setWidgetResizable(True)
        param_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        left_layout.addWidget(param_scroll, 1)

        # 运行时进度标签 (跳跃计数 / 倒计时)
        from dayu_widgets.label import MLabel
        self._progress_label = MLabel("")
        self._progress_label.setAlignment(Qt.AlignCenter)
        self._progress_label.setStyleSheet("font-size: 16pt; font-weight: bold; padding: 4px;")
        self._progress_label.hide()
        left_layout.addWidget(self._progress_label)

        # 分析详情
        left_layout.addWidget(MDivider("分析详情"))
        self.text_edit_top = MTextEdit(self)
        self.text_edit_top.setReadOnly(True)
        self.text_edit_top.setMinimumSize(200, 200)
        self.text_edit_top.setObjectName("data_display_edit")
        self.text_edit_top.setStyleSheet("QTextEdit#data_display_edit { font-size: 14pt; }")
        
        # 连接配置变更信号，更新待机摘要
        self.param_panel.config_changed.connect(self._update_standby_summary)
        
        left_layout.addWidget(self.text_edit_top, 1)

        # 按钮区 - 重新布局：相机按钮 + 开始分析按钮
        left_layout.addWidget(MDivider("操作"))
        self.btn_container = QtWidgets.QWidget()
        self.btn_container.setMinimumHeight(120)  # 增加高度容纳两个按钮
        self.btn_layout = QtWidgets.QVBoxLayout(self.btn_container)  # 改为垂直布局
        self.btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_layout.setSpacing(10)
        
        # 相机按钮 (次级样式)
        self.btn_camera = MPushButton("📷 打开相机")
        self.btn_camera.setObjectName("btnCamera")
        self.btn_camera.setMinimumHeight(45)
        self.btn_camera.clicked.connect(self.on_camera_clicked)
        self.btn_layout.addWidget(self.btn_camera)
        
        # 开始分析按钮 (主要样式)
        self.btn_start = MPushButton("开始分析").primary()
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.btn_start.setMinimumHeight(60)
        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_layout.addWidget(self.btn_start)
        left_layout.addWidget(self.btn_container, 0)

        # 右侧图表 (与 1data_show.py 完全一致)
        right_container = QtWidgets.QWidget()
        right_container.setMinimumWidth(500)
        right_layout = QtWidgets.QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 10, 15, 10)
        right_layout.addWidget(MDivider("数据可视化"))

        if _PG_AVAILABLE:
            # 图表1: 跳高
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground(dayu_theme.background_in_color)
            self.plot_widget.showGrid(x=True, y=True, alpha=0.1)  # 降低网格透明度
            self.plot_widget.setLabel('left', '跳高 h (m)')
            self.plot_widget.setLabel('bottom', '跳跃次数')
            self.plot_widget.enableAutoRange(axis='y')
            self.plot_widget.setXRange(0, 10, padding=0)
            self.h_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush=dayu_theme.primary_color)
            self.plot_widget.addItem(self.h_bar)
            right_layout.addWidget(self.plot_widget, 1)

            # 图表2: 步频
            self.plot_widget_cadence = pg.PlotWidget()
            self.plot_widget_cadence.setBackground(dayu_theme.background_in_color)
            self.plot_widget_cadence.showGrid(x=True, y=True, alpha=0.1)  # 降低网格透明度
            self.plot_widget_cadence.setLabel('left', '步频 (步/分钟)')
            self.plot_widget_cadence.setLabel('bottom', '跳跃次数')
            self.plot_widget_cadence.enableAutoRange(axis='y')
            self.plot_widget_cadence.setXRange(0, 10, padding=0)
            self.cadence_bar = pg.BarGraphItem(x=[], height=[], width=0.65, brush='#52c41a')
            self.plot_widget_cadence.addItem(self.cadence_bar)
            right_layout.addWidget(self.plot_widget_cadence, 1)
        else:
            placeholder = QtWidgets.QLabel("未安装 pyqtgraph")
            right_layout.addWidget(placeholder)

        self.main_lay.addWidget(left_container, 4)  # 调大左侧比例
        self.main_lay.addWidget(right_container, 5) # 调小右侧比例
        self.setLayout(self.main_lay)
        
        # 初始化摘要文本
        self._update_standby_summary()

    def _apply_global_style(self):
        """应用全局 QSS 样式表"""
        style = """
        /* 全局字体 */
        QWidget {
            font-family: "Microsoft YaHei UI", "微软雅黑", sans-serif;
        }
        
        /* 相机按钮 - 次级样式 */
        QPushButton#btnCamera {
            background-color: #424242;
            color: #e0e0e0;
            border-radius: 6px;
            font-size: 14px;
            padding: 8px;
            border: 1px solid #555555;
        }
        QPushButton#btnCamera:hover {
            background-color: #505050;
            border-color: #777777;
        }
        QPushButton#btnCamera:pressed {
            background-color: #383838;
        }
        
        /* 主操作按钮 - 增强样式 */
        QPushButton#btnStart {
            border-radius: 6px;
            font-size: 20px;
        }
        
        /* 模式选择下拉框样式 */
        QComboBox#modeCombo {
            background-color: #3a3a3a;
            color: #e0e0e0;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 14px;
        }
        QComboBox#modeCombo:hover {
            border-color: #777777;
            background-color: #454545;
        }
        QComboBox#modeCombo:focus {
            border-color: #555555;
            background-color: #3a3a3a;
        }
        QComboBox#modeCombo:on {
            border-color: #555555;
            background-color: #3a3a3a;
        }
        QComboBox#modeCombo::drop-down {
            border: none;
            width: 20px;
        }
        QComboBox#modeCombo QAbstractItemView {
            background-color: #3a3a3a;
            color: #e0e0e0;
            selection-background-color: #4a4a4a;
            border: 1px solid #555555;
        }
        """
        self.setStyleSheet(style)
    
    def on_camera_clicked(self):
        """打开/关闭相机"""
        if self.camera is None:
            self.camera = Camera()
        
        if not self.camera.is_running:
            self.camera.open_camera(threaded=True)
            self.btn_camera.setText("📷 关闭相机")
        else:
            self.camera.close_camera()
            self.btn_camera.setText("📷 打开相机")

    def _update_standby_summary(self):
        """更新待机状态下的配置摘要，并根据模式调整图表标签"""
        if not hasattr(self, 'btn_start') or not self.btn_start.isVisible():
            return  # UI未初始化完成或测试运行中，不更新摘要
            
        config = self.param_panel.get_config()
        new_mode = "纵跳" if config.test_type == "Jump Test" else "步态分析"
        
        if getattr(self, 'current_mode', None) != new_mode:
            self.current_mode = new_mode
            if _PG_AVAILABLE:
                if self.current_mode == "纵跳":
                    self.plot_widget.setLabel('left', '跳高 h (m)')
                    self.plot_widget.setLabel('bottom', '跳跃次数')
                    self.plot_widget_cadence.setLabel('left', '步频 (步/分钟)')
                    self.plot_widget_cadence.setLabel('bottom', '跳跃次数')
                else:
                    self.plot_widget.setLabel('left', '步长 (cm)')
                    self.plot_widget.setLabel('bottom', '步数')
                    self.plot_widget_cadence.setLabel('left', '步速 (cm/s)')
                    self.plot_widget_cadence.setLabel('bottom', '步数')
            self._reset_analysis_state()
            
        # 生成摘要文本
        lines = [
            "=== 待机配置摘要 ===",
            f"• 测试模式: {config.test_type}",
            f"• 启动条件: {config.start_type}",
            f"• 停止条件: {config.stop_type}",
        ]
        if config.number_of_jumps:
            lines.append(f"• 目标跳跃: {config.number_of_jumps} 次")
        if config.test_length:
            lines.append(f"• 测试时长: {config.test_length}")
            
        lines.append(f"• 接触/腾空: >{config.min_contact_time}ms / >{config.min_flight_time}ms")
        
        if config.metronome_enabled:
            lines.append(f"• 节拍器: 开启 ({config.metronome_bpm} BPM)")
            
        lines.append("\n👉 请确认配置后，点击【开始分析】按钮")
        self.text_edit_top.setText("\n".join(lines))

    def _reset_analysis_state(self):
        """重置分析状态 (仅重置 UI 层状态，算法引擎在 on_start_clicked 中新建)"""
        self._last_strike_centroid = None
        
        # ===== 性能优化: 重置 UI 节流状态 =====
        self._last_ui_update = 0.0
        self._last_chart_update = 0.0
        self._pending_chart_data = None
        self._line_spacing_applied = False
        
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[])
            self.cadence_bar.setOpts(x=[], height=[])
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)

    def on_start_clicked(self):
        """开始采集 (复用 start_test.py 的 USB 启动逻辑)"""
        self.paused = False
        self.btn_start.setVisible(False)
        self.param_panel.set_enabled(False)

        # 创建暂停/结束按钮
        self.btn_pause = MPushButton("暂停")
        self.btn_pause.setMinimumHeight(60)
        self.btn_stop = MPushButton("结束")
        self.btn_stop.setMinimumHeight(60)
        self.btn_pause.clicked.connect(self.on_pause_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)
        self.btn_layout.addWidget(self.btn_pause)
        self.btn_layout.addWidget(self.btn_stop)

        # 重置状态
        self._reset_analysis_state()
        self._start_time = time.perf_counter()

        # 从 ParamPanel 获取配置
        config = self.param_panel.get_config()
        self.current_mode = "纵跳" if config.test_type == "Jump Test" else "步态分析"
        
        mode_text = self.current_mode
        self.text_edit_top.setText(f"模式: {mode_text} (实时)\n正在连接设备...")
        self._apply_line_spacing(self.text_edit_top, 140)

        # ====== 三层架构: 统一后台线程 ======
        self.engine_thread = QThread()

        # L1: USB 采集层
        self.serial_worker = UsbWorker(
            dll_path=self.dll_path,
            vid=self.vid,
            pid=self.pid,
            timeout_ms=self.timeout_ms,
            chunk_size=self.chunk_size,
        )
        self.serial_worker.moveToThread(self.engine_thread)

        # L2: 算法引擎层
        self.gait_engine = GaitEngine(config=config)
        self.gait_engine.set_start_time(self._start_time)
        self.gait_engine.moveToThread(self.engine_thread)

        # L1 → L2: 同线程 DirectConnection（零开销）
        self.serial_worker.raw_contact_signal.connect(
            self.gait_engine.process_raw_frame, Qt.DirectConnection
        )

        # L2 → L3: 跨线程 QueuedConnection（低频高级事件）
        self.gait_engine.hop_event.connect(self._on_hop_event)
        self.gait_engine.gait_step_event.connect(self._on_gait_step_event)
        self.gait_engine.gait_status_snapshot.connect(self._on_gait_snapshot)

        # L2 → L3: 自动停止信号
        self.gait_engine.test_finished.connect(self._on_test_finished)

        # L1 → L3: 设备消息（节流）
        self.serial_worker.data_received.connect(self._on_device_message)

        self.engine_thread.started.connect(self.serial_worker.start)
        self.engine_thread.finished.connect(self.serial_worker.deleteLater)
        self.engine_thread.start()

        # ====== 运行时进度显示 ======
        self._init_progress_display(config)

    def _apply_line_spacing(self, edit, percent=150):
        """设置行距 - 性能优化：只在首次调用时应用"""
        if self._line_spacing_applied:
            return  # 已设置过，跳过
        cursor = edit.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(float(percent), 1)
        cursor.mergeBlockFormat(fmt)
        cursor.endEditBlock()
        self._line_spacing_applied = True

    def _on_device_message(self, msg: str):
        """显示设备消息"""
        current = self.text_edit_top.toPlainText()
        if "正在连接设备" in current:
            self.text_edit_top.setText(f"设备: {msg}\n等待数据...")
        self._apply_line_spacing(self.text_edit_top, 140)

    def _on_test_finished(self, reason: str):
        """自动停止回调 — 由 GaitEngine.test_finished 信号触发。"""
        reason_text = {
            "jump_count_reached": "跳跃次数已达标",
            "time_up": "测试时间到",
        }.get(reason, reason)
        self.text_edit_top.append(f"\n✅ 自动停止: {reason_text}")
        self._apply_line_spacing(self.text_edit_top, 140)
        # 延迟执行停止流程，确保最后一个事件处理完毕
        from qtpy.QtCore import QTimer
        QTimer.singleShot(200, self.on_stop_clicked)

    # ---------------------------------------------------------------
    #  运行时进度显示 (跳跃计数 / 倒计时)
    # ---------------------------------------------------------------

    def _init_progress_display(self, config):
        """初始化运行时进度显示。"""
        from qtpy.QtCore import QTimer as _QTimer
        self._countdown_timer = None
        self._countdown_remaining = 0
        self._jump_target = None

        if config.stop_type == "Status change" and config.number_of_jumps:
            self._jump_target = config.number_of_jumps
            self._progress_label.setText(f"0 / {self._jump_target} 跳")
            self._progress_label.show()
        elif config.stop_type == "End of Time" and config.test_length:
            self._countdown_remaining = config.get_test_length_seconds()
            mm = self._countdown_remaining // 60
            ss = self._countdown_remaining % 60
            self._progress_label.setText(f"剩余 {mm:02d}:{ss:02d}")
            self._progress_label.show()
            self._countdown_timer = _QTimer(self)
            self._countdown_timer.timeout.connect(self._on_countdown_tick)
            self._countdown_timer.start(1000)
        else:
            self._progress_label.hide()

    def _update_jump_progress(self):
        """每次 hop_event(touch) 时更新跳跃进度标签。"""
        if self._jump_target is None or self.gait_engine is None:
            return
        current = getattr(self.gait_engine, 'touch_count', 0)
        self._progress_label.setText(f"{current} / {self._jump_target} 跳")

    def _on_countdown_tick(self):
        """每秒更新倒计时标签。"""
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            if self._countdown_timer:
                self._countdown_timer.stop()
            self._progress_label.setText("时间到")
        else:
            mm = self._countdown_remaining // 60
            ss = self._countdown_remaining % 60
            self._progress_label.setText(f"剩余 {mm:02d}:{ss:02d}")

    def _stop_progress_display(self):
        """停止进度显示，清理计时器。"""
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.stop()
            self._countdown_timer = None
        self._jump_target = None
        self._progress_label.hide()

    # ---------------------------------------------------------------
    #  L3 事件接收槽 (从 GaitEngine 跨线程接收高级事件)
    # ---------------------------------------------------------------

    def _on_hop_event(self, ev):
        """接收纵跳事件 (FootEvent)，更新图表和文字面板。"""
        eng = self.gait_engine
        if eng is None:
            return
        # 触地事件 → 从事件对象取计算值（避免跨线程竞态）
        air_time = getattr(ev, '_air_time', None)
        if ev.kind.lower() == "touch" and air_time is not None:
            h = ev._hop_height
            contact_time = getattr(ev, '_contact_time', None)
            self._update_charts(h, air_time, contact_time)
        # 记录质心
        if ev.kind.lower() == "touch" and ev.centroid_cm:
            self._last_strike_centroid = ev.centroid_cm
        # 更新文字面板
        self._update_hop_display(ev)
        # 更新跳跃进度
        if ev.kind.lower() == "touch":
            self._update_jump_progress()

    def _on_gait_step_event(self, ev):
        """接收步态事件 (GaitStepEvent)，更新图表。"""
        if ev.kind == "touch" and ev.contact.step_length is not None:
            self._update_charts(ev.contact.step_length, ev.contact.velocity, None)

    def _on_gait_snapshot(self, snapshot: dict):
        """接收步态状态快照 (~10Hz)，更新步态分析面板。"""
        lines = [
            f"模式: 步态分析 (Object Tracking)",
            f"步态阶段: {snapshot['status']}",
            f"原始光斑数: {snapshot['cluster_count']} 簇",
            f"时间: {snapshot['timestamp']:.3f}s",
        ]
        centroids = snapshot.get("active_centroids", [])
        centroids_str = ", ".join(f"{c:.1f}cm" for c in centroids) if centroids else "--"
        lines.append(f"脚印坐标: {centroids_str}")
        lines.append("-" * 30)
        lines.append(f"累计触地: {snapshot['touch_count']} 次")
        lines.append(f"累计离地: {snapshot['lift_count']} 次")
        if snapshot.get("stride_count", 0) > 0:
            avg_stride = snapshot["stride_sum"] / snapshot["stride_count"]
            lines.append(f"最新步长: {snapshot.get('latest_stride', 0):.2f} cm")
            lines.append(f"平均步长: {avg_stride:.2f} cm")
        if snapshot.get("velocity_count", 0) > 0:
            avg_vel = snapshot["velocity_sum"] / snapshot["velocity_count"]
            lines.append(f"最新步速: {snapshot.get('latest_velocity', 0):.2f} cm/s")
            lines.append(f"平均步速: {avg_vel:.2f} cm/s")
        lines.append("-" * 30)
        has_support = False
        for label, key in [("A", "foot_a_support_times"), ("B", "foot_b_support_times")]:
            times = snapshot.get(key, [])
            if times:
                avg = sum(times) / len(times)
                lines.append(f"Foot {label} 平均支撑时间: {avg:.3f}s")
                has_support = True
        if not has_support and snapshot.get("lift_count", 0) > 0:
            lines.append("(仍在积累有标签数据的支撑期...)")
        em = snapshot.get("latest_extra_metrics", {})
        if em:
            lines.append("-" * 30)
            lines.append("[ 高阶运动学特征 ]")
            if em.get("imbalance_index") is not None:
                lines.append(f"左右脚不平稳度: {em['imbalance_index']:.1f}%")
            if em.get("double_support") is not None:
                lines.append(f"双支撑期耗时: {em['double_support']:.3f}s")
            if em.get("single_support") is not None:
                lines.append(f"单支撑期耗时: {em['single_support']:.3f}s")
            if em.get("acceleration") is not None:
                lines.append(f"前后加速度: {em['acceleration']:.2f} cm/s²")
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)


    def _update_charts(self, h, air_time, contact_time=None):
        """更新柱状图 (与 1data_show.py 中的 _update_charts 完全一致)"""
        if not _PG_AVAILABLE:
            return
        
        # Update Chart 1 (Hop Height or Stride Length)
        self.h_x.append(len(self.h_x) + 1)
        self.h_y.append(h)
        
        # Update Chart 2 (Cadence or Velocity)
        if self.current_mode == "纵跳":
            # 步频公式 (与 1data_show.py 完全一致)
            if contact_time is not None and contact_time > 0:
                cadence = 60.0 / (air_time + contact_time)
            else:
                cadence = 60.0 / air_time if air_time > 0 else 0
            val2 = cadence
        else:
            # air_time 在步态模式中传入的是 velocity
            val2 = air_time
        
        self.cadence_x.append(len(self.cadence_x) + 1)
        self.cadence_y.append(val2)
        
        # 滑动窗口 (与 1data_show.py 完全一致)
        if len(self.h_x) > self.slide_window:
            display_h_x = self.h_x[-self.slide_window:]
            display_h_y = self.h_y[-self.slide_window:]
        else:
            display_h_x = self.h_x
            display_h_y = self.h_y
        
        if len(self.cadence_x) > self.slide_window:
            display_cadence_x = self.cadence_x[-self.slide_window:]
            display_cadence_y = self.cadence_y[-self.slide_window:]
        else:
            display_cadence_x = self.cadence_x
            display_cadence_y = self.cadence_y
        
        self.h_bar.setOpts(x=display_h_x, height=display_h_y, width=0.65, brush=dayu_theme.primary_color)
        self.cadence_bar.setOpts(x=display_cadence_x, height=display_cadence_y, width=0.65, brush='#52c41a')
        
        # X轴范围 (与 1data_show.py 完全一致)
        current_idx = len(self.h_x)
        if current_idx <= self.initial_range:
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)
        else:
            x_max = current_idx + 0.5
            x_min = max(0, current_idx - self.slide_window + 0.5)
            self.plot_widget.setXRange(x_min, x_max, padding=0)
            self.plot_widget_cadence.setXRange(x_min, x_max, padding=0)

    def _update_hop_display(self, ev):
        """更新纵跳模式的文本显示 - 读取 GaitEngine 统计数据"""
        eng = self.gait_engine
        if eng is None:
            return
        stage = "触地" if ev.kind.lower() == "touch" else "腾空"
        if ev.centroid_cm:
            centroid_str = f"{ev.centroid_cm:.2f}cm"
        elif self._last_strike_centroid:
            centroid_str = f"{self._last_strike_centroid:.2f}cm (上次触地)"
        else:
            centroid_str = "--"
        lines = [
            f"模式: 纵跳 (实时)",
            f"当前事件: {stage}",
            f"时刻: {ev.time:.3f}s",
            f"遮挡率: {ev.ratio:.3f}",
            f"质心位置: {centroid_str}",
            "-" * 30,
            f"触地次数: {eng.touch_count}",
            f"腾空次数: {eng.lift_count}"
        ]
        # 快照共享列表，避免遍历期间被后台线程修改
        air_snap = list(eng.air_times)
        contact_snap = list(eng.contact_times)
        if air_snap:
            latest_air = air_snap[-1]
            avg_air = sum(air_snap) / len(air_snap)
            latest_h = 0.5 * G * (latest_air / 2) ** 2
            avg_h = 0.5 * G * (avg_air / 2) ** 2
            max_h = 0.5 * G * (max(air_snap) / 2) ** 2
            lines.append(f"最新腾空时间: {latest_air:.3f}s | 平均: {avg_air:.3f}s")
            lines.append(f"最新跳高: {latest_h:.3f}m | 平均: {avg_h:.3f}m | 最大: {max_h:.3f}m")
        if contact_snap:
            latest_contact = contact_snap[-1]
            avg_contact = sum(contact_snap) / len(contact_snap)
            lines.append(f"最新触底时间: {latest_contact:.3f}s | 平均: {avg_contact:.3f}s")
        if air_snap and contact_snap:
            total_cycle = air_snap[-1] + contact_snap[-1]
            cadence = 60.0 / total_cycle if total_cycle > 0 else 0
            lines.append(f"当前步频: {cadence:.1f} steps/min")
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def on_pause_clicked(self):
        if not self.paused:
            self.paused = True
            if self.gait_engine:
                self.gait_engine.paused = True
            self.btn_pause.setText("继续")
        else:
            self.paused = False
            if self.gait_engine:
                self.gait_engine.paused = False
            self.btn_pause.setText("暂停")

    def on_stop_clicked(self):
        self.paused = True
        if self.gait_engine:
            self.gait_engine.paused = True
        
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass

        if self.engine_thread:
            try:
                self.engine_thread.quit()
                self.engine_thread.wait(2000)
            except Exception:
                pass
            finally:
                self.engine_thread = None
                self.serial_worker = None

        # 导出数据 (从 GaitEngine 读取缓存)
        self._save_export()

        # 显示汇总 (从 GaitEngine 读取统计)
        self._show_summary()

        # 清理引擎引用
        self.gait_engine = None

        self.param_panel.set_enabled(True)
        self._stop_progress_display()

        try:
            self.btn_pause.setVisible(False)
            self.btn_stop.setVisible(False)
            self.btn_layout.removeWidget(self.btn_pause)
            self.btn_layout.removeWidget(self.btn_stop)
            self.btn_pause.deleteLater()
            self.btn_stop.deleteLater()
        except Exception:
            pass

        self.btn_start.setVisible(True)
        self._update_standby_summary()
        
        # 清空柱状图数据
        if _PG_AVAILABLE:
            self.h_x, self.h_y = [], []
            self.cadence_x, self.cadence_y = [], []
            self.h_bar.setOpts(x=[], height=[])
            self.cadence_bar.setOpts(x=[], height=[])
            self.plot_widget.setXRange(0, self.initial_range, padding=0)
            self.plot_widget_cadence.setXRange(0, self.initial_range, padding=0)

    def _show_summary(self):
        """显示汇总 - 从 GaitEngine 读取统计数据"""
        eng = self.gait_engine
        if eng is None:
            return
        if self.current_mode == "纵跳":
            lines = ["分析完成！", f"触地次数: {eng.touch_count}", f"腾空次数: {eng.lift_count}"]
            if eng.air_times:
                avg_air = sum(eng.air_times) / len(eng.air_times)
                max_air = max(eng.air_times)
                avg_h = 0.5 * G * (avg_air / 2) ** 2
                max_h = 0.5 * G * (max_air / 2) ** 2
                lines.extend([
                    f"平均腾空时间: {avg_air:.3f}s",
                    f"最大腾空时间: {max_air:.3f}s",
                    f"平均跳高: {avg_h:.3f}m",
                    f"最大跳高: {max_h:.3f}m"
                ])
            if eng.contact_times:
                lines.append(f"平均触底时间: {sum(eng.contact_times)/len(eng.contact_times):.3f}s")
            if eng.cycle_times:
                avg_cycle = sum(eng.cycle_times) / len(eng.cycle_times)
                lines.extend([
                    f"平均步态周期: {avg_cycle:.3f}s",
                    f"步频: {60.0/avg_cycle:.1f} 步/分钟"
                ])
        else:
            ct = eng.contact_tracker
            if ct is None:
                return
            lines = ["分析完成！", "-" * 25]
            lines.append(f"总步数: {eng.touch_count}")
            if ct.stride_lengths:
                avg_stride = sum(ct.stride_lengths) / len(ct.stride_lengths)
                max_stride = max(ct.stride_lengths)
                lines.append(f"平均步长: {avg_stride:.2f} cm")
                lines.append(f"最大步长: {max_stride:.2f} cm")
            if ct.velocities:
                avg_vel = sum(ct.velocities) / len(ct.velocities)
                max_vel = max(ct.velocities)
                lines.append(f"平均步速: {avg_vel:.2f} cm/s")
                lines.append(f"最大步速: {max_vel:.2f} cm/s")
            lines.append("-" * 25)
            if ct.foot_a_support_times:
                avg_a = sum(ct.foot_a_support_times) / len(ct.foot_a_support_times)
                lines.append(f"Foot A 平均支撑时间: {avg_a:.3f}s")
                lines.append(f"Foot A 步数: {len(ct.foot_a_support_times)}")
            if ct.foot_b_support_times:
                avg_b = sum(ct.foot_b_support_times) / len(ct.foot_b_support_times)
                lines.append(f"Foot B 平均支撑时间: {avg_b:.3f}s")
                lines.append(f"Foot B 步数: {len(ct.foot_b_support_times)}")
            if ct.extra_metrics_history:
                lines.append("-" * 25)
                lines.append("[ 高阶运动学汇总 ]")
                for key, label, unit, dec in [
                    ("imbalance_index", "平均不平衡指数", "%", 1),
                    ("double_support", "平均双支撑期", "s", 3),
                    ("single_support", "平均单支撑期", "s", 3),
                    ("acceleration", "平均加速度", "cm/s²", 2),
                ]:
                    vals = [m[key] for m in ct.extra_metrics_history if m.get(key) is not None]
                    if vals:
                        lines.append(f"{label}: {sum(vals)/len(vals):.{dec}f}{unit}")
            if ct.touch_extra_history:
                lines.append("-" * 25)
                for key, label, unit, dec in [
                    ("imbalance_index", "平均不平衡指数", "%", 1),
                    ("single_support", "平均步间隔", "s", 3),
                    ("acceleration", "平均加速度", "cm/s²", 2),
                ]:
                    vals = [m[key] for m in ct.touch_extra_history if m.get(key) is not None]
                    if vals:
                        lines.append(f"{label}: {sum(vals)/len(vals):.{dec}f}{unit}")
                step_intervals = [
                    m.get("single_support") for m in ct.touch_extra_history
                    if m.get("single_support") is not None and m.get("single_support") > 1e-6
                ]
                if step_intervals:
                    cadence = 60.0 / (sum(step_intervals) / len(step_intervals))
                    lines.append(f"平均步频: {cadence:.1f} 步/分钟")
        self.text_edit_top.setText("\n".join(lines))
        self._apply_line_spacing(self.text_edit_top, 140)

    def _save_export(self):
        """将缓存的 LED 位图帧导出为 Excel 文件 - 从 GaitEngine 读取。"""
        eng = self.gait_engine
        if eng is None or not eng.export_frames:
            return

        frames = eng.export_frames
        timestamps = eng.export_timestamps

        reply = QtWidgets.QMessageBox.question(
            self,
            "导出数据",
            f"本次采集共 {len(frames)} 帧数据，是否保存？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        save_dir = os.path.join(_get_base_dir(), "data")
        os.makedirs(save_dir, exist_ok=True)
        filename = time.strftime("led_frames_%Y%m%d_%H%M%S.xlsx")
        path = os.path.join(save_dir, filename)

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "LED Frames"
            ws.append(["timestamp", "hex_string"])
            for ts, bits in zip(timestamps, frames):
                hex_bytes = []
                for i in range(0, 96, 8):
                    byte_val = 0
                    for j in range(8):
                        byte_val |= (bits[i + j] << j)
                    hex_bytes.append(byte_val)
                hex_str = " ".join(f"{b:02x}" for b in hex_bytes)
                ws.append([ts, hex_str])
            wb.save(path)
            QtWidgets.QMessageBox.information(
                self, "导出成功", f"数据已保存至：\n{path}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "导出失败", f"保存文件失败：{e}")

    def closeEvent(self, event):
        if self.gait_engine:
            self.gait_engine.paused = True
        if self.serial_worker:
            try:
                self.serial_worker.stop()
            except Exception:
                pass
        if self.engine_thread and self.engine_thread.isRunning():
            self.engine_thread.quit()
            self.engine_thread.wait(2000)
        event.accept()


if __name__ == "__main__":
    with application() as app:
        widget = RealTimeGaitWidget()
        dayu_theme.apply(widget)
        widget.show()

