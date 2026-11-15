"""Bounded, device-clock inference for one person's overground observations.

Inferred bits are event-association aids, never replacement acquisition samples.
The constrained test assumes no complete event hidden inside a short gap. Gaps over ten samples or ambiguous footprints stay unknown.
"""
from collections import deque
from dataclasses import dataclass, field, replace
import math

from hardware.sensor_frame import blocked_indices


def classify_ground_frame(frame, bad_indices=()):
    """Mark dark modules and geometrically unavailable observations.

    The two-module premise is checked after isolated components are validated.
    """
    bad = set(bad_indices)
    occupied, dark, groups = [], [], []
    wide = set()
    for s in range(len(frame.layout.segments)):
        lo, hi = s * 96, (s + 1) * 96
        unavailable = [i for i in bad if lo <= i < hi]
        count = frame.contact_bits[lo:hi].count(1) - sum(frame.contact_bits[i] for i in unavailable)
        if count:
            occupied.append(s)
        if len(unavailable) < 96 and count == 96 - len(unavailable):
            dark.append(s)
        elif count:
            for offset in sorted(blocked_indices(frame.contact_bits[lo:hi])):
                i = lo + offset
                if i in bad:
                    continue
                if (groups and frame.layout.positions_m[i] - frame.layout.positions_m[groups[-1][-1]] <= .04):
                    groups[-1].append(i)
                else:
                    groups.append([i])
    hard = set()
    for i in bad:
        if i // 96 in dark:
            continue
        for j in (i - 1, i + 1):
            if (0 <= j < len(frame.contact_bits) and j not in bad and frame.contact_bits[j]
                    and abs(frame.layout.positions_m[i] - frame.layout.positions_m[j]) <= .04):
                group = next((g for g in groups if j in g), ())
                if not group or frame.layout.positions_m[group[-1]] - frame.layout.positions_m[group[0]] < .08:
                    hard.add(j // 96)
    reliable_groups = [g for g in groups if not any(i // 96 in hard for i in g)]
    for g in reliable_groups:
        if frame.layout.positions_m[g[-1]] - frame.layout.positions_m[g[0]] > .45:
            wide.update(i // 96 for i in g)
    unknown = set(dark) | wide | hard
    if not unknown:
        return frame
    valid = bytearray(frame.valid_bits)
    for s in unknown:
        valid[s * 96:(s + 1) * 96] = bytes(96)
    reason = ('segment_count_violation' if len(set(occupied) - set(dark)) > 2 else
              'segment_footprint_violation' if wide or len(groups) > 2 else 'segment_all_zero')
    flags = frame.quality_flags if reason in frame.quality_flags else frame.quality_flags + (reason,)
    flags += tuple(f'known_bad_boundary:{s}' for s in sorted(hard)
                   if f'known_bad_boundary:{s}' not in flags)
    return replace(frame, valid_bits=bytes(valid), quality_flags=flags)


@dataclass(frozen=True)
class EdgeEstimate:
    segment: int
    left_sample: int
    right_sample: int
    before: bytes
    after: bytes

    @property
    def sample(self):
        return (self.left_sample + self.right_sample) / 2


@dataclass
class GroundObservation:
    frame: object
    bits: bytearray
    unknown_segments: tuple
    unresolved_segments: set = field(default_factory=set)
    recovery_segments: set = field(default_factory=set)
    edges: list = field(default_factory=list)
    intervals: list = field(default_factory=list)
    pending: set = field(default_factory=set, repr=False)
    bad_indices: tuple = ()
    _measurement: object = field(default=None, repr=False)

    def reliable(self, low, high):
        return (not any(low <= i <= high for i in self.bad_indices)
                and all(self.frame.valid_bits[low:high + 1]))

    def release_reliable(self, low, high, margin_m):
        if not self.reliable(low, high):
            return False
        positions = self.frame.layout.positions_m
        left, right = sorted((positions[low], positions[high]))
        # A footprint may continue into a neighbouring unknown module. The
        # previous visible fragment clearing alone cannot prove the foot lifted.
        return not any(min(positions[s * 96], positions[(s + 1) * 96 - 1]) <= right + margin_m
                       and max(positions[s * 96], positions[(s + 1) * 96 - 1]) >= left - margin_m
                       for s in self.unknown_segments)

    def neighbour_unknown(self, low, high, margin_m):
        positions = self.frame.layout.positions_m
        left, right = sorted((positions[low], positions[high]))
        return any(not low // 96 <= s <= high // 96
                   and min(positions[s * 96], positions[(s + 1) * 96 - 1]) <= right + margin_m
                   and max(positions[s * 96], positions[(s + 1) * 96 - 1]) >= left - margin_m
                   for s in self.unknown_segments)

    def affected(self, low, high, segments=None):
        return any(s * 96 <= high and (s + 1) * 96 > low
                   and (segments is not None or b'\x00' in self.frame.valid_bits[max(low, s * 96):min(high + 1, (s + 1) * 96)])
                   for s in (self.unresolved_segments if segments is None else segments))

    def edge(self, low, high, blocked):
        matches = []
        for edge in self.edges:
            offset = edge.segment * 96
            for i in range(max(low, offset), min(high + 1, offset + 96)):
                j = i - offset
                if edge.before[j] != edge.after[j] and edge.after[j] == blocked:
                    matches.append(edge)
                    break
        return matches[0] if matches and len({e.sample for e in matches}) == 1 else None

    def associate_fragments(self, groups, contacts):
        """Join inner fragments only when one existing footprint owns them."""
        positions = self.frame.layout.positions_m
        owners = {}
        for j, (low, high) in enumerate(groups):
            matches = [c for c in contacts
                       if positions[low] <= positions[c.high] + .035
                       and positions[high] >= positions[c.low] - .035]
            if len(matches) == 1:
                c = matches[0]
                if (positions[low] >= positions[c.low] - .035
                        and positions[high] <= positions[c.high] + .035):
                    owners.setdefault(c.id, []).append(j)
        merged, consumed = {}, set()
        for indices in owners.values():
            if len(indices) > 1:
                merged[indices[0]] = (groups[indices[0]][0], groups[indices[-1]][1])
                consumed.update(indices[1:])
        return [merged.get(j, g) for j, g in enumerate(groups) if j not in consumed]

    def measurement_frame(self):
        if self._measurement is not None:
            return self._measurement
        flags = tuple(f for f in self.frame.quality_flags
                      if f not in {'segment_all_zero', 'segment_count_violation', 'segment_footprint_violation',
                                   'all_beams_blocked'} and not f.startswith('known_bad_boundary:'))
        self._measurement = (self.frame if self.frame.contact_bits == self.bits and flags == self.frame.quality_flags
                             else replace(self.frame, contact_bits=bytes(self.bits), quality_flags=flags))
        return self._measurement


class GroundObservationModel:
    MAX_GAP_MS = 10
    AUDIT_LIMIT = 10000

    def __init__(self, layout, bad_indices=(), match_margin_m=.035):
        self.layout, self.bad_indices = layout, tuple(bad_indices)
        self.match_margin_m = match_margin_m
        self._last = [None] * len(layout.segments)
        self._runs = {}
        self._queue = deque()
        self.audit = []
        self.interval_count = 0
        self._last_sample = None
        self._stream_id = None
        self._previous_unresolved = set()
        self._narrow_queue = deque()
        self._narrow_runs = []
        self._narrow_previous = {}

    def _compatible(self, before, after, segment):
        if before == after:
            return True
        # Allow clear->contact and contact->clear. For contact->contact require
        # unique overlap of every footprint; never average two different feet.
        def groups(bits):
            result = []
            for i, bit in enumerate(bits):
                if bit:
                    if result and (i - result[-1][-1]) * self.layout.segments[segment].pitch_m <= .04:
                        result[-1].append(i)
                    else:
                        result.append([i])
            return result
        left, right = groups(before), groups(after)
        if not left or not right:
            return len(left or right) <= 2
        if len(left) > 2 or len(right) > 2:
            return False
        pitch = self.layout.segments[segment].pitch_m
        margin = 3 * pitch if self.match_margin_m > .035 else self.match_margin_m
        used = set()
        unmatched = 0
        for g in left:
            candidates = [j for j, h in enumerate(right)
                          if (g[0] - h[-1]) * pitch <= margin
                          and (h[0] - g[-1]) * pitch <= margin
                          and abs((g[0] + g[-1] - h[0] - h[-1]) * pitch / 2) <= .18]
            if len(candidates) > 1 or (candidates and candidates[0] in used):
                return False
            if candidates:
                used.add(candidates[0])
            else:
                unmatched += 1
        return bool(used) and not (unmatched and len(used) < len(right))

    def _record(self, event):
        self.interval_count += 1
        if len(self.audit) < self.AUDIT_LIMIT:
            self.audit.append(event)

    def _finish_narrow(self, run, accepted):
        for item, indices in run['entries']:
            if not accepted:
                valid = bytearray(item.frame.valid_bits)
                for i in indices:
                    item.bits[i] = 0
                    valid[i] = 0
                item.frame = replace(item.frame, valid_bits=bytes(valid))
            item.pending.discard(id(run))
        self._record({'segment_index': run['low'] // 96, 'start_sample': run['start'],
                      'end_sample': run['entries'][-1][0].frame.sample_index + 1,
                      'recovered': True, 'reason': 'validated_narrow_candidate' if accepted else 'isolated_narrow_pulse'})

    def _filter_narrow(self, item):
        # Validate isolated components before using them as gap endpoints.
        # Missing samples neither confirm a component nor prove its release.
        # Waiting never erases an existing foot in the same module.
        groups = []
        positions = self.layout.positions_m
        visible = bytearray(item.bits)
        for s in range(len(self._last)):
            if b'\x01' not in item.frame.valid_bits[s * 96:(s + 1) * 96]:
                visible[s * 96:(s + 1) * 96] = bytes(96)
        for i in sorted(blocked_indices(visible)):
            if not item.frame.valid_bits[i]:
                continue
            if groups and positions[i] - positions[groups[-1][-1]] <= .04:
                groups[-1].append(i)
            else:
                groups.append([i])
        self._narrow_queue.append(item)
        used = set()
        next_runs = []
        for run in self._narrow_runs:
            matches = [j for j, g in enumerate(groups)
                       if positions[g[0]] <= positions[run['high']] + .04
                       and positions[g[-1]] >= positions[run['low']] - .04]
            if not matches and not item.reliable(run['low'], run['high']):
                run['missing'] += 1
                if run['missing'] <= self.MAX_GAP_MS and item.frame.sample_index - run['start'] <= 2 * self.MAX_GAP_MS:
                    run['entries'].append((item, ()))
                    item.pending.add(id(run))
                    next_runs.append(run)
                    continue
            if len(matches) != 1 or matches[0] in used:
                self._finish_narrow(run, False)
                continue
            j = matches[0]
            used.add(j)
            g = groups[j]
            run['entries'].append((item, tuple(g)))
            item.pending.add(id(run))
            run['low'], run['high'] = g[0], g[-1]
            run['missing'] = 0
            run['observed'] += 1
            if positions[g[-1]] - positions[g[0]] >= .08 or run['observed'] > self.MAX_GAP_MS:
                self._finish_narrow(run, True)
            elif item.frame.sample_index - run['start'] >= 2 * self.MAX_GAP_MS:
                self._finish_narrow(run, False)
            else:
                next_runs.append(run)
        for j, g in enumerate(groups):
            if j in used or positions[g[-1]] - positions[g[0]] >= .08:
                continue
            if any(positions[g[0]] <= positions[high] + .04 and positions[g[-1]] >= positions[low] - .04
                   for low, high in self._narrow_previous):
                continue
            run = {'low': g[0], 'high': g[-1], 'start': item.frame.sample_index,
                   'entries': [(item, tuple(g))], 'observed': 1, 'missing': 0}
            item.pending.add(id(run))
            next_runs.append(run)
        self._narrow_runs = next_runs
        pending_bounds = {(run['low'], run['high']) for run in next_runs}
        previous = {(low, high): seen for (low, high), seen in self._narrow_previous.items()
                    if item.frame.sample_index - seen <= self.MAX_GAP_MS
                    and b'\x00' in item.frame.valid_bits[low:high + 1]}
        previous.update({(g[0], g[-1]): item.frame.sample_index for g in groups
                         if (g[0], g[-1]) not in pending_bounds})
        self._narrow_previous = previous
        ready = []
        while self._narrow_queue and not self._narrow_queue[0].pending:
            ready.extend(self._feed_physical(self._narrow_queue.popleft()))
        return ready

    def _check_premise(self, item):
        # A reliable observation elsewhere in this same bounded interval can
        # disprove a module's interpolation. Carry that uncertainty through the
        # interval instead of letting it invalidate a different foot later.
        for event in item.intervals:
            if event['reason'] == 'inferred_segment_conflict':
                s = event['segment_index']
                item.bits[s * 96:(s + 1) * 96] = bytes(96)
                item.unresolved_segments.add(s)
        occupied = {s for s in range(len(self._last)) if b'\x01' in item.bits[s * 96:(s + 1) * 96]}
        if len(occupied) > 2:
            uncertain = occupied.intersection(item.unknown_segments)
            # Reliable modules constrain an interpolation in an erased module.
            # Only when the reliable evidence itself violates the premise must
            # all occupied modules remain ambiguous.
            affected = uncertain if uncertain and len(occupied - uncertain) <= 2 else occupied
            valid = bytearray(item.frame.valid_bits)
            for s in affected:
                item.bits[s * 96:(s + 1) * 96] = bytes(96)
                valid[s * 96:(s + 1) * 96] = bytes(96)
                item.unresolved_segments.add(s)
            item.frame = replace(item.frame, valid_bits=bytes(valid))
            for event in item.intervals:
                if event['segment_index'] in affected:
                    event['recovered'] = False
                    event['reason'] = 'inferred_segment_conflict'
            item.edges[:] = [edge for edge in item.edges if edge.segment not in affected]
        item.recovery_segments.update(self._previous_unresolved - item.unresolved_segments)
        self._previous_unresolved = set(item.unresolved_segments)
        return item

    def _resolve(self, s, run, right=None):
        entries, before = run['entries'], run['before']
        recover = (right is not None and before is not None and not run['expired']
                   and len(entries) <= self.MAX_GAP_MS
                   and right[0] - before[0] <= self.MAX_GAP_MS + 1
                   and self._compatible(before[1], right[1], s)
                   and (not run['boundary'] or bool(any(before[1])) == bool(any(right[1]))))
        event = {'segment_index': s, 'start_sample': run['start'],
                 'end_sample': right[0] if right else entries[-1].frame.sample_index + 1,
                 'recovered': recover, 'reason': 'bounded_unknown' if recover else
                 'unknown_timeout' if run['expired'] else 'missing_or_ambiguous_evidence'}
        if recover:
            event['edge_bounds_samples'] = [before[0], right[0]]
            event['state_relation'] = ('clear_clear' if not any(before[1]) and not any(right[1])
                                       else 'same_contact' if any(before[1]) and any(right[1]) else 'edge')
        edge = EdgeEstimate(s, before[0], right[0], before[1], right[1]) if recover else None
        for entry in entries:
            lo = s * 96
            if recover:
                inferred = edge.before if entry.frame.sample_index < edge.sample else edge.after
                entry.bits[lo:lo + 96] = inferred
                entry.intervals.append(event)
                if edge.before != edge.after and entry.frame.sample_index == math.ceil(edge.sample):
                    entry.edges.append(edge)
            else:
                entry.bits[lo:lo + 96] = bytes(96)
                entry.unresolved_segments.add(s)
            entry.pending.discard(s)
        self._record(event)
        run['event'] = event
        run['entries'] = []
        return edge

    def feed(self, frame, classified=False):
        ready = []
        if (frame.layout != self.layout or (self._last_sample is not None and
                (frame.sample_index <= self._last_sample or frame.stream_id != self._stream_id))):
            ready.extend(self.reset())
            ready.append(GroundObservation(frame, bytearray(frame.contact_bits), (), bad_indices=self.bad_indices))
            return ready
        if self._last_sample is not None and (
                frame.sample_index != self._last_sample + 1 or frame.dropped_frames_before
                or frame.stream_id != self._stream_id):
            ready.extend(self.reset())
        self._last_sample, self._stream_id = frame.sample_index, frame.stream_id
        if any(frame.contact_bits[i] for i in self.bad_indices):
            bits = bytearray(frame.contact_bits)
            for i in self.bad_indices:
                bits[i] = 0
            frame = replace(frame, contact_bits=bytes(bits))
        if not classified:
            frame = classify_ground_frame(frame, self.bad_indices)
        entry = GroundObservation(frame, bytearray(frame.contact_bits), (), bad_indices=self.bad_indices)
        ready.extend(self._filter_narrow(entry))
        return ready

    def _feed_physical(self, entry):
        frame = (entry.frame if entry.frame.contact_bits == entry.bits
                 else replace(entry.frame, contact_bits=bytes(entry.bits)))
        entry.frame = frame
        hard = {int(f.split(':')[1]) for f in frame.quality_flags if f.startswith('known_bad_boundary:')}
        unknown = tuple(s for s in range(len(self._last))
                        if b'\x01' not in frame.valid_bits[s * 96:(s + 1) * 96])
        entry.unknown_segments = unknown
        ready = []
        self._queue.append(entry)
        for s in range(len(self._last)):
            right = (frame.sample_index, frame.contact_bits[s * 96:(s + 1) * 96])
            if s in unknown:
                run = self._runs.setdefault(s, {'start': frame.sample_index, 'before': self._last[s],
                                                'entries': [], 'expired': False, 'boundary': s in hard})
                run['boundary'] |= s in hard
                if run['expired']:
                    run['event']['end_sample'] = frame.sample_index + 1
                    entry.bits[s * 96:(s + 1) * 96] = bytes(96)
                    entry.unresolved_segments.add(s)
                else:
                    entry.pending.add(s)
                    run['entries'].append(entry)
                    if len(run['entries']) > self.MAX_GAP_MS:
                        run['expired'] = True
                        self._resolve(s, run)
            else:
                run = self._runs.pop(s, None)
                if run is not None:
                    edge = self._resolve(s, run, right) if run['entries'] else None
                    if run.get('event'):
                        run['event']['end_sample'] = frame.sample_index
                    if edge and edge.before != edge.after and math.ceil(edge.sample) == frame.sample_index:
                        entry.edges.append(edge)
                    if edge is None:
                        entry.recovery_segments.add(s)
                self._last[s] = right
        while self._queue and not self._queue[0].pending:
            ready.append(self._check_premise(self._queue.popleft()))
        return ready

    def flush(self):
        """A stop/disconnect is not future clear evidence."""
        ready = []
        for run in self._narrow_runs:
            self._finish_narrow(run, False)
        self._narrow_runs.clear()
        while self._narrow_queue:
            ready.extend(self._feed_physical(self._narrow_queue.popleft()))
        for s, run in self._runs.items():
            if run['entries']:
                self._resolve(s, run)
        self._runs.clear()
        while self._queue:
            ready.append(self._check_premise(self._queue.popleft()))
        return ready

    def snapshot(self):
        return {'max_gap_ms': self.MAX_GAP_MS, 'max_occupied_segments': 2,
                'edge_estimator': 'bracketing_midpoint', 'interval_count': self.interval_count,
                'intervals': [dict(e) for e in self.audit],
                'truncated': self.interval_count > len(self.audit)}

    def reset(self):
        ready = self.flush()
        self._last = [None] * len(self._last)
        self._previous_unresolved.clear()
        self._narrow_previous.clear()
        self._last_sample = None
        self._stream_id = None
        return ready
