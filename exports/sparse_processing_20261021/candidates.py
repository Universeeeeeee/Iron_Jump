"""Isolated candidates. Import only after selecting the frozen source root."""
from collections import deque
import os

import numpy as np

from hardware.sensor_frame import _CONTACT_BYTE_BITS
from hardware.walking_preflight import RuntimeBeamEvidence


def enabled(variant, feature):
    if variant == 'combined':
        return feature in os.environ['IRON_SPARSE_FEATURES'].split(',')
    return variant == feature


class Decoder:
    def __init__(self, layout, variant='baseline'):
        self.layout, self.variant = layout, variant
        self.previous = None
        self.decoded = None
        self.parts = [None] * len(layout.segments)
        self.hits = self.segment_hits = 0
        self.delta = None

    def reset(self):
        self.previous = self.decoded = self.delta = None
        self.parts = [None] * len(self.layout.segments)

    def decode(self, payload):
        if len(payload) != self.layout.payload_bytes:
            raise ValueError('payload length does not match layout')
        if self.variant == 'baseline':
            return self.layout.contact_bits(payload)
        if self.variant == 'decode_full':
            if payload == self.previous:
                self.hits += 1
                return self.decoded
            self.previous = payload
            self.decoded = self.layout.contact_bits(payload)
            return self.decoded
        parts = []
        blocked = cleared = changed = 0
        for physical, segment in enumerate(self.layout.segments):
            offset = segment.wire_index * 12
            raw = payload[offset:offset + 12]
            old = None if self.previous is None else self.previous[offset:offset + 12]
            if raw == old:
                self.segment_hits += 1
                bits = self.parts[physical]
            else:
                bits = b''.join(_CONTACT_BYTE_BITS[b] for b in raw)
                if segment.reversed:
                    bits = bits[::-1]
                self.parts[physical] = bits
                if old is not None:
                    current_mask = (~int.from_bytes(raw, 'little')) & ((1 << 96) - 1)
                    old_mask = (~int.from_bytes(old, 'little')) & ((1 << 96) - 1)
                    delta = current_mask ^ old_mask
                    new_on, new_off = delta & current_mask, delta & old_mask
                    if segment.reversed:
                        delta = int(f'{delta:096b}'[::-1], 2)
                        new_on = int(f'{new_on:096b}'[::-1], 2)
                        new_off = int(f'{new_off:096b}'[::-1], 2)
                    changed |= delta << (physical * 96)
                    blocked |= new_on << (physical * 96)
                    cleared |= new_off << (physical * 96)
            parts.append(bits)
        self.delta = None if self.previous is None else (changed, blocked, cleared)
        self.previous = payload
        self.decoded = b''.join(parts)
        return self.decoded


class CancelledRuntime(RuntimeBeamEvidence):
    """Cancel equal incoming/outgoing contributions, including expired deltas."""
    def _reset(self):
        super()._reset()
        self._exp_signatures = deque()
        self._exp_zero = b''
        self._exp_count_skips = self._exp_transition_skips = 0

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
            self._exp_zero = bytes(len(bits))
            change_bytes = self._exp_zero
        elif frame.contact_bits == previous.contact_bits:
            change_bytes = self._exp_zero
        else:
            change_bytes = (bits ^ self._previous).tobytes()
        changes = np.frombuffer(change_bytes, dtype=np.uint8)
        old = self._window.popleft() if len(self._window) >= self.policy.samples else None
        old_signature = self._exp_signatures.popleft() if old is not None else (self._exp_zero, self._exp_zero)
        if frame.contact_bits != old_signature[0]:
            self._counts += bits
            if old is not None:
                self._counts -= old[0]
        else:
            self._exp_count_skips += 1
        if change_bytes != old_signature[1]:
            self._transitions += changes
            if old is not None:
                self._transitions -= old[1]
        else:
            self._exp_transition_skips += 1
        self._window.append((bits, changes))
        self._exp_signatures.append((frame.contact_bits, change_bytes))
        self._previous = bits
        self.healthy_samples = len(self._window)
        return True


class SegmentClusters:
    """Cache only spatial runs, stitch seams using the production geometry rule."""
    def __init__(self, processor):
        self.processor = processor
        self.layout = processor.device.layout
        self.positions = processor.positions
        self.parts = [None] * len(self.layout.segments)
        self.runs = [()] * len(self.layout.segments)
        self.hits = self.rebuilds = 0

    def __call__(self, bits):
        if (self.layout is not self.processor.device.layout
                or self.positions is not self.processor.positions):
            self.__init__(self.processor)
        # Match the existing empty-field fast path, without slicing eight parts.
        if b'\x01' not in bits:
            return []
        groups = []
        for s in range(len(self.parts)):
            part = bits[s * 96:(s + 1) * 96]
            if part != self.parts[s]:
                runs = []
                low = part.find(b'\x01')
                while low != -1:
                    end = part.find(b'\x00', low)
                    end = 96 if end == -1 else end
                    runs.append((s * 96 + low, s * 96 + end - 1))
                    low = part.find(b'\x01', end)
                self.runs[s] = tuple(runs)
                self.parts[s] = part
                self.rebuilds += 1
            else:
                self.hits += 1
            for low, high in self.runs[s]:
                previous = groups[-1][1] if groups else None
                adjacent = (previous is not None and low == previous + 1
                    and self.positions[low] - self.positions[previous] <= 1.5 * max(
                        self.layout.segments[low // 96].pitch_m,
                        self.layout.segments[previous // 96].pitch_m))
                if adjacent:
                    groups[-1] = (groups[-1][0], high)
                else:
                    groups.append((low, high))
        return groups


def idle_eligible(p, frame, observation=None, masked_contact=False):
    previous = p._previous_frame
    return (not p.finished_reason and observation is None and not masked_contact
        and previous is not None and not p.active and not p._narrow_candidates
        and not p._ownership_groups and not getattr(p, '_local_regions', ())
        and not p._recovering and not p._masked_contact_uncertain
        and p._commit_cursor == len(p.contacts)
        and frame.stream_id == p.device.stream_id and frame.layout == p.device.layout
        and frame.sample_index == p.last_sample + 1 and not frame.dropped_frames_before
        and not frame.quality_flags and not previous.quality_flags
        and len(frame.contact_bits) == len(p.positions)
        and len(frame.valid_bits) == len(p.positions) and b'\x00' not in frame.valid_bits
        and b'\x01' not in frame.contact_bits and b'\x01' not in previous.contact_bits)


def idle_step(p, frame):
    """Explicit reliable empty step; retain review evidence, commits and deadlines."""
    n = frame.sample_index
    p.last_sample, p.last_time = n, frame.sample_time_s
    if p.name == 'overground_running':
        p._current_frame = frame
        if p._duration_censored and p._duration_clear_upper is None:
            p._duration_clear_upper = n
        p._masked_contact_uncertain = False
        p._observe_ownership_groups([], frame)
        p._ambiguous = p._multiple_islands_now = False
        p._recover_ownership_groups()
        p._commit_contacts()
        p._recovering = False
        p._phase(n, 0)
        if p.origin is not None:
            if p._clear_since is None:
                p._clear_since = n
            if (p.config.has_auto_stop and p._exit_evidence
                    and n - p._clear_since + 1 >= p.config.exit_clear_ms):
                p.finished_reason = 'passage_complete'
        p._previous_frame = frame
        p._record_visual(frame)
    else:
        p._unlocalized_masked_contact = p._masked_contact_uncertain = False
        if p._duration_censored and p._duration_clear_upper is None:
            p._duration_clear_upper = n
        p._observe_ownership_groups((), frame)
        p._multiple_islands_now = p._ambiguous_now = False
        p._recover_ownership_groups()
        p._commit_contacts()
        p._recovering = False
        if p.origin is not None:
            if p.clear_since is None:
                p.clear_since = p.last_time
            if (p.config.has_auto_stop
                    and p.last_time - p.clear_since >= p.config.exit_clear_ms / 1000
                    and p._at_exit()):
                p.finished_reason = 'passage_complete'
        p._record_visual(frame)
        p._previous_frame = frame


def processor_class(base, variant):
    if variant not in {'idle', 'clusters', 'combined'}:
        return base
    do_clusters = enabled(variant, 'clusters')
    do_idle = enabled(variant, 'idle')

    class Candidate(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._exp_idle_hits = 0
            if do_clusters:
                self._exp_clusters = SegmentClusters(self)
                if self.name == 'overground_running':
                    self._groups = self._exp_clusters
                else:
                    self._clusters = self._exp_clusters

        def process(self, frame, observation=None, *, masked_contact=False):
            if do_idle and idle_eligible(self, frame, observation, masked_contact):
                self._exp_idle_hits += 1
                return idle_step(self, frame)
            return super().process(frame, observation, masked_contact=masked_contact)

    return Candidate


class RetirementShadow:
    """Counterfactual marks only; never filters or changes a measurement frame."""
    def __init__(self, layout):
        self.layout = layout
        self.clear_since = [None] * len(layout.segments)
        self.retired = set()
        self.direction = 0
        self.previous_frame = None
        self.frame_segments = self.eligible_segments = 0
        self.events = []

    def observe(self, p, frame):
        n = frame.sample_index
        previous = self.previous_frame
        continuous = (previous is None or (frame.stream_id == previous.stream_id
                      and frame.layout == previous.layout and n == previous.sample_index + 1))
        self.previous_frame = frame
        bad = bool(frame.quality_flags or frame.dropped_frames_before
                   or not continuous or frame.layout != self.layout
                   or len(frame.contact_bits) != self.layout.bit_count
                   or len(frame.valid_bits) != self.layout.bit_count
                   or b'\x00' in frame.valid_bits or p._recovering
                   or not getattr(p, '_identity_known', True)
                   or not p.direction or self.direction not in (0, p.direction))
        if bad:
            if self.retired:
                self.events.append({'sample': n, 'action': 'revoke_all'})
            self.retired.clear()
            self.clear_since = [None] * len(self.clear_since)
        self.direction = p.direction
        live = [(c.low, c.high) for c in p.active]
        live += [(q['low'], q['high']) for q in p._narrow_candidates]
        for g in p._ownership_groups:
            if g['tracking_ended_sample'] is None:
                live.extend(g['islands'])
        for g in getattr(p, '_local_regions', ()):
            live.append((g['low'], g['high']))
        confirmed = [c for c in p.contacts if c.confirmed and c.touch_known
                     and not getattr(c, 'exclusion', None) and not getattr(c, 'problem', None)
                     and not getattr(c, 'interrupted', None)]
        frontier = None
        if confirmed:
            frontier = (max(p.positions[c.low] for c in confirmed) if p.direction > 0
                        else min(p.positions[c.high] for c in confirmed))
        for s in range(len(self.clear_since)):
            lo, hi = s * 96, (s + 1) * 96 - 1
            blocked = b'\x01' in frame.contact_bits[lo:hi + 1]
            pending = any(a <= hi and b >= lo for a, b in live)
            if blocked or pending or bad:
                self.clear_since[s] = None
                if s in self.retired:
                    self.retired.remove(s)
                    self.events.append({'sample': n, 'segment': s, 'action': 'reactivate'})
            else:
                if self.clear_since[s] is None:
                    self.clear_since[s] = n
                behind = (frontier is not None and (p.positions[hi] < frontier if p.direction > 0
                                                    else p.positions[lo] > frontier))
                if behind and n - self.clear_since[s] >= max(10, p.config.release_ms):
                    if s not in self.retired:
                        self.events.append({'sample': n, 'segment': s, 'action': 'retire_mark'})
                    self.retired.add(s)
            assert not (blocked and s in self.retired), (n, s, 'missed reactivation')
        self.frame_segments += len(self.clear_since)
        self.eligible_segments += len(self.retired)
