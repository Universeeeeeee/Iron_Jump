"""Mode-independent layout and samples for the cascaded 96-beam hardware.

Coordinates are in metres. Contact bits use 1=blocked, never 1=force contact.
The acquisition clock is the device's 1000 Hz counter, not USB delivery time.
"""

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class SensorSegment:
    segment_id: str
    wire_index: int
    origin_m: float
    pitch_m: float = 0.0104
    reversed: bool = False

    def __post_init__(self):
        if not self.segment_id or self.wire_index < 0:
            raise ValueError("segment_id and non-negative wire_index are required")
        if not math.isfinite(self.origin_m) or not math.isfinite(self.pitch_m) or self.pitch_m <= 0:
            raise ValueError("segment geometry must be finite, with positive pitch")


@dataclass(frozen=True)
class DeviceLayout:
    """Segments in increasing physical position; wire indices are zero-based.

    origin_m is the first physical beam centre. Pitch/origins require installation
    calibration; nominal one-metre modules do not imply uniform seam spacing.
    """

    segments: tuple[SensorSegment, ...]
    invalid_bit_indices: tuple[int, ...] = ()

    def __post_init__(self):
        if not isinstance(self.segments, tuple) or not 1 <= len(self.segments) <= 255:
            raise ValueError("segments must be a tuple of 1..255 modules")
        if sorted(s.wire_index for s in self.segments) != list(range(len(self.segments))):
            raise ValueError("wire indices must be a permutation of 0..N-1")
        if len({s.segment_id for s in self.segments}) != len(self.segments):
            raise ValueError("segment IDs must be unique")
        for left, right in zip(self.segments, self.segments[1:]):
            if left.origin_m + 95 * left.pitch_m >= right.origin_m:
                raise ValueError("physical segments must be ordered and non-overlapping")
        if not isinstance(self.invalid_bit_indices, tuple) or any(
            not 0 <= i < self.bit_count for i in self.invalid_bit_indices
        ):
            raise ValueError("invalid bits must be a tuple of physical bit indices")

    @classmethod
    def linear(cls, segment_count=1, *, wire_order=None):
        """Nominal 1 m modules; wire_order lists physical IDs (1..N) on wire."""
        if not isinstance(segment_count, int) or not 1 <= segment_count <= 255:
            raise ValueError("segment_count must be an integer in 1..255")
        order = tuple(range(1, segment_count + 1)) if wire_order is None else tuple(wire_order)
        if sorted(order) != list(range(1, segment_count + 1)):
            raise ValueError("wire_order must be a permutation of 1..N")
        return cls(tuple(
            SensorSegment(str(i), order.index(i), float(i - 1))
            for i in range(1, segment_count + 1)
        ))

    @property
    def bit_count(self):
        return len(self.segments) * 96

    @property
    def payload_bytes(self):
        return len(self.segments) * 12

    @property
    def positions_m(self):
        return tuple(s.origin_m + i * s.pitch_m for s in self.segments for i in range(96))

    def contact_bits(self, payload: bytes) -> bytes:
        if len(payload) != self.payload_bytes:
            raise ValueError("payload length does not match layout")
        result = bytearray()
        for segment in self.segments:
            offset = segment.wire_index * 12
            bits = bytes(1 - ((b >> i) & 1) for b in payload[offset:offset + 12] for i in range(8))
            result.extend(bits[::-1] if segment.reversed else bits)
        return bytes(result)


@dataclass(frozen=True)
class SensorFrame:
    """Complete immutable sample; time is relative to the first accepted frame.

    stream_id changes after explicit acquisition restart. Never compare sample
    times across stream IDs. Missing frames are NOT synthesized or time-compressed.
    """

    stream_id: str
    layout: DeviceLayout
    frame_index: int
    sample_index: int
    received_monotonic_ns: int
    contact_bits: bytes
    valid_bits: bytes
    wire_payload: bytes
    dropped_frames_before: int = 0
    quality_flags: tuple[str, ...] = ()
    sample_rate_hz: int = field(default=1000, init=False)
    time_source: str = field(default="device_frame_counter", init=False)

    @property
    def sample_time_ns(self):
        return self.sample_index * 1_000_000

    @property
    def sample_time_s(self):
        return self.sample_index / self.sample_rate_hz


@dataclass(frozen=True)
class AcquisitionIssue:
    code: str
    frame_index: int
    missing_wire_segments: tuple[int, ...] = ()


class SensorFrameAssembler:
    """Assemble whole samples; never combine packets from different counters.

    Packets can arrive in either order, with zero- or one-based numbering. Late
    completed frames are rejected, not delivered backwards. A counter reversal is
    ambiguous (restart vs stale traffic): report it and require an explicit reset.
    """

    def __init__(self, layout: DeviceLayout | None = None):
        self._configured_layout = layout
        self.reset()

    def reset(self):
        from uuid import uuid4

        self.layout = self._configured_layout
        self.valid_bits = self._valid_bits(self.layout) if self.layout else b""
        self.layout_confirmed = False
        self.stream_id = uuid4().hex
        self._pending = {}
        self._packet_base = None
        self._last_index = None
        self._last_payload = None
        self._sample_index = 0
        self._issues = []

    @staticmethod
    def _valid_bits(layout: DeviceLayout) -> bytes:
        valid = bytearray([1]) * layout.bit_count
        for i in layout.invalid_bit_indices:
            valid[i] = 0
        return bytes(valid)

    @staticmethod
    def _packet_segment_count(count: int, payload: bytes) -> int | None:
        if count == 1:
            if len(payload) % 12 == 0 and 12 <= len(payload) <= 12 * 255:
                return len(payload) // 12
        elif 2 <= count <= 255 and len(payload) == 12:
            return count
        return None

    def pop_issues(self):
        issues, self._issues = self._issues, []
        return tuple(issues)

    def _discard_superseded_pending(self):
        if self._last_index is None:
            return
        for index in list(self._pending):
            # Accepted samples already account for these missing counters. Use
            # uint32 ordering so wraparound does not discard future fragments.
            if 0 < ((self._last_index - index) & 0xFFFFFFFF) < 0x80000000:
                del self._pending[index]

    def expire(self, now_ns):
        self._discard_superseded_pending()
        for index, node in list(self._pending.items()):
            if now_ns - node["created"] >= 1_000_000_000:
                base = self._packet_base
                missing = () if base is None else tuple(
                    i for i in range(len(self.layout.segments)) if i + base not in node["packs"]
                )
                self._issues.append(AcquisitionIssue("incomplete_frame", index, missing))
                del self._pending[index]
        if self._configured_layout is None and not self.layout_confirmed and not self._pending:
            self._packet_base = None

    def feed(self, packet, received_ns: int):
        self.expire(received_ns)
        index, count, part = packet.frameIdx, packet.packNum, packet.packIdx
        payload = bytes(packet.buffer)
        detected_count = self._packet_segment_count(count, payload)
        if not 0 <= index <= 0xFFFFFFFF or detected_count is None or not 0 <= part <= count:
            if index in self._pending:
                self._pending[index]["invalid"] = True
            self._issues.append(AcquisitionIssue("invalid_packet", index))
            return None
        if self._last_index is not None and ((index - self._last_index) & 0xFFFFFFFF) >= 0x80000000:
            self._issues.append(AcquisitionIssue("out_of_order_or_reset", index))
            return None
        if self._configured_layout is None and (
            self.layout is None or (
                not self.layout_confirmed
                and detected_count != len(self.layout.segments)
                and not self._pending
            )
        ):
            self.layout = DeviceLayout.linear(detected_count)
            self.valid_bits = self._valid_bits(self.layout)
            self._packet_base = None
        n = len(self.layout.segments)
        if detected_count != n:
            if index in self._pending:
                self._pending[index]["invalid"] = True
            self._issues.append(AcquisitionIssue("layout_mismatch", index))
            return None
        if count == 1:
            if index in self._pending:
                self._pending[index]["invalid"] = True
                self._issues.append(AcquisitionIssue("packet_count_changed", index))
                return None
            if len(payload) != self.layout.payload_bytes:
                self._issues.append(AcquisitionIssue("layout_mismatch", index))
                return None
        else:
            if len(payload) != 12:
                self._issues.append(AcquisitionIssue("invalid_packet_length", index))
                return None
            if part in (0, n):
                base = 0 if part == 0 else 1
                if self._packet_base is not None and base != self._packet_base:
                    if index in self._pending:
                        self._pending[index]["invalid"] = True
                    self._issues.append(AcquisitionIssue("packet_base_changed", index))
                    return None
                self._packet_base = base
            if index not in self._pending and len(self._pending) >= 128:
                oldest = next(iter(self._pending))
                del self._pending[oldest]
                self._issues.append(AcquisitionIssue("assembly_overflow", oldest))
            node = self._pending.setdefault(index, {"created": received_ns, "packs": {}, "invalid": False})
            old = node["packs"].get(part)
            if old is not None and old != payload:
                node["invalid"] = True
                self._issues.append(AcquisitionIssue("conflicting_packet", index))
            node["packs"][part] = payload
            base = self._packet_base
            if node["invalid"] or base is None or len(node["packs"]) != n:
                return None
            if set(node["packs"]) != set(range(base, base + n)):
                self._issues.append(AcquisitionIssue("invalid_packet_indices", index))
                del self._pending[index]
                return None
            payload = b"".join(node["packs"][i] for i in range(base, base + n))
            del self._pending[index]

        dropped = 0
        if self._last_index is not None:
            delta = (index - self._last_index) & 0xFFFFFFFF
            if delta == 0:
                if payload != self._last_payload:
                    self._issues.append(AcquisitionIssue("conflicting_frame", index))
                return None
            if delta >= 0x80000000:
                self._issues.append(AcquisitionIssue("out_of_order_or_reset", index))
                return None
            self._sample_index += delta
            dropped = delta - 1
        self._last_index, self._last_payload = index, payload
        self._discard_superseded_pending()
        self.layout_confirmed = True
        flags = []
        if dropped:
            flags.append("frame_gap")
        if not any(payload):
            flags.append("all_beams_blocked")
        return SensorFrame(
            self.stream_id, self.layout, index, self._sample_index, received_ns,
            self.layout.contact_bits(payload), self.valid_bits, payload, dropped, tuple(flags),
        )
