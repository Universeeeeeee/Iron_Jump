"""Shared empty-field observation on the device sample clock (legacy import name)."""
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
import numpy as np
from hardware.sensor_frame import DeviceLayout, SensorFrame, blocked_indices
from hardware.beam_quality import BeamQualityPolicy, longest_run


class RuntimeBeamEvidence:
    """Exact rolling raw counts, without per-beam Python counter updates."""

    def __init__(self, policy):
        self.policy = policy
        self.last_frame = None
        self._reset()

    def _reset(self):
        self.healthy_samples = 0
        self._window = deque()
        self._counts = np.zeros(0, dtype=np.int32)
        self._transitions = np.zeros(0, dtype=np.int32)
        self._previous = None

    def observe(self, frame):
        previous = self.last_frame
        self.last_frame = frame
        if previous and (frame.stream_id != previous.stream_id or frame.layout != previous.layout
                         or frame.sample_index != previous.sample_index + 1):
            self._reset()
        if (len(frame.contact_bits) != frame.layout.bit_count
                or len(frame.valid_bits) != frame.layout.bit_count or b'\x00' in frame.valid_bits
                or frame.dropped_frames_before
                or any(flag != 'all_beams_blocked' for flag in frame.quality_flags)):
            self._reset()
            return False
        bits = np.frombuffer(frame.contact_bits, dtype=np.uint8)
        if self._previous is None:
            self._counts = np.zeros(len(bits), dtype=np.int32)
            self._transitions = np.zeros(len(bits), dtype=np.int32)
            changes = np.zeros(len(bits), dtype=np.uint8)
        else:
            changes = bits ^ self._previous
        self._counts += bits
        self._transitions += changes
        self._window.append((bits, changes))
        if len(self._window) > self.policy.samples:
            old_bits, old_changes = self._window.popleft()
            self._counts -= old_bits
            self._transitions -= old_changes
        self._previous = bits
        self.healthy_samples = len(self._window)
        return True


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
    stability: dict = field(default_factory=dict)
    segment_selection: dict = field(default_factory=dict)

    @property
    def key(self):
        return (self.stream_id, self.layout, self.policy, self.bad_indices, self.bad_types,
                self.segment_selection.get("source_segment_count"),
                self.segment_selection.get("source_segment_indices", ()))

    def snapshot(self):
        return {**asdict(self), "segment_count": len(self.layout.segments),
                "nominal_length_m": len(self.layout.segments), "positions_m": self.layout.positions_m,
                "time_source": "device_frame_counter"}


class WalkingPreflight:
    REQUIRED_SAMPLES = 3000
    STALE_NS = 500_000_000
    STABILITY_SAMPLES = 10  # 10 ms on the 1000 Hz device clock, not USB arrival time.
    STABILITY_REPEATS = 3

    def __init__(self, policy=None, *, stabilize=True):
        self.policy = policy or BeamQualityPolicy()
        self.stabilize = stabilize
        self.last_frame = None
        self.invalidate("等待完整数据帧，识别设备段数")

    def invalidate(self, reason):
        self.context = None
        self.healthy_samples = 0
        self.reason = reason
        self.restart_reason = reason if self.last_frame is not None else ""
        self.data_valid = False
        self._window = deque()
        self._counts = Counter()
        self._transitions = Counter()
        self._previous_bits = set()
        self.updated_indices = set()
        self.bad_indices = ()
        self.bad_types = ()
        self.transient_indices = ()
        self.ratios = []
        self.consecutive = 0
        self._stable_bits = set()
        self._pending = {}
        self.pending_indices = ()
        self._filtered_events = deque()
        self._filtered_counts = Counter()
        self._filtered_pulses = 0
        self._broad_events = deque()
        self._broad_active = False

    def _confirm_bits(self, raw, frame):
        if not self.stabilize:
            return raw
        cutoff = frame.sample_index - self.policy.samples + 1
        while self._filtered_events and self._filtered_events[0][0] < cutoff:
            _, indices = self._filtered_events.popleft()
            self._filtered_counts.subtract(indices)
            self._filtered_pulses -= len(indices)
        while self._broad_events and self._broad_events[0] < cutoff:
            self._broad_events.popleft()
        changed = raw ^ self._stable_bits
        cancelled = tuple(i for i in self._pending if i not in changed)
        if cancelled:
            self._filtered_events.append((frame.sample_index, cancelled))
            self._filtered_counts.update(cancelled)
            self._filtered_pulses += len(cancelled)
            for i in cancelled:
                del self._pending[i]
        segment_counts = Counter(i // 96 for i in changed)
        broad = (any(count / 96 > self.policy.max_bad_ratio for count in segment_counts.values())
                 or longest_run(changed, frame.layout) > self.policy.max_consecutive)
        if broad and not self._broad_active:
            self._broad_events.append(frame.sample_index)
        self._broad_active = broad
        for i in changed:
            start, count = self._pending.get(i, (frame.sample_index, 0))
            count += 1
            if count >= self.STABILITY_REPEATS and frame.sample_index - start >= self.STABILITY_SAMPLES:
                self._stable_bits.symmetric_difference_update((i,))
                self._pending.pop(i, None)
            else:
                self._pending[i] = (start, count)
        self.pending_indices = tuple(sorted(self._pending))
        return frozenset(self._stable_bits)

    def _stability_snapshot(self):
        if not self.stabilize:
            return {}
        return {"confirmation_ms": self.STABILITY_SAMPLES, "minimum_frames": self.STABILITY_REPEATS,
                "time_source": "device_frame_counter", "scope": "preflight_only",
                "transient_beam_pulses": self._filtered_pulses,
                "transient_indices": tuple(sorted(i for i, count in self._filtered_counts.items() if count > 0)),
                "broad_change_events": len(self._broad_events)}

    def observe(self, frame: SensorFrame):
        """Update the rolling evidence without running empty-field classification."""
        previous = self.last_frame
        self.last_frame = frame
        if previous and (frame.stream_id != previous.stream_id or frame.layout != previous.layout):
            self.invalidate("设备布局或数据流变化，重新自检")
        elif previous and frame.sample_index != previous.sample_index + 1:
            self.invalidate("帧序号不连续，重新自检")
        # A complete dark payload is an optical state, not a broken packet.
        # Confirm it and count broad changes just like a dark individual segment.
        invalid_flags = any(flag != "all_beams_blocked" for flag in frame.quality_flags)
        if (len(frame.contact_bits) != frame.layout.bit_count
                or len(frame.valid_bits) != frame.layout.bit_count
                or b'\x00' in frame.valid_bits or invalid_flags or frame.dropped_frames_before):
            self.invalidate(f"采集丢帧（缺失{frame.dropped_frames_before}帧），等待连续完整数据"
                            if frame.dropped_frames_before else "采集数据异常，等待连续完整数据")
            self.data_valid = (len(frame.contact_bits) == frame.layout.bit_count
                               and len(frame.valid_bits) == frame.layout.bit_count
                               and not invalid_flags and not frame.dropped_frames_before)
            return False
        self.data_valid = True
        raw_bits = blocked_indices(frame.contact_bits)
        bits = self._confirm_bits(raw_bits, frame)
        changes = bits ^ self._previous_bits if self._window else set()
        self._previous_bits = bits
        self._window.append((bits, changes))
        old_bits, old_changes = set(), set()
        if len(self._window) > self.policy.samples:
            old_bits, old_changes = self._window.popleft()
        # Shared members cancel exactly; update only evidence that actually changes.
        added, removed = bits - old_bits, old_bits - bits
        changed_added, changed_removed = changes - old_changes, old_changes - changes
        if added:
            self._counts.update(added)
        if removed:
            self._counts.subtract(removed)
        if changed_added:
            self._transitions.update(changed_added)
        if changed_removed:
            self._transitions.subtract(changed_removed)
        self.updated_indices = added | removed | changed_added | changed_removed
        self.healthy_samples = len(self._window)
        return True

    def feed(self, frame: SensorFrame):
        if not self.observe(frame):
            return
        # Re-evaluate every sample; confirmed changes invalidate a UI acknowledgement.
        observed = tuple(sorted(i for i, count in self._counts.items() if count > 0))
        persistent_threshold = self.policy.samples * .95
        self.bad_indices = tuple(i for i in observed if self._counts[i] >= persistent_threshold
                                 or self._transitions[i] >= 4)
        bad_set = set(self.bad_indices)
        self.transient_indices = tuple(i for i in observed if i not in bad_set)
        self.bad_types = tuple("持续遮挡" if self._counts[i] >= persistent_threshold else "闪烁"
                               for i in self.bad_indices)
        segment_counts = Counter(i // 96 for i in self.bad_indices)
        self.ratios = [segment_counts[s] / 96 for s in range(len(frame.layout.segments))]
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
                                          policy=self.policy, bad_indices=observed, bad_types=self.bad_types,
                                          stability=self._stability_snapshot())
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
        stability = self._stability_snapshot()
        visual = None if frame is None else {
            "positions_m": layout.positions_m,
            "segment_ids": tuple(s.segment_id for s in layout.segments),
            # Show the existing confirmed state; retain raw data and instability
            # evidence separately. This never modifies a measurement frame.
            "contact_bits": [int(i in self._stable_bits) for i in range(layout.bit_count)]
                            if self.stabilize else (list(frame.contact_bits)
                            if len(frame.contact_bits) == layout.bit_count else [0] * layout.bit_count),
            "raw_contact_bits": list(frame.contact_bits),
            "preflight_display_confirmation_ms": self.STABILITY_SAMPLES if self.stabilize else 0,
            "valid_bits": [int(bool(v) and not (self.context and i in self.context.bad_indices))
                           for i, v in enumerate(frame.valid_bits)]
                          if fresh and self.data_valid else [0] * layout.bit_count,
            "feet": [], "timestamp_s": 0,
            "preflight_bad_indices": self.bad_indices,
            "preflight_transient_indices": self.transient_indices,
            "preflight_pending_indices": self.pending_indices,
            "preflight_filtered_indices": stability.get("transient_indices", ()),
        }
        return {"ready": ready, "requires_acknowledgement": ready and bool(self.bad_indices),
                "message": self.reason, "bad_indices": self.bad_indices, "bad_types": self.bad_types,
                "transient_indices": self.transient_indices,
                "pending_indices": self.pending_indices, "stability": stability,
                "details": self._details(layout),
                "segment_ratios": self.ratios, "max_consecutive": self.consecutive,
                "policy": self.policy.snapshot(), "segment_count": len(layout.segments) if layout else None,
                "segment_ids": tuple(s.segment_id for s in layout.segments) if layout else (),
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
        parts = (["重新观察原因：" + self.restart_reason]
                 if self.healthy_samples < self.policy.samples and self.restart_reason else [])
        for s in range(len(layout.segments)):
            segment_id = layout.segments[s].segment_id
            bad = [i % 96 + 1 for i in self.bad_indices if i // 96 == s]
            transient = [i % 96 + 1 for i in self.transient_indices if i // 96 == s]
            if bad:
                types = "、".join(sorted({kind for i, kind in zip(self.bad_indices, self.bad_types) if i // 96 == s}))
                parts.append(f"第{segment_id}段：异常束{self._ranges(bad)}（{types}，{len(bad)}/96，{len(bad) / 96:.2%}）")
            if transient:
                parts.append(f"第{segment_id}段：短暂遮挡束{self._ranges(transient)}（尚未确认为闪烁，等待稳定空场）")
        if self.bad_indices or self.transient_indices:
            parts.append(f"全程最大连续{self.consecutive}束异常；允许每段≤{self.policy.max_bad_ratio:.2%}、连续≤{self.policy.max_consecutive}束")
        return "；".join(parts)
