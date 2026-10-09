"""Shared worker-thread lifecycle for independent overground modes."""
from collections import deque
import time

from qtpy.QtCore import QObject, QTimer, Signal, Slot
from hardware.walking_preflight import WalkingPreflight
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import uncertain_contact



class OvergroundSession(QObject):
    readiness = Signal(dict)
    armed = Signal()
    finished = Signal(str)
    snapshot = Signal(dict)
    visual = Signal(dict)
    FATAL_ISSUES = {"layout_mismatch", "out_of_order_or_reset", "packet_base_changed", "device_changed"}

    def __init__(self, config, processor_factory, parent=None):
        super().__init__(parent)
        self.config = config
        self.processor_factory = processor_factory
        self.preflight = WalkingPreflight()
        self.processor = None
        self.done = False
        self.last_received_ns = None
        self._last_update_ns = 0
        self._last_ready = None
        self._last_frame = None
        self._visual_issue = None
        self._summary = None
        self._frame_filter = None
        self.frames = deque(maxlen=600000)
        self.timestamps = deque(maxlen=600000)
        self.total_frames = 0
        self.raw_only_tail_frames = 0
        self._monitor_started_ns = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.poll)

    @Slot()
    def monitor(self):
        self._monitor_started_ns = time.perf_counter_ns()
        self._timer.start()
        self.poll()

    @Slot(float)
    def arm(self, unused_host_time=0):
        # Executed in the same Qt thread as frame handling; UI readiness is advisory.
        if self.processor or self.done:
            return
        if not self.preflight.ready(time.perf_counter_ns()):
            self.poll()
            return
        if self.preflight.context.bad_indices:
            return  # Degraded starts require the shared quality gate's explicit acknowledgement.
        self.start_prepared(self.preflight.context)

    def start_prepared(self, context):
        self.processor = self.processor_factory(self.config, context)
        self._frame_filter = GroundStabilityFilter(context.layout, context.bad_indices)
        self._summary = None
        raw_bit_count = context.segment_selection.get("source_segment_count", len(context.layout.segments)) * 96
        limit = min(600000, 64 * 1024 * 1024 // (raw_bit_count + 64))
        self.frames = deque(maxlen=limit)
        self.timestamps = deque(maxlen=limit)
        self.armed.emit()

    @Slot(object)
    def arm_checked(self, device_key):
        context = self.preflight.context
        if context is None or device_key != context.key or context.bad_indices:
            status = self.preflight.status(time.perf_counter_ns())
            status["start_rejected"] = True
            status["message"] = "设备布局或数据流已变化，请重新核对段数后开始"
            self.readiness.emit(status)
            return
        self.arm()

    @Slot(object)
    def on_frame(self, frame, raw_frame=None, uncertain=False):
        if self.processor is not None:
            self.archive_raw_frame(raw_frame or frame, raw_only=self.done)
        if self.done:
            return
        self.last_received_ns = frame.received_monotonic_ns
        self._visual_issue = None
        if self.processor is None:
            self._last_frame = frame
            self.preflight.feed(frame)
            self._publish_ready()
            return
        if uncertain:
            self._consume_frames(self._frame_filter.reset())
            if not getattr(self, "_quality_uncertain", False):
                self.processor.break_continuity("unavailable_contact_boundary", frame.frame_index)
                self._summary = None
        else:
            self._consume_frames(self._frame_filter.feed(frame))
        self._quality_uncertain = uncertain
        if self.processor.finished_reason:
            self.finish(self.processor.finished_reason)
        if frame.received_monotonic_ns - self._last_update_ns >= 100_000_000:
            self._last_update_ns = frame.received_monotonic_ns
            self.publish_snapshot()

    def archive_raw_frame(self, frame, *, raw_only=False):
        """Retain accepted evidence even after the measurement has stopped."""
        if self.processor is not None:
            self.total_frames += 1
            self.raw_only_tail_frames += int(raw_only)
            self.frames.append(frame.contact_bits)
            self.timestamps.append(frame.sample_time_s)

    def _consume_frames(self, frames):
        for frame in frames:
            masked_contact = uncertain_contact(frame, self.processor.device.bad_indices)
            self.processor.process(frame, masked_contact=masked_contact)
            self._last_frame = frame
        if frames:
            self._summary = None

    @Slot(object)
    def on_issue(self, issue):
        if self.done:
            return
        if self.processor is None:
            self.preflight.invalidate(f"采集异常：{issue.code}；重新自检")
            self._publish_ready(force=True)
        else:
            self._visual_issue = issue.code
            self._consume_frames(self._frame_filter.reset())
            self.processor.break_continuity(issue.code, issue.frame_index)
            self._summary = None
            if issue.code in self.FATAL_ISSUES:
                self.finish(issue.code)

    @Slot(str, str)
    def on_device_state(self, state, message):
        if state in {"error", "disconnected"}:
            self.preflight.invalidate(message)
            if self.processor and not self.done:
                self._visual_issue = "disconnected"
                self._consume_frames(self._frame_filter.flush())
                self.processor.break_continuity("disconnected")
                self._summary = None
                self.finish("disconnected")
            else:
                self._publish_ready(force=True)

    def _publish_ready(self, force=False):
        now = time.perf_counter_ns()
        ready = self.preflight.ready(now)
        if force or ready != self._last_ready or now - self._last_update_ns >= 100_000_000:
            status = self.preflight.status(now)
            self._last_update_ns = now
            self._last_ready = status["ready"]
            self.readiness.emit(status)

    @Slot()
    def poll(self):
        if self.done:
            return
        if self.processor is None:
            if (self.last_received_ns is None and self._monitor_started_ns is not None
                    and time.perf_counter_ns() - self._monitor_started_ns > 5_000_000_000):
                self.preflight.invalidate("未收到完整帧，请检查连接及采集启动设置；可返回配置重新连接")
            self._publish_ready(force=True)
        elif self.last_received_ns is not None and time.perf_counter_ns() - self.last_received_ns > 1_000_000_000:
            self._visual_issue = "data_timeout"
            self._consume_frames(self._frame_filter.flush())
            self.processor.break_continuity("data_timeout")
            self._summary = None
            self.finish("data_timeout")

    def publish_snapshot(self):
        p = self.processor
        if p is None:
            return
        if self._summary is None:
            self._summary = p.summary()
        s = self._summary
        running = p.name == "overground_running"
        lengths = s["step_lengths_m"]
        speed = s["running_speed_m_s" if running else "walking_speed_m_s"]
        self.snapshot.emit({"touch_count": sum(c.confirmed for c in p.contacts),
                            "device_timing": ({
                                "stream_id": self._last_frame.stream_id,
                                "sample_time_s": self._last_frame.sample_time_s,
                                "received_time_s": self._last_frame.received_monotonic_ns / 1e9,
                                "frame_index": self._last_frame.sample_index,
                                "origin_sample_time_s": p.origin,
                            } if self._last_frame is not None else None),
                            "running" if running else "walking": s,
                            "status": "等待进入" if p.origin is None else s.get("status", "行走中"),
                            "stride_count": len(lengths),
                            "latest_stride": lengths[-1] * 100 if lengths else None,
                            "velocity_count": int(speed is not None),
                            "velocity_sum": (speed or 0) * 100})
        if self._last_frame is not None:
            frame = self._last_frame
            invalid = (self._visual_issue or frame.layout != p.device.layout
                       or len(frame.contact_bits) != len(p.positions) or len(frame.valid_bits) != len(p.positions)
                       or any(x != "frame_gap" for x in frame.quality_flags))
            visual = dict(p.timeline[-1]) if p.timeline else {"feet": []}
            origin = p.origin if p.origin is not None else frame.sample_time_s
            visual.update({"timestamp_s": max(0, frame.sample_time_s - origin),
                           "segment_ids": tuple(s.segment_id for s in p.device.layout.segments),
                           "positions_m": p.positions,
                           "contact_bits": list(frame.contact_bits) if len(frame.contact_bits) == len(p.positions) else [0] * len(p.positions),
                           "valid_bits": [0] * len(p.positions) if invalid else list(frame.valid_bits)})
            for index in p.device.bad_indices:
                visual["valid_bits"][index] = 0
            if invalid:
                visual["feet"] = []
            self.visual.emit(visual)

    def finish(self, reason):
        if self.done:
            return
        if self._frame_filter is not None:
            self._consume_frames(self._frame_filter.flush())
        self.done = True
        self._timer.stop()
        self.publish_snapshot()
        self.finished.emit(reason)

    @Slot()
    def halt(self):
        if self.done:
            return
        if self._frame_filter is not None:
            self._consume_frames(self._frame_filter.flush())
        self.done = True
        self._timer.stop()
        self.publish_snapshot()

    def build_report(self, reason):
        if self.processor is None:
            raise RuntimeError("Overground session has not passed preflight and armed")
        self._consume_frames(self._frame_filter.flush())
        origin = self.processor.origin
        # Keep pre-entry and unknown-edge samples as well; negative relative times
        # locate them before the first estimated touchdown without deleting frames.
        origin = origin if origin is not None else (self.timestamps[0] if self.timestamps else 0)
        pairs = [(bits, t - origin) for bits, t in zip(self.frames, self.timestamps)]
        report = self.processor.build_report(reason, tuple(x[0] for x in pairs), tuple(x[1] for x in pairs))
        report.report_config_snapshot["raw_buffer"] = {
            "total_received_frames": self.total_frames, "retained_frames": len(self.frames),
            "truncated": self.total_frames > len(self.frames), "budget_bytes": 64 * 1024 * 1024,
            "raw_only_tail_frames": self.raw_only_tail_frames,
        }
        return report
