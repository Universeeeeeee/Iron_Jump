"""One worker-thread gate for all test modes: preflight, frozen mask and audit."""
import time
from qtpy.QtCore import QObject, QTimer, Signal, Slot
from hardware.walking_preflight import WalkingPreflight
from hardware.beam_quality import masked_frame, uncertain_contact


class DeviceQualitySession(QObject):
    readiness = Signal(dict)
    armed = Signal(object)
    frame_ready = Signal(object, object, bool)
    notice = Signal(dict)
    finished = Signal(str)

    def __init__(self, config, policy, parent=None):
        super().__init__(parent)
        self.config = config
        self.preflight = WalkingPreflight(policy)
        self.context = None
        self.done = False
        self.last_frame = None
        self.started_ns = None
        self._last_publish = 0
        self._last_status = None
        self._events = []
        self._event_count = 0
        self._last_event_key = None
        self._last_event = None
        self._runtime = WalkingPreflight(policy, stabilize=False)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.poll)

    @Slot()
    def monitor(self):
        self.started_ns = time.perf_counter_ns()
        self._timer.start()
        self.poll()

    def _status(self):
        result = self.preflight.status(time.perf_counter_ns())
        if (result["segment_count"] not in (None, 1) and
                self.config.test_type not in {"Sprint and Gait Test", "Overground Running Test"}):
            result.update(ready=False, message="当前模式仅支持单段设备，请返回配置核对需求")
        return result

    def _publish(self, force=False):
        now = time.perf_counter_ns()
        ready = self.preflight.ready(now)
        key = (ready, self.preflight.context.key if ready else None)
        if force or key != self._last_status or now - self._last_publish >= 100_000_000:
            result = self._status()
            self._last_publish, self._last_status = now, key
            self.readiness.emit(result)

    @Slot(object)
    def arm_checked(self, request):
        if self.context or self.done:
            return
        status = self._status()
        key, acknowledged = request
        if (not status["ready"] or key != status["device_key"] or
                (status["requires_acknowledgement"] and not acknowledged)):
            status.update(start_rejected=True, message="自检结果变化或尚未确认降级，请重新核对后开始")
            self.readiness.emit(status)
            return
        self.context = self.preflight.context
        self.acknowledged = bool(acknowledged)
        self.armed.emit(self.context)
        if self.context.bad_indices:
            self.notice.emit({"code": "degraded_start", "indices": self.context.bad_indices,
                              "impact": f"降级测试：{len(self.context.bad_indices)} 束不可用；邻近坏点的事件不计入统计，详见报告。"})

    @Slot(object)
    def on_frame(self, frame):
        if self.done:
            return
        previous = self.last_frame
        self.last_frame = frame
        if self.context is None:
            self.preflight.feed(frame)
            self._publish()
            return
        if frame.layout != self.context.layout or frame.stream_id != self.context.stream_id:
            self._record("device_changed", frame, (), "设备布局或数据流变化，结束本次采集")
            self.finish("device_changed")
            return
        if previous is not None and frame.sample_index <= previous.sample_index:
            self._record("counter_reset", frame, (), "设备采样计数回退")
            self.finish("counter_reset")
            return
        invalid = (len(frame.contact_bits) != frame.layout.bit_count or
                   len(frame.valid_bits) != frame.layout.bit_count or not all(frame.valid_bits) or
                   bool(frame.quality_flags) or bool(frame.dropped_frames_before) or
                   (previous is not None and frame.sample_index != previous.sample_index + 1))
        if invalid:
            self._record("invalid_data", frame, (), "本段原始数据保留，事件与跨段指标不计入统计")
            self.frame_ready.emit(frame, frame, True)
            return
        processed = masked_frame(frame, self.context.bad_indices)
        uncertain = uncertain_contact(processed, self.context.bad_indices)
        # Runtime observations are warnings, never new masks. Motion can produce similar signals.
        self._runtime.feed(processed)
        suspicious = ()
        if self._runtime.healthy_samples >= self._runtime.policy.samples:
            suspicious = tuple(sorted(i for i, count in self._runtime._counts.items()
                                      if count >= self._runtime.policy.samples * .95 or
                                      self._runtime._transitions[i] >= 20))
        if suspicious:
            self._record("runtime_obstruction", frame, suspicious,
                         "新增持续遮挡或高频变化，可能是停留/传感器异常；未动态屏蔽，该不确定区间不计入统计")
            uncertain = True
        elif uncertain:
            self._record("masked_contact_boundary", frame, self.context.bad_indices,
                         "接触邻近不可用光束，当前事件及跨越该区间的指标排除")
        if not uncertain:
            self._last_event_key = None
        self.frame_ready.emit(frame, processed, uncertain)

    def _record(self, code, frame, indices, impact):
        key = (code, tuple(indices))
        when = (frame.sample_index - self.context.checked_sample_index) / 1000 if frame else None
        if key == self._last_event_key and self._last_event is not None:
            self._last_event["end_s"] = when
            return
        self._last_event_key = key
        event = {"code": code, "start_s": when, "end_s": when,
                 "indices": list(indices), "impact": impact}
        self._event_count += 1
        self._last_event = event
        if len(self._events) < 10000:
            self._events.append(event)
        self.notice.emit(event)

    @Slot(object)
    def on_issue(self, issue):
        if self.done:
            return
        if self.context is None:
            self.preflight.invalidate(f"采集异常：{issue.code}，重新自检")
            self._publish(True)
        else:
            self._record(issue.code, self.last_frame, (), "采集不连续，相关区间需复核")
            if issue.code in {"layout_mismatch", "out_of_order_or_reset", "packet_base_changed", "device_changed"}:
                self.finish(issue.code)

    @Slot(str, str)
    def on_device_state(self, state, message):
        if self.done:
            return
        if state in {"disconnected", "error"}:
            if self.context:
                self._record("disconnected", self.last_frame, (), message)
                self.finish("disconnected")
            else:
                self.preflight.invalidate(message)
                self._publish(True)

    @Slot()
    def poll(self):
        if self.done:
            return
        now = time.perf_counter_ns()
        if self.context is None:
            if self.last_frame is None and self.started_ns and now - self.started_ns > 5_000_000_000:
                self.preflight.invalidate("未收到完整帧，请检查设备连接")
            self._publish(True)
        elif self.last_frame and now - self.last_frame.received_monotonic_ns > 1_000_000_000:
            self._record("data_timeout", self.last_frame, (), "持续无数据，结束采集，保留已有结果")
            self.finish("data_timeout")

    def finish(self, reason):
        if self.done:
            return
        self.halt()
        self.finished.emit(reason)

    @Slot()
    def halt(self):
        self.done = True
        self._timer.stop()

    def snapshot(self):
        if self.context is None:
            return {}
        return {"preflight": self.context.snapshot(), "degraded": bool(self.context.bad_indices),
                "empty_field_acknowledged": self.acknowledged,
                "mask_frozen": True, "events": list(self._events),
                "event_time_reference": "seconds_after_preflight_checked_sample",
                "event_count": self._event_count, "events_truncated": self._event_count > len(self._events),
                "limitation": "屏蔽光束不可用于测量；邻近不可用点的事件已排除。运行中新增疑似异常未动态屏蔽，需结合原始数据复核。"}
