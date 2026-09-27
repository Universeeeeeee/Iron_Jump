"""
gait_engine.py — 独立算法引擎（L2 算法层）

职责:
  - 接收 UsbWorker 的 raw_contact_signal（96 位无损接触状态 + 精确时间戳）
  - 在后台线程内执行簇提取、轨迹追踪、触地/离地状态机
  - 发射高级事件信号（hop_event / gait_step_event）给 UI 层
  - 内部缓存导出数据，供结束时一次性读取

设计约束:
  - 不 import 任何 QtWidgets，只依赖 QObject / Signal / Slot
  - 与 UsbWorker 共享同一个 QThread，通过 DirectConnection 连接
  - 所有公共属性均为只读统计数据，供 UI 在结束时读取汇总
"""
from __future__ import annotations

import logging

import time
import traceback
from collections import deque
from typing import List, Optional

from qtpy.QtCore import QObject, Signal, Slot, QTimer

# 配置容器
try:
    from config.test_config import AnyTestConfig, TestConfig
except ImportError:
    from ..config.test_config import TestConfig

log = logging.getLogger(__name__)

# 纵跳检测器
try:
    from .single_foot_tracker import SingleFootDetector, LedFrame, FootEvent
except ImportError:
    from single_foot_tracker import SingleFootDetector, LedFrame, FootEvent

# 步态聚类与追踪
try:
    from .spatial_clusterer import ClusterTracker, extract_clusters
except ImportError:
    from spatial_clusterer import ClusterTracker, extract_clusters

# Contact-Based 步态事件检测器
try:
    from .contact_tracker import ContactBasedGaitTracker, GaitStepEvent
except ImportError:
    from contact_tracker import ContactBasedGaitTracker, GaitStepEvent

try:
    from .footprint_visualization import FootprintTimelineRecorder
except ImportError:
    from footprint_visualization import FootprintTimelineRecorder

# 模式处理器
try:
    from .modes.jump_processor import JumpProcessor
except ImportError:
    from modes.jump_processor import JumpProcessor


G = 9.81  # 重力加速度
MAX_EXPORT_FRAMES = 600_000  # 导出缓存上限 (10 分钟 @1000Hz, ~230MB)


class GaitEngine(QObject):
    """
    算法引擎 — 纯计算，无 UI 依赖。

    目前作为 facade: 根据 config.test_type 选择对应的 ModeProcessor，
    将 process_raw_frame、build_report 委托给 processor。

    信号流:
        UsbWorker.raw_contact_signal  →  process_raw_frame()  →  hop_event / gait_step_event  →  UI

    使用方式::

        engine = GaitEngine(mode="纵跳")
        engine.moveToThread(worker_thread)
        usb_worker.raw_contact_signal.connect(engine.process_raw_frame, Qt.DirectConnection)
        engine.hop_event.connect(ui._on_hop_event)          # QueuedConnection 跨线程
        engine.gait_step_event.connect(ui._on_gait_step_event)
    """

    # === 高级事件信号 (跨线程发往 UI，低频: 每秒 2~5 次) ===
    hop_event = Signal(object)            # FootEvent, 纵跳模式的触地/腾空
    jump_quality_notice = Signal(dict)    # 纵跳非计数质量提示
    gait_step_event = Signal(object)      # GaitStepEvent, 步态模式的触地/离地

    # === 步态模式周期性状态快照 (节流: ~10Hz，供 UI 面板刷新) ===
    gait_status_snapshot = Signal(dict)   # 当前状态快照 dict
    footprint_visual_frame = Signal(dict)  # canonical footprint visual frame

    # === 自动停止信号 ===
    test_finished = Signal(str)           # 结束原因: "jump_count_reached" | "time_up"
    pause_state_changed = Signal(bool)    # emitted after the worker applies the transition

    def __init__(self, config: AnyTestConfig | None = None, *, mode: str = "纵跳", parent=None):
        """
        初始化算法引擎。

        推荐用法 (P3+)::

            config = TestConfig(test_type="Jump Test", ...)
            engine = GaitEngine(config=config)

        向后兼容 (旧用法)::

            engine = GaitEngine(mode="纵跳")  # 使用默认 TestConfig
        """
        super().__init__(parent)

        # 构建配置: 优先使用传入的 config，否则按 mode 字符串构造默认配置
        if config is not None:
            self._config = config
        else:
            from config.test_config import default_jump_config
            self._config = default_jump_config()
            if mode != "纵跳":
                self._config.test_type = "Sprint and Gait Test"

        self._start_time: Optional[float] = None
        self._paused = False
        self._pause_started_at: Optional[float] = None
        self._finished = False  # 防止重复发射 test_finished

        self.overground = None
        self.walking = None  # Compatibility with existing walking integrations.
        if self._config.test_type in {"Sprint and Gait Test", "Overground Running Test"}:
            from config.test_config import config_from_dict
            self._config = config_from_dict(self._config.to_dict())
            if self._config.test_type == "Sprint and Gait Test":
                from .walking_session import WalkingSession
                self.overground = self.walking = WalkingSession(self._config, self)
            else:
                from .overground_session import OvergroundSession
                from .modes.overground_running_processor import OvergroundRunningProcessor
                self.overground = OvergroundSession(self._config, OvergroundRunningProcessor, self)
            self.overground.snapshot.connect(self.gait_status_snapshot)
            self.overground.visual.connect(self.footprint_visual_frame)
            self.overground.finished.connect(self.test_finished)

        # ---- 处理器 ----
        self._processor = self._select_processor()
        self._sensor_origin = None
        self._sensor_last = None
        self._sensor_offset_s = 0.0

        # ---- 步态模式内部状态 (仍直接持有，尚无步态 processor) ----
        self._cluster_tracker: Optional[ClusterTracker] = None
        self._contact_tracker: Optional[ContactBasedGaitTracker] = None
        self._visual_recorder = FootprintTimelineRecorder()

        # 步态统计
        self.touch_count = 0
        self.lift_count = 0

        # ---- 导出缓存 (FIFO 有限队列，防止长期运行 OOM) ----
        self._export_frames: deque = deque(maxlen=MAX_EXPORT_FRAMES)
        self._export_timestamps: deque = deque(maxlen=MAX_EXPORT_FRAMES)

        # ---- 步态状态快照节流 ----
        self._last_snapshot_ts = 0.0
        self._snapshot_interval = 0.1  # 100ms = ~10Hz

        # ---- End of Time 倒计时 ----
        self._stop_timer: Optional[QTimer] = None
        self._stop_timer_remaining_ms = 0

        # 初始化步态检测器
        self._init_gait_detectors()

    # ---------------------------------------------------------------
    #  配置
    # ---------------------------------------------------------------

    def _select_processor(self):
        """根据 config.test_type 选择对应的 ModeProcessor。

        Mode selection rules:
          - "Jump Test" → JumpProcessor
          - "Treadmill Gait Test" → TreadmillProcessor(mode_name="treadmill_gait")
          - "Treadmill Running Test" → TreadmillProcessor(mode_name="treadmill_running")
          - "Sprint and Gait Test" → no processor (gait handled inline)
        """
        from .modes.jump_processor import JumpProcessor

        test_type = self._config.test_type

        if test_type == "Jump Test":
            return JumpProcessor(self._config)
        elif test_type == "Treadmill Gait Test":
            from .modes.treadmill_processor import TreadmillProcessor
            return TreadmillProcessor(self._config, mode_name="treadmill_gait")
        elif test_type == "Treadmill Running Test":
            from .modes.treadmill_processor import TreadmillProcessor
            return TreadmillProcessor(self._config, mode_name="treadmill_running")
        else:
            # 步态分析模式 — 尚无独立 processor，返回 None
            return None

    def set_start_time(self, t: float):
        """设置时间基准（由 UI 在点击'开始分析'时调用），并启动倒计时。"""
        self._start_time = t
        self._sensor_origin = None
        self._sensor_last = None
        self._sensor_offset_s = 0.0
        self._pause_started_at = None
        self._stop_timer_remaining_ms = 0
        self._start_timer()

    @Slot(float)
    def begin_session(self, t: float):
        """Enable processing and establish the time base immediately before capture."""
        if self.overground is not None:
            self.overground.arm(t)
            return
        self._paused = False
        self._pause_started_at = None
        self.set_start_time(t)

    def set_mode(self, mode: str):
        """切换模式并重置内部状态"""
        if mode == "纵跳":
            self._config.test_type = "Jump Test"
        else:
            self._config.test_type = "Sprint and Gait Test"
        self.reset()

    @property
    def mode(self) -> str:
        """返回当前模式的中文显示标签。委托给 processor 或回退旧逻辑。"""
        if self.overground is not None:
            return self._config.mode_label
        if self._processor is not None:
            return self._processor.display_mode
        return "步态分析"

    @property
    def processor_name(self) -> str:
        """返回当前 processor 的内部标识名。"""
        if self.overground is not None:
            return self.overground.processor_factory.name
        if self._processor is not None:
            return self._processor.name
        return "gait"

    @property
    def config(self) -> AnyTestConfig:
        return self._config

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, val: bool):
        if val:
            self.pause_session()
        else:
            self.resume_session()

    @Slot()
    def pause_session(self):
        """Freeze processing, the time limit, and the relative event clock."""
        if self._paused:
            return
        self._paused = True
        if self._start_time is not None:
            self._pause_started_at = time.perf_counter()
        if self._stop_timer is not None and self._stop_timer.isActive():
            self._stop_timer_remaining_ms = max(
                self._stop_timer.remainingTime(), 1
            )
            self._stop_timer.stop()

        if self._processor is not None and self._start_time is not None:
            pause_boundary = getattr(self._processor, "pause_boundary", None)
            if callable(pause_boundary):
                pause_boundary()
        self._sensor_offset_s = self._export_timestamps[-1] if self._export_timestamps else 0.0
        self._sensor_origin = None
        self._sensor_last = None
        self.pause_state_changed.emit(True)

    @Slot()
    def resume_session(self):
        """Resume from the frozen remaining time without a timestamp jump."""
        if not self._paused:
            return
        if self._pause_started_at is not None and self._start_time is not None:
            paused_duration = max(
                time.perf_counter() - self._pause_started_at, 0.0
            )
            self._start_time += paused_duration
        self._pause_started_at = None
        self._paused = False
        if (
            self._stop_timer is not None
            and self._stop_timer_remaining_ms > 0
            and not self._finished
        ):
            self._stop_timer.start(self._stop_timer_remaining_ms)
        self.pause_state_changed.emit(False)

    def _init_gait_detectors(self):
        """初始化步态模式检测器（仅在非纵跳模式时）。"""
        if self._config.test_type == "Jump Test" or self.overground is not None:
            self._cluster_tracker = None
            self._contact_tracker = None
        else:
            self._cluster_tracker = ClusterTracker()
            self._contact_tracker = ContactBasedGaitTracker()

    def reset(self):
        """重置所有算法和统计状态"""
        # 步态统计
        self.touch_count = 0
        self.lift_count = 0
        self._finished = False
        self._paused = False
        self._pause_started_at = None
        self._start_time = None
        self._sensor_origin = None
        self._sensor_last = None
        self._sensor_offset_s = 0.0

        # 处理器（重新选择，丢弃旧实例）
        self._processor = self._select_processor()

        # 步态追踪器
        if self._contact_tracker is not None:
            self._contact_tracker.reset()

        # 导出缓存
        self._export_frames.clear()
        self._export_timestamps.clear()

        # 快照节流
        self._last_snapshot_ts = 0.0
        self._visual_recorder.reset()

        # 停止计时器
        if self._stop_timer is not None:
            self._stop_timer.stop()
            self._stop_timer = None
        self._stop_timer_remaining_ms = 0

        # 重新初始化步态检测器
        self._init_gait_detectors()

    # ---------------------------------------------------------------
    #  导出数据访问 (供 UI 结束时读取)
    # ---------------------------------------------------------------

    @property
    def export_frames(self) -> List[List[int]]:
        return self._export_frames

    @property
    def export_timestamps(self) -> List[float]:
        return self._export_timestamps

    @property
    def contact_tracker(self) -> Optional[ContactBasedGaitTracker]:
        """暴露 ContactBasedGaitTracker 实例，供 UI 结束时读取汇总统计"""
        return self._contact_tracker

    # ---------------------------------------------------------------
    #  核心入口 (由 UsbWorker.raw_contact_signal → DirectConnection 调用)
    # ---------------------------------------------------------------

    @Slot(object)
    def process_acquisition_issue(self, issue):
        if (not self._paused and self._processor is not None
                and self._processor.name in {"treadmill_gait", "treadmill_running"}):
            self._processor.break_continuity(issue.code)

    @Slot(object)
    def begin_quality_session(self, context):
        if self.overground is not None:
            self.overground.start_prepared(context)
        else:
            self.begin_session(time.perf_counter())

    @Slot(object, object, bool)
    def process_quality_frame(self, raw, frame, uncertain):
        if self._finished:
            return
        if self.overground is not None:
            self.overground.on_frame(frame, raw, uncertain)
            return
        if self._paused:
            return
        self._processor.time_source = raw.time_source
        if self._sensor_origin is None:
            self._sensor_origin = raw.sample_index
        rel_time = self._sensor_offset_s + (raw.sample_index - self._sensor_origin) / raw.sample_rate_hz
        if uncertain:
            self._export_frames.append(list(raw.contact_bits))
            self._export_timestamps.append(rel_time)
            if not getattr(self, "_quality_uncertain", False):
                visual = {"timestamp_s": rel_time, "contact_bits": list(frame.contact_bits),
                          "valid_bits": [0] * len(frame.contact_bits), "feet": [],
                          "quality_flags": ["unavailable_contact_boundary"]}
                self.footprint_visual_frame.emit(visual)
                if not hasattr(self, "_quality_visual_events"):
                    self._quality_visual_events = deque(maxlen=10000)
                self._quality_visual_events.append(visual)
                if isinstance(self._processor, JumpProcessor):
                    self._processor.pause_boundary()
                else:
                    self._processor.break_continuity("unavailable_contact_boundary")
        else:
            self._raw_quality_bits = raw.contact_bits
            self.process_raw_frame(list(frame.contact_bits), (self._start_time or 0) + rel_time)
            self._raw_quality_bits = None
        self._quality_uncertain = uncertain

    @Slot(object)
    def process_sensor_frame(self, frame):
        """Use device samples for treadmill timing; USB delivery time is not gait time."""
        if (self._paused or self._finished or self._processor is None
                or self._processor.name not in {"treadmill_gait", "treadmill_running"}):
            return
        if len(frame.contact_bits) != 96 or not all(frame.valid_bits) or frame.quality_flags:
            self._processor.break_continuity("invalid_sensor_frame")
            return
        previous = self._sensor_last
        if previous is not None:
            if frame.stream_id != previous.stream_id:
                self._processor.break_continuity("device_stream_changed")
                self._sensor_offset_s = self._export_timestamps[-1]
                self._sensor_origin = None
            elif frame.sample_index <= previous.sample_index:
                self._processor.break_continuity("non_monotonic_sample")
                return
            elif frame.sample_index != previous.sample_index + 1 or frame.dropped_frames_before:
                self._processor.break_continuity("missing_device_samples")
        if self._sensor_origin is None:
            self._sensor_origin = frame.sample_index
        self._sensor_last = frame
        rel_time = self._sensor_offset_s + (frame.sample_index - self._sensor_origin) / frame.sample_rate_hz
        self._processor.time_source = frame.time_source
        self.process_raw_frame(list(frame.contact_bits), (self._start_time or 0.0) + rel_time)

    @Slot(list, float)
    def process_raw_frame(self, contact_bits: list, timestamp: float):
        """
        处理单帧原始接触数据。

        在后台线程内被 DirectConnection 同步调用，
        每秒可能执行数百到一千次。

        参数:
            contact_bits: 96 位接触状态列表 (1=触地)
            timestamp: time.perf_counter() 绝对时间
        """
        if self._paused or self.overground is not None:
            return

        # 转换为相对时间
        rel_time = timestamp - self._start_time if self._start_time is not None else timestamp

        # 记录到导出缓存
        self._export_frames.append(list(getattr(self, "_raw_quality_bits", None) or contact_bits))
        self._export_timestamps.append(rel_time)

        # 分发到对应模式的处理器
        if self._processor is not None:
            events = self._processor.process_raw_frame(contact_bits, rel_time, timestamp)
            # 纵跳事件 → hop_event；步态/跑步机事件 → gait_step_event
            if isinstance(self._processor, JumpProcessor):
                for ev in events:
                    self.hop_event.emit(ev)
                for notice in self._processor.pop_pending_quality_notices():
                    self.jump_quality_notice.emit(
                        {
                            "kind": notice.kind,
                            "time_s": notice.time_s,
                            "cluster_length": notice.cluster_length,
                            "ratio": notice.ratio,
                        }
                    )
                self._check_stop_condition()
            else:
                for ev in events:
                    self.gait_step_event.emit(ev)
                if hasattr(self._processor, "pop_visual_frames"):
                    for frame in self._processor.pop_visual_frames():
                        visual = frame.to_dict()
                        quality = getattr(self, "quality", None)
                        if quality and quality.context:
                            visual["valid_bits"] = [int(i not in quality.context.bad_indices)
                                                    for i in range(len(visual["contact_bits"]))]
                        self.footprint_visual_frame.emit(visual)
                if (
                    hasattr(self._processor, "make_status_snapshot")
                    and timestamp - self._last_snapshot_ts >= self._snapshot_interval
                ):
                    snapshot = self._processor.make_status_snapshot(rel_time)
                    self.gait_status_snapshot.emit(snapshot)
                    self._last_snapshot_ts = timestamp
        else:
            self._process_gait(contact_bits, rel_time, timestamp)

    # ---------------------------------------------------------------
    #  步态模式处理 (尚未提取为 processor)
    # ---------------------------------------------------------------

    def _process_gait(self, bits: list, rel_time: float, abs_time: float):
        """步态分析模式：ClusterTracker + ContactBasedGaitTracker"""
        clusters = extract_clusters(bits)
        self._cluster_tracker.update(rel_time, clusters)

        active_tracks = self._cluster_tracker.get_active_tracks_view()
        events = self._contact_tracker.process_frame(rel_time, active_tracks)

        # 同步计数器
        self.touch_count = self._contact_tracker.touch_count
        self.lift_count = self._contact_tracker.lift_count

        # 发射高级事件 (低频: 仅在 touch/lift 发生时)
        for ev in events:
            self.gait_step_event.emit(ev)  # → UI

        frame = self._visual_recorder.record_if_due(
            rel_time,
            bits,
            self._contact_tracker,
        )
        if frame is not None:
            self.footprint_visual_frame.emit(frame.to_dict())

        # 周期性状态快照 (节流 ~10Hz)
        if abs_time - self._last_snapshot_ts >= self._snapshot_interval:
            self._emit_gait_snapshot(rel_time, clusters)
            self._last_snapshot_ts = abs_time

    def _emit_gait_snapshot(self, rel_time: float, clusters: list):
        """构建步态状态快照 dict 并发射给 UI"""
        ct = self._contact_tracker
        active_count = len(ct.foot_contact_queue)

        if active_count == 0:
            status = "腾空 / 离地"
        elif active_count == 1:
            status = "单脚支撑"
        else:
            status = f"多支撑 ({active_count}脚)"

        # 活跃脚印坐标
        active_centroids = []
        for cid in ct.foot_contact_queue:
            if cid in ct.active_contacts:
                c = ct.active_contacts[cid].latest_centroid
                if c is not None:
                    active_centroids.append(c)

        snapshot = {
            "timestamp": rel_time,
            "status": status,
            "cluster_count": len(clusters),
            "active_centroids": active_centroids,
            "touch_count": self.touch_count,
            "lift_count": self.lift_count,
            # 步长统计
            "stride_count": ct.stride_count,
            "stride_sum": ct.stride_sum,
            "latest_stride": ct.stride_lengths[-1] if ct.stride_lengths else None,
            # 步速统计
            "velocity_count": ct.velocity_count,
            "velocity_sum": ct.velocity_sum,
            "latest_velocity": ct.velocities[-1] if ct.velocities else None,
            # 支撑时间
            "foot_a_support_times": list(ct.foot_a_support_times),
            "foot_b_support_times": list(ct.foot_b_support_times),
            # 高阶指标
            "latest_extra_metrics": dict(ct.latest_extra_metrics) if ct.latest_extra_metrics else {},
        }
        self.gait_status_snapshot.emit(snapshot)

    # ---------------------------------------------------------------
    #  build_report 委托
    # ---------------------------------------------------------------

    def build_report(self, reason: str = "manual"):
        """构建不可变测试报告，委托给当前 mode processor。

        Must be called after the test has stopped.
        """
        if self.overground is not None:
            report = self.overground.build_report(reason)
            if getattr(self, "quality", None) is not None:
                report.report_config_snapshot["beam_quality"] = self.quality.snapshot()
            return self._quality_report(report)
        export_frames = tuple(list(frame) for frame in self._export_frames)
        export_timestamps = tuple(self._export_timestamps)

        if self._processor is not None:
            report = self._processor.build_report(reason, export_frames, export_timestamps)
            if getattr(self, "quality", None) is not None:
                report.report_config_snapshot["beam_quality"] = self.quality.snapshot()
            return self._quality_report(report)

        # 回退到旧步态报告逻辑
        return self._build_gait_report(reason, export_frames, export_timestamps)

    def _quality_report(self, report):
        quality = getattr(self, "quality", None)
        if quality is None or quality.context is None or not hasattr(report, "visual_timeline"):
            return report
        from dataclasses import replace
        timeline = []
        for item in report.visual_timeline:
            visual = dict(item.to_dict() if hasattr(item, "to_dict") else item)
            visual["segment_ids"] = tuple(s.segment_id for s in quality.context.layout.segments)
            valid = list(visual.get("valid_bits", [1] * len(visual.get("contact_bits", ()))))
            for i in quality.context.bad_indices:
                if i < len(valid):
                    valid[i] = 0
            visual["valid_bits"] = valid
            timeline.append(visual)
        timeline.extend(getattr(self, "_quality_visual_events", ()))
        timeline.sort(key=lambda visual: visual["timestamp_s"])
        return replace(report, visual_timeline=tuple(timeline))

    def _build_gait_report(self, reason: str, export_frames: tuple, export_timestamps: tuple):
        """构建步态报告 (内联逻辑，尚未提取为 processor)。"""
        from config.test_report import GaitTestReport

        ct = self._contact_tracker
        strides = tuple(ct.stride_lengths) if ct and ct.stride_lengths else ()
        vels = tuple(ct.velocities) if ct and ct.velocities else ()
        fa = tuple(ct.foot_a_support_times) if ct and ct.foot_a_support_times else ()
        fb = tuple(ct.foot_b_support_times) if ct and ct.foot_b_support_times else ()

        avg_stride = sum(strides) / len(strides) if strides else 0.0
        max_stride = max(strides) if strides else 0.0
        avg_vel = sum(vels) / len(vels) if vels else 0.0
        max_vel = max(vels) if vels else 0.0

        imbalance = None
        avg_ds = None
        avg_ss = None
        avg_acc = None
        if ct and ct.extra_metrics_history:
            _extract = lambda key: [m[key] for m in ct.extra_metrics_history if m.get(key) is not None]
            ii_vals = _extract("imbalance_index")
            ds_vals = _extract("double_support")
            ss_vals = _extract("single_support")
            acc_vals = _extract("acceleration")
            imbalance = sum(ii_vals) / len(ii_vals) if ii_vals else None
            avg_ds = sum(ds_vals) / len(ds_vals) if ds_vals else None
            avg_ss = sum(ss_vals) / len(ss_vals) if ss_vals else None
            avg_acc = sum(acc_vals) / len(acc_vals) if acc_vals else None

        return GaitTestReport(
            touch_count=self.touch_count,
            lift_count=self.lift_count,
            stride_lengths=strides,
            velocities=vels,
            avg_stride=avg_stride,
            max_stride=max_stride,
            avg_velocity=avg_vel,
            max_velocity=max_vel,
            foot_a_support_times=fa,
            foot_b_support_times=fb,
            imbalance_index=imbalance,
            avg_double_support=avg_ds,
            avg_single_support=avg_ss,
            avg_acceleration=avg_acc,
            finish_reason=reason,
            export_frames=export_frames,
            export_timestamps=export_timestamps,
            visual_timeline=self._visual_recorder.frames,
        )

    # ---------------------------------------------------------------
    #  自动停止逻辑
    # ---------------------------------------------------------------

    def _check_stop_condition(self):
        """在已结算统计后检查是否满足自动结束条件。"""
        if self._finished:
            return

        cfg = self._config

        if cfg.stop_type == "Status change" and cfg.number_of_jumps:
            if self._processor is not None:
                completed_jumps = getattr(self._processor, "completed_jumps", 0)
                if completed_jumps >= cfg.number_of_jumps:
                    self._finished = True
                    log.info("自动停止: 已完成 %d/%d 次跳跃",
                             completed_jumps, cfg.number_of_jumps)
                    self.test_finished.emit("jump_count_reached")

    def _start_timer(self):
        """如果 stop_type=End of Time，启动倒计时。在 set_start_time 中调用。"""
        if self._config.stop_type != "End of Time":
            return

        seconds = self._config.get_test_length_seconds()
        if not seconds or seconds <= 0:
            log.warning("stop_type=End of Time 但 test_length 无效: %s",
                        self._config.test_length)
            return

        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._on_timer_expired)
        self._stop_timer_remaining_ms = seconds * 1000
        self._stop_timer.start(self._stop_timer_remaining_ms)
        log.info("倒计时启动: %d 秒", seconds)

    def _on_timer_expired(self):
        """End of Time 倒计时到期。"""
        if self._finished:
            return
        self._stop_timer_remaining_ms = 0
        self._finished = True
        log.info("自动停止: 测试时间到")
        self.test_finished.emit("time_up")


__all__ = ["GaitEngine"]
