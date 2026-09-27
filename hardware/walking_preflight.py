"""Shared empty-field observation on the device sample clock (legacy import name)."""
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.beam_quality import BeamQualityPolicy, longest_run


@dataclass(frozen=True)
class PreparedDevice:
    layout: DeviceLayout
    stream_id: str
    checked_sample_index: int
    checked_monotonic_ns: int
    healthy_samples: int
    sample_rate_hz: int = 1000
    policy: BeamQualityPolicy = field(default_factory=BeamQualityPolicy)
    bad_indices: tuple[int, ...] = ()
    bad_types: tuple[str, ...] = ()

    @property
    def key(self):
        return (self.stream_id, self.layout, self.policy, self.bad_indices, self.bad_types)

    def snapshot(self):
        return {**asdict(self), "segment_count": len(self.layout.segments),
                "nominal_length_m": len(self.layout.segments), "positions_m": self.layout.positions_m,
                "time_source": "device_frame_counter"}


class WalkingPreflight:
    REQUIRED_SAMPLES = 3000
    STALE_NS = 500_000_000

    def __init__(self, policy=None):
        self.policy = policy or BeamQualityPolicy()
        self.last_frame = None
        self.invalidate("等待完整数据帧，识别设备段数")

    def invalidate(self, reason):
        self.context = None
        self.healthy_samples = 0
        self.reason = reason
        self.data_valid = False
        self._window = deque()
        self._counts = Counter()
        self._transitions = Counter()
        self._previous_bits = set()
        self.bad_indices = ()
        self.bad_types = ()
        self.transient_indices = ()
        self.ratios = []
        self.consecutive = 0

    def feed(self, frame: SensorFrame):
        previous = self.last_frame
        self.last_frame = frame
        if previous and (frame.stream_id != previous.stream_id or frame.layout != previous.layout):
            self.invalidate("设备布局或数据流变化，重新自检")
        elif previous and frame.sample_index != previous.sample_index + 1:
            self.invalidate("帧序号不连续，重新自检")
        if (len(frame.contact_bits) != frame.layout.bit_count
                or len(frame.valid_bits) != frame.layout.bit_count
                or not all(frame.valid_bits) or frame.quality_flags or frame.dropped_frames_before):
            self.invalidate("采集数据异常，等待连续完整数据")
            self.data_valid = (len(frame.contact_bits) == frame.layout.bit_count
                               and len(frame.valid_bits) == frame.layout.bit_count
                               and not frame.quality_flags and not frame.dropped_frames_before)
            return
        self.data_valid = True
        bits = {i for i, bit in enumerate(frame.contact_bits) if bit}
        changes = bits ^ self._previous_bits if self._window else set()
        self._previous_bits = bits
        self._window.append((bits, changes))
        self._counts.update(bits)
        self._transitions.update(changes)
        if len(self._window) > self.policy.samples:
            old_bits, old_changes = self._window.popleft()
            self._counts.subtract(old_bits)
            self._transitions.subtract(old_changes)
        self.healthy_samples = len(self._window)
        # Re-evaluate every sample so a new obstruction immediately invalidates a UI acknowledgement.
        observed = tuple(sorted(i for i, count in self._counts.items() if count > 0))
        self.bad_indices = tuple(i for i in observed if self._counts[i] >= self.policy.samples * .95
                                 or self._transitions[i] >= 4)
        self.transient_indices = tuple(i for i in observed if i not in self.bad_indices)
        self.bad_types = tuple("持续遮挡" if self._counts[i] >= self.policy.samples * .95 else "闪烁"
                               for i in self.bad_indices)
        self.ratios = [sum(i // 96 == s for i in self.bad_indices) / 96 for s in range(len(frame.layout.segments))]
        self.consecutive = longest_run(self.bad_indices, frame.layout)
        self.context = None
        if len(self._window) < self.policy.samples:
            self.reason = f"空场观察 {len(self._window) / 1000:.1f}/{self.policy.observation_seconds:g} 秒"
        elif any(r > self.policy.max_bad_ratio for r in self.ratios) or self.consecutive > self.policy.max_consecutive:
            self.reason = "异常光束超限，请清空测量区域并检查设备"
        elif self.transient_indices:
            self.reason = "检测到短暂遮挡，等待稳定空场或重复闪烁证据"
        else:
            self.context = PreparedDevice(frame.layout, frame.stream_id, frame.sample_index,
                                          frame.received_monotonic_ns, len(self._window),
                                          policy=self.policy, bad_indices=observed, bad_types=self.bad_types)
            self.reason = ("异常在阈值内：需确认现场空场并接受降级" if observed else "自检通过，可以开始")

    def ready(self, now_ns):
        if self.context and not 0 <= now_ns - self.context.checked_monotonic_ns <= self.STALE_NS:
            self.invalidate("采集超时，重新自检")
        return self.context is not None

    def status(self, now_ns):
        ready = self.ready(now_ns)
        frame = self.last_frame
        layout = frame.layout if frame else None
        fresh = frame is not None and 0 <= now_ns - frame.received_monotonic_ns <= self.STALE_NS
        visual = None if frame is None else {
            "positions_m": layout.positions_m,
            "contact_bits": list(frame.contact_bits) if len(frame.contact_bits) == layout.bit_count else [0] * layout.bit_count,
            "valid_bits": [int(bool(v) and not (self.context and i in self.context.bad_indices))
                           for i, v in enumerate(frame.valid_bits)]
                          if fresh and self.data_valid else [0] * layout.bit_count,
            "feet": [], "timestamp_s": 0,
            "preflight_bad_indices": self.bad_indices,
            "preflight_transient_indices": self.transient_indices,
        }
        return {"ready": ready, "requires_acknowledgement": ready and bool(self.bad_indices),
                "message": self.reason, "bad_indices": self.bad_indices, "bad_types": self.bad_types,
                "transient_indices": self.transient_indices,
                "details": self._details(layout),
                "segment_ratios": self.ratios, "max_consecutive": self.consecutive,
                "policy": self.policy.snapshot(), "segment_count": len(layout.segments) if layout else None,
                "nominal_length_m": len(layout.segments) if layout else None,
                "healthy_samples": self.healthy_samples,
                "device_key": self.context.key if self.context else None, "visual_frame": visual}

    @staticmethod
    def _ranges(indices):
        groups = []
        for i in indices:
            if groups and i == groups[-1][-1] + 1:
                groups[-1].append(i)
            else:
                groups.append([i])
        return "、".join(str(g[0]) if len(g) == 1 else f"{g[0]}–{g[-1]}" for g in groups)

    def _details(self, layout):
        if layout is None:
            return ""
        parts = []
        for s in range(len(layout.segments)):
            bad = [i % 96 + 1 for i in self.bad_indices if i // 96 == s]
            transient = [i % 96 + 1 for i in self.transient_indices if i // 96 == s]
            if bad:
                types = "、".join(sorted({kind for i, kind in zip(self.bad_indices, self.bad_types) if i // 96 == s}))
                parts.append(f"第{s + 1}段：异常束{self._ranges(bad)}（{types}，{len(bad)}/96，{len(bad) / 96:.2%}）")
            if transient:
                parts.append(f"第{s + 1}段：短暂遮挡束{self._ranges(transient)}（尚未确认为闪烁，等待稳定空场）")
        if parts:
            parts.append(f"全程最大连续{self.consecutive}束异常；允许每段≤{self.policy.max_bad_ratio:.2%}、连续≤{self.policy.max_consecutive}束")
        return "；".join(parts)
