"""Per-beam display confirmation shared by health checks and monitoring."""
import math
from collections import deque
from dataclasses import replace

import numpy as np


class BeamDisplayFilter:
    """Confirm each wire bit on the device clock; never alter a SensorFrame."""

    def __init__(self, milliseconds=10):
        if not math.isfinite(milliseconds) or milliseconds < 0:
            raise ValueError('显示确认时间必须是非负有限数')
        self.samples = math.ceil(milliseconds)
        self.last_frame = None
        self.stable = 0
        self.pending = {}
        self.transients = []

    def feed(self, frame):
        previous = self.last_frame
        self.last_frame = frame
        raw = int.from_bytes(frame.wire_payload, 'little')
        if (previous is None or previous.stream_id != frame.stream_id
                or previous.layout != frame.layout):
            self.transients = [0] * len(frame.layout.segments)
            self.pending.clear()
            self.stable = raw
        elif (frame.sample_index != previous.sample_index + 1 or frame.dropped_frames_before
              or any(flag != 'all_beams_blocked' for flag in frame.quality_flags)):
            self.pending.clear()
            self.stable = raw
        elif self.samples == 0:
            self.stable = raw
        else:
            changed = raw ^ self.stable
            for bit in tuple(self.pending):
                if not changed & (1 << bit):
                    del self.pending[bit]
                    self.transients[bit // 96] += 1
            while changed:
                mask = changed & -changed
                bit = mask.bit_length() - 1
                start, count = self.pending.get(bit, (frame.sample_index, 0))
                count += 1
                if count >= 3 and frame.sample_index - start >= self.samples:
                    self.stable ^= mask
                    self.pending.pop(bit, None)
                else:
                    self.pending[bit] = (start, count)
                changed ^= mask
        return self.stable.to_bytes(len(frame.wire_payload), 'little')


class GroundStabilityFilter:
    """10 ms per-beam confirmation with a bounded, backdated output stream.

    Prepared ground sessions start from a verified clear field. Eleven adjacent
    samples span 10 ms, matching BeamDisplayFilter's device-clock threshold.
    Held frames keep their original timestamps and unmodified wire payloads.
    Flushing marks unresolved tail beams invalid without confirming an event.
    """

    def __init__(self, layout, bad_indices=()):
        self.layout = layout
        self._stable = np.zeros(layout.bit_count, dtype=np.uint8)
        self._counts = np.zeros(layout.bit_count, dtype=np.uint8)
        self._bad = np.zeros(layout.bit_count, dtype=np.uint8)
        self._bad[list(bad_indices)] = 1
        self._last_partial = self._stable.copy()
        self._zero_counts = np.zeros(len(layout.segments), dtype=np.uint8)
        self._previous = None
        self._queue = deque()

    @staticmethod
    def _render(item):
        frame, bits = item
        flags = tuple(f for f in frame.quality_flags if f != 'all_beams_blocked')
        return replace(frame, contact_bits=bits.tobytes(), quality_flags=flags)

    def feed(self, frame):
        previous = self._previous
        fatal = (frame.layout != self.layout or (previous is not None and
                 (frame.stream_id != previous.stream_id or frame.sample_index <= previous.sample_index)))
        invalid = (len(frame.contact_bits) != self.layout.bit_count or
                   len(frame.valid_bits) != self.layout.bit_count or b'\x00' in frame.valid_bits or
                   any(f not in {'all_beams_blocked', 'frame_gap'} for f in frame.quality_flags))
        if fatal or invalid:
            ready = self.reset()
            self._previous = frame
            return ready + [frame]
        ready = []
        if frame.dropped_frames_before or (previous is not None and frame.sample_index != previous.sample_index + 1):
            ready = self.reset()
        self._previous = frame
        raw = np.frombuffer(frame.contact_bits, dtype=np.uint8).copy()
        # A brief whole-module dropout must not repeatedly cancel release
        # confirmation. Hold the last partial observation for at most 10 ms.
        whole_zero = np.all((raw | self._bad).reshape(-1, 96), axis=1)
        self._zero_counts[~whole_zero] = 0
        self._zero_counts[whole_zero] = np.minimum(self._zero_counts[whole_zero] + 1, 11)
        held = np.repeat(whole_zero & (self._zero_counts <= 10), 96)
        reliable = np.repeat(~whole_zero, 96)
        raw[held] = self._last_partial[held]
        self._last_partial[reliable] = raw[reliable]
        changed = raw != self._stable
        self._counts[changed] += 1
        self._counts[~changed] = 0
        sustained = np.repeat(self._zero_counts > 10, 96)
        self._counts[sustained & changed] = 11
        confirmed = self._counts > 10
        self._queue.append((frame, self._stable.copy()))
        if np.any(confirmed):
            self._stable[confirmed] = raw[confirmed]
            self._counts[confirmed] = 0
            # All queued samples belong to this confirmed 10 ms candidate.
            for _, bits in self._queue:
                bits[confirmed] = raw[confirmed]
        if len(self._queue) > 10:
            ready.append(self._render(self._queue.popleft()))
        return ready

    def flush(self):
        # Stopping cannot confirm an unfinished touch or release candidate.
        held_counts = np.where(self._zero_counts <= 10, self._zero_counts, 0)
        pending = np.maximum(self._counts, np.repeat(held_counts, 96))
        ready = []
        for index, item in enumerate(self._queue):
            frame = self._render(item)
            # Candidate counts locate only their suffix within the held queue.
            uncertain = pending >= len(self._queue) - index
            if np.any(uncertain):
                valid = np.frombuffer(frame.valid_bits, dtype=np.uint8).copy()
                valid[uncertain] = 0
                frame = replace(
                    frame, valid_bits=valid.tobytes(),
                    quality_flags=frame.quality_flags + ('unconfirmed_filter_tail',))
            ready.append(frame)
        self._queue.clear()
        return ready

    def reset(self):
        ready = self.flush()
        self._stable.fill(0)
        self._counts.fill(0)
        self._last_partial.fill(0)
        self._zero_counts.fill(0)
        self._previous = None
        return ready
