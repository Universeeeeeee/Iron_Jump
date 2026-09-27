"""
session_controller.py — 测试会话控制器

独立的 QObject 子类，专注管理一次测试会话的硬件资源生命周期:
  - 创建/销毁 QThread + UsbWorker + GaitEngine
  - 转发 GaitEngine 信号给 View 层
  - 测试结束时构造 TestReport 并发射

设计约束:
  - 不 import 任何 QtWidgets，不知道界面长什么样
  - 不持有任何 View 引用
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from qtpy.QtCore import QObject, Signal, Slot, QThread, Qt, QMetaObject

from config.test_config import AnyTestConfig, TestConfig
from config.test_report import TestReport, build_report
from hardware.usb_worker import UsbWorker
from engine.gait_engine import GaitEngine
from engine.device_quality_session import DeviceQualitySession
from hardware.beam_quality import BeamQualityPolicy
from path_utils import find_dll as _find_dll

log = logging.getLogger(__name__)


class SessionController(QObject):
    """
    管理一次测试会话的完整生命周期。

    信号流::

        MainWindow → prepare(config) → 创建后台资源
        MainWindow → start()         → 启动线程
        GaitEngine → hop_event       → 转发给 ExecutionView
        GaitEngine → test_finished   → stop() → 构造 TestReport → session_finished
    """

    # ---- 转发给 ExecutionView 的实时数据信号 ----
    hop_event = Signal(object)              # FootEvent (纵跳)
    jump_quality_notice = Signal(dict)      # 纵跳质量提示
    gait_step_event = Signal(object)        # GaitStepEvent (步态)
    gait_snapshot = Signal(dict)            # 步态状态快照 (~10Hz)
    footprint_visual_frame = Signal(dict)   # canonical footprint frame
    device_message = Signal(str)            # 设备消息 (节流)
    device_state_changed = Signal(str, str)  # state, user-facing detail
    walking_readiness_changed = Signal(dict)
    device_layout_changed = Signal(object)
    prepare_walking_requested = Signal()
    ground_start_requested = Signal(object)
    led_health_changed = Signal(dict)        # LED 通断/闪烁诊断
    beam_quality_notice = Signal(dict)

    # ---- queued commands into the worker thread ----
    connect_device_requested = Signal()
    start_capture_requested = Signal()
    engine_start_requested = Signal(float)
    engine_pause_requested = Signal()
    engine_resume_requested = Signal()
    refresh_led_health_requested = Signal()

    # ---- 生命周期信号 → MainWindow ----
    session_started = Signal()
    session_finished = Signal(object)       # TestReport
    pause_state_changed = Signal(bool)

    def __init__(self, parent=None, *, worker_factory=None):
        super().__init__(parent)
        self._worker_factory = worker_factory or UsbWorker

        # 后台资源 (懒初始化)
        self._thread: Optional[QThread] = None
        self._worker: Optional[UsbWorker] = None
        self._engine: Optional[GaitEngine] = None

        # USB 硬件参数
        self._dll_path = _find_dll()
        self._vid = self._parse_int_env("DAYU_VID", 0x04B4)
        self._pid = self._parse_int_env("DAYU_PID", 0x1004)
        self._timeout_ms = self._parse_int_env("DAYU_TIMEOUT", 10)
        self._chunk_size = self._parse_int_env("DAYU_CHUNK", 2048)

        # 会话状态
        self._config: Optional[AnyTestConfig] = None
        self._start_time: Optional[float] = None
        self._finish_reason: Optional[str] = None
        self._is_running = False
        self._is_paused = False
        self._pause_pending = False
        self._start_pending = False
        self._device_state = "disconnected"
        self._walking_ready = False
        self._walking_device_key = None
        self._device_layout = None
        self.quality_policy = BeamQualityPolicy()
        self.quality_status = {}
        self._quality = None

    # ------------------------------------------------------------------
    #  公共方法
    # ------------------------------------------------------------------

    def ensure_device_connected(self):
        """Connect the USB device for setup-page status without capturing."""
        if self._thread is not None and self._thread.isRunning():
            if self._device_state in {"connected", "connecting", "streaming"}:
                return
            self._device_state = "connecting"
            self.device_state_changed.emit("connecting", "正在连接设备...")
            self.connect_device_requested.emit()
            return

        self._device_state = "connecting"
        self._thread = QThread()
        self._worker = self._worker_factory(
            dll_path=self._dll_path,
            vid=self._vid,
            pid=self._pid,
            timeout_ms=self._timeout_ms,
            chunk_size=self._chunk_size,
        )
        self._worker.moveToThread(self._thread)
        self._worker.data_received.connect(self._on_device_message)
        self._worker.device_state_changed.connect(self._on_device_state)
        if hasattr(self._worker, "layout_detected"):
            self._worker.layout_detected.connect(self._on_device_layout)
        if hasattr(self._worker, "led_health_changed"):
            self._worker.led_health_changed.connect(self._on_led_health)
        if hasattr(self._worker, "refresh_led_health"):
            self.refresh_led_health_requested.connect(
                self._worker.refresh_led_health
            )
        self.connect_device_requested.connect(self._worker.connect_device)
        self._thread.started.connect(self._worker.connect_device)
        self._thread.finished.connect(self._worker.deleteLater)

        self.device_state_changed.emit("connecting", "正在连接设备...")
        self._thread.start()

    def prepare(self, config: AnyTestConfig):
        """Create resources and continuously observe hardware before formal testing.

        调用此方法后进入设备准备阶段；正式算法计时仍需调用 start()。
        """
        # 配置页会提前连接设备以显示状态。复用这个已运行的
        # worker/thread，避免点击后在 UI 线程同步停止、等待再重连。
        reuse_device = (
            self._engine is None
            and self._worker is not None
            and self._thread is not None
            and self._thread.isRunning()
        )
        prepared_device_state = self._device_state
        if not reuse_device:
            # 如果有上一次的残留会话资源，先清理
            self._cleanup()

        self._config = config
        self._finish_reason = None
        self._is_paused = False
        self._pause_pending = False
        self._start_pending = False
        self._device_state = prepared_device_state if reuse_device else "connecting"

        if not reuse_device:
            # 1. 创建线程
            self._thread = QThread()

            # 2. 创建 L1: USB 采集层
            self._worker = self._worker_factory(
                dll_path=self._dll_path,
                vid=self._vid,
                pid=self._pid,
                timeout_ms=self._timeout_ms,
                chunk_size=self._chunk_size,
            )
            self._worker.moveToThread(self._thread)

        # 3. 创建 L2: 算法引擎层
        self._engine = GaitEngine(config=config)
        self._engine.paused = True

        # 4. Real hardware queues frames and arm commands on the same worker thread.
        if (hasattr(self._worker, "sensor_frame_received") and
                hasattr(self._worker, "prepare_walking_capture")):
            self._quality = DeviceQualitySession(config, self.quality_policy, self._engine)
            self._engine.quality = self._quality
            self._walking_ready = False
            self._worker.sensor_frame_received.connect(self._quality.on_frame, Qt.QueuedConnection)
            self._worker.acquisition_issue.connect(self._quality.on_issue, Qt.QueuedConnection)
            self._worker.device_state_changed.connect(self._quality.on_device_state)
            self.prepare_walking_requested.connect(self._worker.prepare_walking_capture)
            self.prepare_walking_requested.connect(self._quality.monitor)
            self.ground_start_requested.connect(self._quality.arm_checked)
            self._quality.armed.connect(self._engine.begin_quality_session)
            self._quality.armed.connect(self._on_walking_armed)
            self._quality.frame_ready.connect(self._engine.process_quality_frame)
            self._quality.readiness.connect(self._on_walking_readiness)
            self._quality.notice.connect(self.beam_quality_notice)
            self._quality.finished.connect(self._on_engine_finished)
        elif self._engine.overground is not None:
            walking = self._engine.overground
            self._walking_ready = False
            # USB callbacks arrive on a Python reader thread. Queue frame/issue and
            # arm commands onto one Qt thread, keeping the readiness handoff atomic.
            self._worker.sensor_frame_received.connect(walking.on_frame, Qt.QueuedConnection)
            self._worker.acquisition_issue.connect(walking.on_issue, Qt.QueuedConnection)
            self._worker.device_state_changed.connect(walking.on_device_state)
            self.prepare_walking_requested.connect(self._worker.prepare_walking_capture)
            self.prepare_walking_requested.connect(walking.monitor)
            self.ground_start_requested.connect(walking.arm_checked)
            walking.readiness.connect(self._on_walking_readiness)
            walking.armed.connect(self._on_walking_armed)
        elif (self._engine.processor_name in {"treadmill_gait", "treadmill_running"}
              and hasattr(self._worker, "sensor_frame_received")):
            self._worker.sensor_frame_received.connect(
                self._engine.process_sensor_frame, Qt.QueuedConnection
            )
            self._worker.acquisition_issue.connect(
                self._engine.process_acquisition_issue, Qt.QueuedConnection
            )
        else:
            self._worker.raw_contact_signal.connect(
                self._engine.process_raw_frame, Qt.DirectConnection
            )

        self._engine.moveToThread(self._thread)
        # 5. 连接 L2 → Controller (跨线程 QueuedConnection, 低频)
        self._engine.hop_event.connect(self._on_hop_event)
        self._engine.jump_quality_notice.connect(self._on_jump_quality_notice)
        self._engine.gait_step_event.connect(self._on_gait_step_event)
        self._engine.gait_status_snapshot.connect(self._on_gait_snapshot)
        self._engine.footprint_visual_frame.connect(self._on_footprint_visual_frame)
        self._engine.test_finished.connect(self._on_engine_finished)
        self._engine.pause_state_changed.connect(self._on_pause_state_changed)

        # 6. 连接 L1 → Controller (设备消息, 节流)
        # 复用配置页 worker 时这些连接已经存在，不重复绑定。
        if not reuse_device:
            self._worker.data_received.connect(self._on_device_message)
            self._worker.device_state_changed.connect(self._on_device_state)
            if hasattr(self._worker, "layout_detected"):
                self._worker.layout_detected.connect(self._on_device_layout)
            if hasattr(self._worker, "led_health_changed"):
                self._worker.led_health_changed.connect(self._on_led_health)
            if hasattr(self._worker, "refresh_led_health"):
                self.refresh_led_health_requested.connect(
                    self._worker.refresh_led_health
                )

        # 7. Full-frame hardware observes continuously; legacy/simulation sources start on demand.
        if not reuse_device:
            self.connect_device_requested.connect(self._worker.connect_device)
        self.start_capture_requested.connect(self._worker.start_capture)
        self.engine_start_requested.connect(self._engine.begin_session)
        self.engine_pause_requested.connect(self._engine.pause_session)
        self.engine_resume_requested.connect(self._engine.resume_session)
        if reuse_device:
            if self._device_state == "connected":
                self.device_state_changed.emit("connected", "设备已连接")
                if self._quality is not None or self._engine.overground is not None:
                    self.prepare_walking_requested.emit()
            elif self._device_state in {"disconnected", "error"}:
                self._device_state = "connecting"
                self.device_state_changed.emit("connecting", "正在连接设备...")
                self.connect_device_requested.emit()
        else:
            self._thread.started.connect(self._worker.connect_device)
            self._thread.finished.connect(self._worker.deleteLater)
            self.device_state_changed.emit("connecting", "正在连接设备...")
            self._thread.start()
        log.info("Session prepared: %s", config.test_type)
        self.device_layout_changed.emit(self._device_layout)

    def start(self, *, acknowledge_quality=False, quality_key=None):
        """Start formal acquisition after the device has been prepared."""
        if self._thread is None or not self._thread.isRunning():
            log.warning("start() called but no session prepared")
            return
        if self._quality is not None or (self._engine is not None and self._engine.overground is not None):
            if self._is_running or self._start_pending:
                return
            if not self._walking_ready:
                self.device_message.emit("设备段数识别及空场自检尚未通过，不能开始。")
                return
            self._start_pending = True
            self._start_time = time.perf_counter()
            if self._quality is not None:
                self.ground_start_requested.emit((quality_key or self._walking_device_key, acknowledge_quality))
            else:
                self.ground_start_requested.emit(self._walking_device_key)
            return
        if self._device_state != "connected":
            log.warning("start() called while device state is %s", self._device_state)
            self.device_state_changed.emit(
                self._device_state,
                "设备尚未就绪，不能开始采集。",
            )
            return
        if self._device_layout is not None and len(self._device_layout.segments) != 1:
            self.device_message.emit("当前模式仅支持单段设备，请改用地面走路/跑步，或连接单段设备。")
            return
        if self._is_running or self._start_pending:
            return

        self._start_time = time.perf_counter()
        self._is_paused = False
        self._start_pending = True
        self.engine_start_requested.emit(self._start_time)
        self.start_capture_requested.emit()
        log.info("Session capture requested")

    def retry_device(self):
        """Retry device connection while remaining in the prepared screen."""
        if self._thread is None or not self._thread.isRunning():
            return
        if self._is_running or self._start_pending:
            return
        self._device_state = "connecting"
        self.device_state_changed.emit("connecting", "正在重新连接设备...")
        self.connect_device_requested.emit()

    def refresh_led_health(self):
        """Refresh the lightweight LED health sample without starting a test."""
        if self._worker is None:
            self.ensure_device_connected()
            return
        if self._quality is not None or (self._engine is not None and self._engine.overground is not None):
            return  # Continuous preflight owns the acquisition stream.
        if self._device_state == "connected":
            self.refresh_led_health_requested.emit()
        elif self._device_state in {"disconnected", "error"}:
            self.ensure_device_connected()

    def pause(self):
        """Pause processing and the active test clock."""
        if self._engine and self._engine.overground is not None:
            return  # Physical stops remain part of the single passage.
        if self._engine and self._is_running and not self._is_paused and not self._pause_pending:
            self._pause_pending = True
            self.engine_pause_requested.emit()

    def resume(self):
        """Resume processing from the frozen test clock."""
        if self._engine and self._is_running and self._is_paused and not self._pause_pending:
            self._pause_pending = True
            self.engine_resume_requested.emit()

    @Slot(bool)
    def _on_pause_state_changed(self, paused):
        if not self._is_running:
            return
        self._pause_pending = False
        self._is_paused = paused
        self.pause_state_changed.emit(paused)

    def toggle_pause(self):
        if self._is_paused:
            self.resume()
        else:
            self.pause()

    def stop(self, reason: str | None = None):
        """停止会话，构造 TestReport 并发射 session_finished 信号。"""
        if not self._is_running:
            return

        if reason is not None:
            self._finish_reason = reason
        self._is_running = False
        self._is_paused = False
        self._pause_pending = False
        report = self._do_stop(self._finish_reason or "manual")

        if report is not None:
            self.session_finished.emit(report)

    def discard(self):
        """Discard a prepared, non-running session without creating a report."""
        if self._is_running:
            raise RuntimeError("cannot discard a running session")
        self._cleanup()
        self._config = None
        self._start_time = None
        self._finish_reason = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def engine(self) -> Optional[GaitEngine]:
        """暴露引擎引用，供 ExecutionView 读取实时统计（如 touch_count）。"""
        return self._engine

    @property
    def config(self) -> Optional[AnyTestConfig]:
        return self._config

    @property
    def start_time(self) -> Optional[float]:
        return self._start_time

    @property
    def device_state(self) -> str:
        return self._device_state

    # ------------------------------------------------------------------
    #  内部信号处理
    # ------------------------------------------------------------------

    @Slot(object)
    def _on_hop_event(self, ev):
        self.hop_event.emit(ev)

    @Slot(dict)
    def _on_jump_quality_notice(self, notice: dict):
        self.jump_quality_notice.emit(notice)

    @Slot(object)
    def _on_gait_step_event(self, ev):
        self.gait_step_event.emit(ev)

    @Slot(dict)
    def _on_gait_snapshot(self, snapshot):
        self.gait_snapshot.emit(snapshot)

    @Slot(dict)
    def _on_footprint_visual_frame(self, frame):
        self.footprint_visual_frame.emit(frame)

    @Slot(str)
    def _on_device_message(self, msg):
        self.device_message.emit(msg)

    @Slot(str, str)
    def _on_device_state(self, state: str, message: str):
        self._device_state = state
        if state in {"disconnected", "error"}:
            self._device_layout = None
            self.device_layout_changed.emit(None)
        if state == "streaming" and self._start_pending:
            self._start_pending = False
            self._is_running = True
            self.session_started.emit()
            log.info("Session started")
        elif state == "error" and self._start_pending:
            self._start_pending = False
            self._start_time = None
            if self._engine is not None:
                self._engine.paused = True
        self.device_state_changed.emit(state, message)
        if state == "connected" and not self._is_running and not self._start_pending:
            if self._quality is not None or (self._engine is not None and self._engine.overground is not None):
                self.prepare_walking_requested.emit()
            else:
                self.refresh_led_health()

    @Slot(dict)
    def _on_walking_readiness(self, result):
        self.quality_status = dict(result)
        self._walking_ready = result["ready"]
        self._walking_device_key = result.get("device_key")
        if not self._walking_ready or result.get("start_rejected"):
            self._start_pending = False
        self.walking_readiness_changed.emit(result)

    @Slot()
    def _on_walking_armed(self):
        self._start_pending = False
        self._is_running = True
        self.session_started.emit()

    @Slot(dict)
    def _on_led_health(self, result: dict):
        self.led_health_changed.emit(result)

    @Slot(object)
    def _on_device_layout(self, layout):
        self._device_layout = layout
        self.device_layout_changed.emit(layout)
        if (len(layout.segments) > 1 and self._engine is not None
                and self._engine.overground is None and (self._is_running or self._start_pending)):
            self.device_message.emit("检测到多段设备，当前模式仅支持单段，已停止采集。")
            self.stop("unsupported_layout")

    @Slot(str)
    def _on_engine_finished(self, reason: str):
        """GaitEngine 自动停止回调（跳跃次数达标 / 时间到）。"""
        log.info("Engine auto-stop: %s", reason)
        self._finish_reason = reason
        self.stop(reason)

    # ------------------------------------------------------------------
    #  内部实现
    # ------------------------------------------------------------------

    def _do_stop(self, reason: str) -> Optional[TestReport]:
        """执行实际的停止流程，返回 TestReport。"""
        engine = self._engine
        report = None

        if self._quality is not None and self._thread and self._thread.isRunning():
            QMetaObject.invokeMethod(self._quality, "halt", Qt.BlockingQueuedConnection)

        if engine is not None and engine.overground is not None and self._thread and self._thread.isRunning():
            QMetaObject.invokeMethod(engine.overground, "halt", Qt.BlockingQueuedConnection)
        # 1. 标记引擎完成 (防止后续回调)
        if engine is not None:
            engine._paused = True
            engine._finished = True
            # 停止引擎内部定时器
            if hasattr(engine, '_stop_timer') and engine._stop_timer:
                engine._stop_timer.stop()

        # 2. 停止 USB 采集
        if self._worker:
            try:
                self._stop_worker()
            except Exception:
                log.exception("Error stopping USB worker")

        # 3. 停止线程
        if self._thread:
            try:
                self._thread.quit()
                self._thread.wait(2000)
            except Exception:
                log.exception("Error stopping engine thread")

        # 4. 构造不可变报告 (在释放引用之前)
        if engine is not None:
            try:
                report = build_report(engine, reason)
            except Exception:
                log.exception("Error building report")

        # 5. 清理引用
        self._thread = None
        self._worker = None
        self._engine = None
        self._quality = None
        self.quality_status = {}

        log.info("Session stopped: %s", reason)
        return report

    def _stop_worker(self):
        # Continuous capture owns Qt timers; stop them on their owning thread.
        if (self._engine is not None
                and self._thread and self._thread.isRunning()
                and self._worker.metaObject().indexOfMethod("stop()") >= 0):
            QMetaObject.invokeMethod(self._worker, "stop", Qt.BlockingQueuedConnection)
        else:
            self._worker.stop()

    def _cleanup(self):
        """清理可能残留的上一次会话资源。"""
        if self._is_running:
            self._is_running = False
            self._do_stop("cleanup")
            return

        if self._quality is not None and self._thread and self._thread.isRunning():
            QMetaObject.invokeMethod(self._quality, "halt", Qt.BlockingQueuedConnection)
        if (self._engine is not None and self._engine.overground is not None
                and self._thread and self._thread.isRunning()):
            QMetaObject.invokeMethod(self._engine.overground, "halt", Qt.BlockingQueuedConnection)
        if self._worker:
            try:
                self._stop_worker()
            except Exception:
                log.exception("Error stopping prepared USB worker")
        if self._thread and self._thread.isRunning():
            try:
                self._thread.quit()
                self._thread.wait(2000)
            except Exception:
                log.exception("Error stopping prepared engine thread")

        self._thread = None
        self._worker = None
        self._engine = None
        self._quality = None
        self.quality_status = {}
        self._is_paused = False
        self._start_pending = False
        self._device_state = "disconnected"
        self._pause_pending = False
        self._device_layout = None
        self._walking_ready = False
        self._walking_device_key = None
        self.device_layout_changed.emit(None)

    @staticmethod
    def _parse_int_env(name: str, default: int) -> int:
        v = os.getenv(name)
        if not v:
            return default
        try:
            return int(v, 0)
        except Exception:
            return default
