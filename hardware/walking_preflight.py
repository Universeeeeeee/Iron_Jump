"""Strict empty-lane preflight, measured on the device sample clock."""
from dataclasses import asdict, dataclass
from hardware.sensor_frame import DeviceLayout, SensorFrame


@dataclass(frozen=True)
class PreparedDevice:
    layout: DeviceLayout
    stream_id: str
    checked_sample_index: int
    checked_monotonic_ns: int
    healthy_samples: int
    sample_rate_hz: int = 1000

    def snapshot(self):
        return {
            **asdict(self),
            "segment_count": len(self.layout.segments),
            "nominal_length_m": len(self.layout.segments),
            "positions_m": self.layout.positions_m,
            "time_source": "device_frame_counter",
        }


class WalkingPreflight:
    REQUIRED_SAMPLES = 1000
    STALE_NS = 500_000_000

    def __init__(self):
        self.context = None
        self.last_frame = None
        self.healthy_samples = 0
        self.reason = "等待完整数据帧，识别设备段数"

    def invalidate(self, reason):
        self.context = None
        self.healthy_samples = 0
        self.reason = reason

    def feed(self, frame: SensorFrame):
        previous = self.last_frame
        self.last_frame = frame
        if previous and (frame.stream_id != previous.stream_id or frame.layout != previous.layout):
            self.invalidate("设备布局或数据流变化，重新自检")
        elif previous and frame.sample_index != previous.sample_index + 1:
            self.invalidate("帧序号不连续，重新自检")
        if (len(frame.contact_bits) != frame.layout.bit_count
                or len(frame.valid_bits) != frame.layout.bit_count
                or not all(frame.valid_bits) or frame.quality_flags
                or frame.dropped_frames_before):
            self.invalidate("采集数据异常，等待连续完整数据")
            return
        if any(frame.contact_bits):
            self.invalidate("检测到遮挡，请保持测量区域空场；持续遮挡需检查传感器")
            return
        self.healthy_samples += 1
        if self.healthy_samples >= self.REQUIRED_SAMPLES:
            self.context = PreparedDevice(frame.layout, frame.stream_id, frame.sample_index,
                                          frame.received_monotonic_ns, self.healthy_samples)
            self.reason = "自检通过，可以开始"
        else:
            self.reason = f"空场自检 {self.healthy_samples}/{self.REQUIRED_SAMPLES} 帧"

    def ready(self, now_ns):
        if self.context and not 0 <= now_ns - self.context.checked_monotonic_ns <= self.STALE_NS:
            self.invalidate("采集超时，重新自检")
        return self.context is not None

    def status(self, now_ns):
        ready = self.ready(now_ns)
        layout = self.last_frame.layout if self.last_frame else None
        return {"ready": ready, "message": self.reason,
                "segment_count": len(layout.segments) if layout else None,
                "nominal_length_m": len(layout.segments) if layout else None,
                "healthy_samples": self.healthy_samples}
