"""Optical overground running, device-clock timing and toe-to-toe geometry.

A blocked beam is an optical proxy, not a measurement of ground reaction force.
Unobserved events never become zeros; only unresolved candidates block gait relationships.
"""
from dataclasses import dataclass, field

from config.overground_running_report import OvergroundRunningReport
from hardware.sensor_frame import blocked_indices


def metric(value=None, reason=None):
    return {"value": value, "valid": value is not None and reason is None,
            "missing_reason": reason if reason else ("not_observed" if value is None else None)}


@dataclass
class Contact:
    id: int
    epoch: int
    label: str
    side: str
    start: float
    last: int
    low: int
    high: int
    touch_known: bool
    end: float | None = None
    lift_known: bool = False
    confirmed: bool = False
    problem: str | None = None
    interrupted: str | None = None
    first_uncertain_sample: int | None = None
    first_masked_sample: int | None = None
    # Run-length encoded leading edges; unchanged stances take constant space.
    edges: list = field(default_factory=list)
    endpoint_run: int = 0
    observed_samples: int = 0
    absent_samples: int = 0
    release_start: float | None = None
    edge_estimates: dict = field(default_factory=dict)
    has_unknown: bool = False
    candidate_since: int | None = None
    last_reliable_sample: int | None = None
    first_seen_sample: int | None = None
    confirmed_sample: int | None = None
    candidate_outcome: str = "pending"
    isolated_clear: bool = False
    clear_before_candidate: int | None = None
    peak_width_m: float = 0.0


class OvergroundRunningProcessor:
    name = "overground_running"
    display_mode = "地面跑步"
    DIRECTION_DISPLACEMENT_M = .15
    CLUSTER_GAP_M = .04
    MATCH_MARGIN_M = .035
    MAX_CLUSTER_WIDTH_M = .45
    NARROW_CANDIDATE_WIDTH_M = .03

    def __init__(self, config, device):
        self.config, self.device = config, device
        self.positions = device.layout.positions_m
        self.contacts, self.active, self.issues, self.timeline = [], [], [], []
        self._preserved_stops = []
        self.phases = []  # [start, exclusive end, occupancy, epoch]
        self.epoch = 0
        self.origin = None
        self.last_sample = device.checked_sample_index
        self.last_time = None
        self.last_occupied = None
        self.direction = 0
        self.finished_reason = None
        self._identity_known = True
        self._recovering = False
        self._masked_contact_uncertain = False
        self._last_label = "B"
        self._clear_since = None
        self._exit_evidence = False
        self._exit_contact_id = None
        self._ambiguous = False
        self._last_visual = -100
        self._phase_adjustments = []
        self._duration_censored = False
        self._duration_start_censored = False
        self._duration_start_unknown_from = None
        self._duration_clear_upper = None
        self._narrow_candidates = []
        self._narrow_unknown = []
        self._narrow_barriers = []
        self._exit_blocked_through_id = -1
        self._previous_frame = None
        self._candidate_decisions = []
        self._commit_cursor = 0
        self._suspended_exit = None

    def break_continuity(self, code, frame_index=None):
        self._preserved_stops = self._stop_intervals()
        self.issues.append({"code": code, "sample": self.last_sample, "frame_index": frame_index})
        if self.origin is not None:
            self.timeline.append({"timestamp_s": (self.last_sample + 1) / 1000 - self.origin,
                                  "positions_m": self.positions, "contact_bits": [0] * len(self.positions),
                                  "valid_bits": [0] * len(self.positions), "feet": [], "quality_flags": [code]})
        for c in self.active:
            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
            if not c.confirmed and c.candidate_outcome == "pending":
                c.candidate_outcome = "unresolved"
                self._record_candidate(c, "unresolved", code)
            c.interrupted = code
        self.active.clear()
        self.epoch += 1
        self._identity_known = False
        self._recovering = True
        self._last_label = "B"
        self._clear_since = None
        self._exit_evidence = False
        self._exit_contact_id = None
        for p in self._narrow_candidates:
            self._mark_unknown_start(p['start'])
            self._narrow_unknown.append((p['start'], p['last'] + 1, self.epoch - 1))
            self._record_candidate(p, 'unresolved', code)
        self._narrow_candidates.clear()
        self._previous_frame = None
        self._suspended_exit = None

    def _mark_unknown_start(self, sample, touch_bounds=None):
        if self.origin is None:
            if touch_bounds is not None:
                sample = touch_bounds[0]
            self._duration_start_censored = True
            if self._duration_start_unknown_from is None or sample < self._duration_start_unknown_from:
                self._duration_start_unknown_from = sample

    def _local_clear(self, frame, low, high):
        if frame is None:
            return False
        left = self.positions[low] - self.MATCH_MARGIN_M
        right = self.positions[high] + self.MATCH_MARGIN_M
        if left < self.positions[0] or right > self.positions[-1]:
            return False
        indices = [i for i, pos in enumerate(self.positions) if left <= pos <= right]
        return (not any(i in self.device.bad_indices for i in indices)
                and all(frame.valid_bits[i] and not frame.contact_bits[i] for i in indices))

    def _candidate_row(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        if isinstance(candidate, Contact):
            row = {"source": "contact", "contact_id": candidate.id, "epoch": candidate.epoch,
                   "first_sample": candidate.first_seen_sample,
                   "last_sample": candidate.last, "observed_samples": candidate.observed_samples,
                   "low": candidate.low, "high": candidate.high, "peak_width_m": candidate.peak_width_m}
        else:
            row = {"source": "narrow", "epoch": self.epoch, "first_sample": candidate['start'],
                   "last_sample": candidate['last'], "observed_samples": candidate['samples'],
                   "low": candidate['low'], "high": candidate['high'], "peak_width_m": candidate.get('peak_width_m', 0)}
        row.update(outcome=outcome, reason=reason, closed_sample=closed_sample)
        if owner_id is not None:
            row['owner_id'] = owner_id
        return row

    def _record_candidate(self, candidate, outcome, reason, closed_sample=None, owner_id=None):
        self._candidate_decisions.append(self._candidate_row(candidate, outcome, reason, closed_sample, owner_id))

    def _unresolve_candidate(self, c, reason):
        if not c.confirmed and c.candidate_outcome == 'pending':
            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
            c.candidate_outcome = 'unresolved'
            self._record_candidate(c, 'unresolved', reason)

    def _exclude_nonstep(self, start, end, epoch, clear_before):
        # The declared non-step observation never represented support. Correct
        # only its own occupancy interval; do not fill neighbouring unknowns.
        phases = []
        for a, b, count, ep in self.phases:
            points = sorted({a, b, *[x for x in (start, end) if a < x < b]})
            for left, right in zip(points, points[1:]):
                value = count - int(ep == epoch and start <= left < end and count > 0)
                if phases and phases[-1][1:] == [left, value, ep]:
                    phases[-1][1] = right
                else:
                    phases.append([left, right, value, ep])
        self.phases = phases
        if self.last_occupied == end - 1:
            occupied = [c.last for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}
                        and c.interrupted != 'masked_contact_boundary']
            occupied += [q['last'] for q in self._narrow_candidates if q['start'] != start]
            self.last_occupied = max(occupied, default=None)
        if (clear_before is not None and epoch == self.epoch
                and not any(x['sample'] >= clear_before for x in self.issues)):
            self._clear_since = max(clear_before, (self.last_occupied + 1) if self.last_occupied is not None else clear_before)

    def _suspend_exit(self):
        if self._exit_evidence and self._suspended_exit is None:
            self._suspended_exit = (self._exit_contact_id, self._exit_blocked_through_id, self._clear_since)
        self._exit_evidence = False

    def _commit_contacts(self):
        # Confirmation publishes own event evidence. Identity waits for earlier
        # candidates to close and never advances for an excluded non-step.
        while self._commit_cursor < len(self.contacts):
            c = self.contacts[self._commit_cursor]
            if any(q['start'] < c.start for q in self._narrow_candidates):
                break
            if not c.confirmed and c.end is None and not c.problem and not c.interrupted:
                break
            self._commit_cursor += 1
            if not c.confirmed or c.problem == 'unresolved_coalescence':
                continue
            self._last_label = 'A' if self._last_label == 'B' else 'B'
            c.label = self._last_label
            side = {"Left": "left", "Right": "right"}.get(self.config.starting_foot, "unknown")
            if not self._identity_known:
                side = 'unknown'
            elif c.label == 'B' and side != 'unknown':
                side = 'right' if side == 'left' else 'left'
            c.side = side
            prior = [x for x in self.contacts[:c.id] if x.confirmed and x.label and x.epoch == c.epoch and not x.problem]
            if any(x.label == c.label and x.last >= c.start for x in prior):
                c.problem, c.side = 'identity_uncertain', 'unknown'
                self._identity_known = False
            if prior and c.touch_known and not c.problem:
                prev = prior[-1]
                delta = (self.positions[c.low] + self.positions[c.high]
                         - self.positions[prev.low] - self.positions[prev.high]) / 2
                if abs(delta) >= self.DIRECTION_DISPLACEMENT_M:
                    if self.direction and delta * self.direction < 0:
                        c.problem = self.finished_reason = 'turn_detected'
                    elif prev.touch_known:
                        self.direction = 1 if delta > 0 else -1
        if self._suspended_exit is not None and not self._narrow_candidates:
            owner, blocked, clear = self._suspended_exit
            sequence = [c for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}]
            if (sequence and sequence[-1].id == owner and not sequence[-1].problem
                    and not sequence[-1].interrupted and all(c.candidate_outcome == 'excluded_nonstep'
                                                            for c in self.contacts[owner + 1:])):
                self._exit_evidence, self._exit_contact_id = True, owner
                self._exit_blocked_through_id = blocked
                if clear is not None:
                    self._clear_since = clear
                self._suspended_exit = None
            elif any(c.id > owner and (c.confirmed or c.problem or c.interrupted) for c in self.contacts):
                self._suspended_exit = None

    def _defer_narrow_candidates(self, groups, n, masked_groups=()):
        # Known optical owners can retain an isolated new island pending local
        # evidence. This gate never imposes a minimum width for a running foot.
        def matches(low, high, candidates):
            return [c for c in candidates
                    if self.positions[low] <= self.positions[c['high']] + self.MATCH_MARGIN_M
                    and self.positions[high] >= self.positions[c['low']] - self.MATCH_MARGIN_M]
        pending = []
        for p in self._narrow_candidates:
            visible = any(matches(low, high, [p]) for low, high in groups)
            if not visible:
                p['isolated_clear'] &= self._local_clear(self._current_frame, p['low'], p['high'])
            if n - p['last'] < self.config.release_ms or (visible and n - p['last'] <= self.config.release_ms):
                pending.append(p)
            else:
                excluded = p['samples'] == 1 and p['low'] == p['high'] and p['isolated_clear'] and not p.get('clear_gaps')
                self._record_candidate(p, 'excluded_nonstep' if excluded else 'unresolved',
                                       'closed_isolated_single_sample' if excluded else 'short_narrow_contact', n)
                if excluded:
                    self._exclude_nonstep(p['start'], p['last'] + 1, self.epoch, p.get('clear_before_candidate'))
                else:
                    self._mark_unknown_start(p['start'])
                    self._narrow_unknown.append((p['start'], p['last'] + 1, self.epoch))
                    self._narrow_barriers.append((p['start'], p['last'] + 1, self.epoch))
                    self._identity_known = False
                    self._suspended_exit = None
        owners = [[c for c in self.active
                   if self.positions[low] <= self.positions[c.high] + self.MATCH_MARGIN_M
                   and self.positions[high] >= self.positions[c.low] - self.MATCH_MARGIN_M]
                  for low, high in groups]
        anchored = any(len(cs) == 1 and cs[0].confirmed and not cs[0].problem
                       and not cs[0].interrupted for cs in owners)
        immature_owner = any(len(cs) == 1 and not cs[0].interrupted
                             and cs[0].problem in {None, 'simultaneous_contacts', 'unresolved_coalescence'} for cs in owners)
        # A later wide contact cannot overtake an earlier pending touch in the
        # contact sequence. Promote the earlier candidates with their own times.
        force = any(not cs and (any(self.positions[low] <= self.positions[h] and self.positions[high] >= self.positions[l]
                                   for l, h in masked_groups)
                                or self.positions[high] - self.positions[low] >= self.NARROW_CANDIDATE_WIDTH_M
                                or self.positions[low] == self.positions[0]
                                or self.positions[high] == self.positions[-1])
                    for (low, high), cs in zip(groups, owners))
        kept, seeds, consumed, ambiguous = [], {}, set(), False
        for (low, high), cs in zip(groups, owners):
            ps = matches(low, high, pending)
            if len(ps) > 1:
                ambiguous = True
                kept.append((low, high))
                continue
            p = ps[0] if ps else None
            if cs:
                kept.append((low, high))
                if p is not None:
                    if len(cs) != 1 or not cs[0].confirmed:
                        ambiguous = True
                        continue
                    self._narrow_unknown.append((p['start'], p['last'] + 1, self.epoch))
                    self._record_candidate(p, 'associated_fragment', 'joined_existing_footprint', n, cs[0].id if len(cs) == 1 else None)
                    consumed.add(id(p))
                    self._suspended_exit = None
                continue
            boundary = self.positions[low] == self.positions[0] or self.positions[high] == self.positions[-1]
            width = self.positions[high] - self.positions[low]
            if (p is None and not force and not boundary and width < self.NARROW_CANDIDATE_WIDTH_M
                    and (anchored or (immature_owner and low == high
                                      and self._local_clear(self._previous_frame, low, high)))):
                p = {'start': n, 'last': n - 1, 'low': low, 'high': high,
                     'samples': 0, 'edges': [], 'touch_known': not self._recovering,
                     'isolated_clear': (not self._recovering and self._previous_frame is not None
                                        and self._previous_frame.sample_index == n - 1
                                        and self._local_clear(self._previous_frame, low, high)),
                     'clear_before_candidate': self._clear_since, 'clear_gaps': [], 'peak_width_m': width}
                pending.append(p)
                self._suspend_exit()
                self._exit_blocked_through_id = len(self.contacts) - 1
            if p is None:
                kept.append((low, high))
                continue
            p['peak_width_m'] = max(p.get('peak_width_m', 0), width)
            if p['samples'] and n > p['last'] + 1:
                p['clear_gaps'].append((p['last'] + 1, n))
            if (force or (not anchored and not immature_owner) or boundary or width >= self.NARROW_CANDIDATE_WIDTH_M
                    or n - p['start'] + 1 >= max(self.config.min_contact_time, self.config.confirmation_ms)):
                kept.append((low, high))
                seeds[(low, high)] = p
                consumed.add(id(p))
            else:
                p.update(last=n, low=low, high=high, samples=p['samples'] + 1)
                if p['edges'] and p['edges'][-1][1:] == [n, low, high]:
                    p['edges'][-1][1] = n + 1
                else:
                    p['edges'].append([n, n + 1, low, high])
        self._narrow_candidates = [p for p in pending if id(p) not in consumed]
        return kept, seeds, ambiguous

    def _coalesce_immature_islands(self, groups, n, affected):
        # A briefly coalescing optical group retains evidence but cannot establish
        # a foot identity or per-foot event/position. Mature fusion stays ambiguous.
        for low, high in groups:
            if (self.positions[high] - self.positions[low] > self.MAX_CLUSTER_WIDTH_M
                    or any(self.positions[low] <= self.positions[h] and self.positions[high] >= self.positions[l]
                           for l, h in affected)):
                continue
            cs = [c for c in self.active if self.positions[low] <= self.positions[c.high] + self.MATCH_MARGIN_M
                  and self.positions[high] >= self.positions[c.low] - self.MATCH_MARGIN_M]
            ps = [q for q in self._narrow_candidates if self.positions[low] <= self.positions[q['high']] + self.MATCH_MARGIN_M
                  and self.positions[high] >= self.positions[q['low']] - self.MATCH_MARGIN_M]
            if len(cs) + len(ps) != 2:
                continue
            evidence = []
            for c in cs:
                if (c.confirmed or c.problem or c.interrupted or not c.touch_known
                        or c.last != n - 1 or c.epoch != self.epoch):
                    break
                evidence.append((c.start, c.last, c.peak_width_m, c.observed_samples, c.edges, c))
            else:
                for q in ps:
                    if not q['touch_known'] or q.get('clear_gaps') or q['last'] != n - 1:
                        break
                    evidence.append((q['start'], q['last'], q.get('peak_width_m', 0), q['samples'], q['edges'], q))
                else:
                    if len(evidence) == 2:
                        evidence.sort(key=lambda r: r[0])
                        first, second = evidence
                        if (0 < second[0] - first[0] <= self.config.confirmation_ms
                                and n - first[0] <= self.config.confirmation_ms
                                and all(r[2] < self.NARROW_CANDIDATE_WIDTH_M for r in evidence)):
                            parent = first[5] if isinstance(first[5], Contact) else None
                            # Preserve the two original islands before modifying their owner.
                            source_rows = [self._candidate_row(r[5], 'associated_fragment', 'immature_islands_coalesced', n)
                                           for r in evidence]
                            if parent is None:
                                parent = Contact(len(self.contacts), self.epoch, '', 'unknown', first[0], first[1],
                                                 low, high, False, observed_samples=first[3], edges=list(first[4]),
                                                 first_seen_sample=first[0])
                                self.contacts.append(parent)
                                self.active.append(parent)
                            for row, r in zip(source_rows, evidence):
                                row.pop('contact_id', None)
                                row.update(source='immature_island', source_id=f"{self.epoch}:{r[0]}:{row['low']}:{row['high']}",
                                           owner_id=parent.id)
                                self._candidate_decisions.append(row)
                            for c in cs:
                                if c is not parent:
                                    c.candidate_outcome, c.problem = 'associated_fragment', 'associated_fragment'
                                    self.active.remove(c)
                            self._narrow_candidates = [q for q in self._narrow_candidates if all(q is not r[5] for r in evidence)]
                            parent.problem, parent.touch_known, parent.side = 'unresolved_coalescence', False, 'unknown'
                            parent.candidate_outcome = 'unresolved_group'
                            parent.peak_width_m = self.positions[high] - self.positions[low]
                            self._identity_known = False
                            self._suspended_exit = None
                            self._exit_evidence = False
                            self._mark_unknown_start(first[0])

    def _groups(self, bits):
        if b'\x01' not in bits:
            return []
        groups = []
        # Sort by actual geometry, including reversed segments and custom wire order.
        for i in sorted(blocked_indices(bits), key=self.positions.__getitem__):
            if groups and self.positions[i] - self.positions[groups[-1][-1]] <= self.CLUSTER_GAP_M:
                groups[-1].append(i)
            else:
                groups.append([i])
        return [(g[0], g[-1]) for g in groups]

    def _associate_inner_fragments(self, groups):
        # A known footprint may separate into heel/toe islands. Associate only
        # islands supported by one existing envelope, never two tracked feet.
        # An inner island anchors association while a rolling edge may move
        # within the same margin already used for ordinary contact matching.
        owners, anchored = {}, set()
        for index, (low, high) in enumerate(groups):
            lo, hi = self.positions[low], self.positions[high]
            candidates = [c for c in self.active
                          if lo <= self.positions[c.high] + self.MATCH_MARGIN_M
                          and hi >= self.positions[c.low] - self.MATCH_MARGIN_M]
            if (len(candidates) == 1
                    and self.positions[candidates[0].low] - self.MATCH_MARGIN_M <= lo
                    and hi <= self.positions[candidates[0].high] + self.MATCH_MARGIN_M):
                c = candidates[0]
                owners.setdefault(c.id, []).append(index)
                if self.positions[c.low] <= lo and hi <= self.positions[c.high]:
                    anchored.add(c.id)
        merged, consumed = [], set()
        for owner, indices in owners.items():
            if len(indices) > 1 and owner in anchored:
                merged.append((groups[indices[0]][0], groups[indices[-1]][1]))
                consumed.update(indices)
        return sorted(merged + [g for i, g in enumerate(groups) if i not in consumed],
                      key=lambda g: self.positions[g[0]])

    def process(self, frame, observation=None, *, masked_contact=False):
        if self.finished_reason:
            return
        if observation is not None:
            frame = observation.measurement_frame()
        if frame.stream_id != self.device.stream_id or frame.layout != self.device.layout:
            self.break_continuity("device_changed", frame.frame_index)
            self.finished_reason = "device_changed"
            return
        n = frame.sample_index
        if n <= self.last_sample:
            self.break_continuity("counter_reset", frame.frame_index)
            self.finished_reason = "counter_reset"
            return
        if n != self.last_sample + 1 or frame.dropped_frames_before:
            self.break_continuity("frame_gap", frame.frame_index)
        self.last_sample, self.last_time = n, frame.sample_time_s
        self._current_frame = frame
        if (len(frame.contact_bits) != len(self.positions) or len(frame.valid_bits) != len(self.positions)
                or (observation is None and not all(frame.valid_bits))
                or any(x != "frame_gap" for x in frame.quality_flags)):
            self.break_continuity("invalid_sample", frame.frame_index)
            return
        raw_groups = self._groups(frame.contact_bits)
        affected = [(low, high) for low, high in raw_groups if any(
            0 <= j < len(self.positions) and frame.contact_bits[j]
            and abs(self.positions[j] - self.positions[i]) <= .04
            and self.positions[low] <= self.positions[j] <= self.positions[high]
            for i in self.device.bad_indices for j in (i - 1, i + 1))] if masked_contact else []
        if masked_contact:
            self._duration_censored = True
            self._mark_unknown_start(n)
            self._duration_clear_upper = None
            if not affected:
                if not self._masked_contact_uncertain or self.active or self._narrow_candidates:
                    self.break_continuity("masked_contact_boundary", frame.frame_index)
                self._masked_contact_uncertain = True
                return
            if not self._masked_contact_uncertain:
                self.issues.append({"code": "masked_contact_boundary", "sample": n,
                                    "frame_index": frame.frame_index})
            self._identity_known = False
            self._exit_evidence = False
            self._exit_contact_id = None
            self._suspended_exit = None
        self._masked_contact_uncertain = masked_contact
        if (self._duration_censored and self._duration_clear_upper is None
                and b'\x01' not in frame.contact_bits and b'\x00' not in frame.valid_bits
                and (observation is None or not observation.unresolved_segments)):
            self._duration_clear_upper = n
        if observation is not None:
            if observation.unresolved_segments:
                self._duration_censored = True
                self._duration_clear_upper = None
            for c in list(self.active):
                if observation.affected(c.low, c.high):
                    self._preserved_stops = self._stop_intervals()
                    self._unresolve_candidate(c, 'local_unknown_timeout')
                    c.interrupted = 'local_unknown_timeout'
                    self.active.remove(c)
                    self._identity_known = False
            for c in list(self.active):
                if (c.interrupted != 'local_unknown_timeout' and ((not c.confirmed and c.has_unknown
                     and n - c.start >= max(self.config.min_contact_time, self.config.confirmation_ms) + 10)
                        or (c.candidate_since is not None
                            and n - c.candidate_since >= self.config.release_ms + 10))):
                    self._preserved_stops = self._stop_intervals()
                    self._unresolve_candidate(c, 'local_unknown_timeout')
                    c.interrupted = 'local_unknown_timeout'
                    self._identity_known = False
        if not masked_contact and raw_groups:
            self.last_occupied = n
        groups = raw_groups
        if observation is not None:
            groups = observation.associate_fragments(groups, self.active)
        else:
            groups = self._associate_inner_fragments(groups)
        self._coalesce_immature_islands(groups, n, affected)
        occupancy = len(groups)
        seeds, pending_ambiguous = {}, False
        if observation is None:
            groups, seeds, pending_ambiguous = self._defer_narrow_candidates(groups, n, affected)
        matches, used = [], set()
        ambiguous = len(groups) > 2 or pending_ambiguous
        for low, high in groups:
            lo, hi = self.positions[low], self.positions[high]
            candidates = [c for c in self.active
                          if lo <= self.positions[c.high] + self.MATCH_MARGIN_M and hi >= self.positions[c.low] - self.MATCH_MARGIN_M]
            ambiguous |= len(candidates) > 1 or hi - lo > self.MAX_CLUSTER_WIDTH_M
            c = candidates[0] if len(candidates) == 1 else None
            if c:
                ambiguous |= c.id in used
                used.add(c.id)
            matches.append((low, high, c))
        if ambiguous:
            self._mark_unknown_start(n)
            for q in seeds.values():
                self._mark_unknown_start(q['start'])
                self._record_candidate(q, 'unresolved', 'ambiguous_contacts')
            if not self._ambiguous:
                self.break_continuity("ambiguous_contacts", frame.frame_index)
            self._ambiguous = True
            self._phase(n, -1)
            return
        self._ambiguous = False
        low_edge, high_edge = self.positions[0], self.positions[-1]
        observed = set()
        new = []
        matches.sort(key=lambda x: seeds.get((x[0], x[1]), {}).get('start', n))
        for low, high, c in matches:
            if c is None:
                boundary = self.positions[low] == low_edge or self.positions[high] == high_edge
                c = Contact(len(self.contacts), self.epoch, "", "unknown", n, n, low, high,
                            not self._recovering and not boundary)
                c.first_seen_sample = n
                c.clear_before_candidate = self._clear_since
                c.isolated_clear = (observation is None and not self._recovering and self._previous_frame is not None
                                    and self._previous_frame.sample_index == n - 1
                                    and self._local_clear(self._previous_frame, low, high))
                seed = seeds.get((low, high))
                if seed is not None:
                    c.start, c.touch_known = seed['start'], seed['touch_known']
                    c.first_seen_sample = seed['start']
                    c.observed_samples, c.edges = seed['samples'], list(seed['edges'])
                    c.peak_width_m = seed.get('peak_width_m', 0)
                    c.isolated_clear = seed.get('isolated_clear', False)
                    c.clear_before_candidate = seed.get('clear_before_candidate')
                    if seed.get('clear_gaps'):
                        c.problem = 'uncertain_short_clear'
                        c.first_uncertain_sample = seed['clear_gaps'][0][0]
                        self._identity_known = False
                if observation is not None:
                    edge = observation.edge(low, high, 1)
                    if edge:
                        c.start = edge.sample
                        c.edge_estimates['touch'] = [edge.left_sample, edge.right_sample]
                        if c.start < n:
                            self._phase_adjustments.append((c.start, n, 1, c.epoch))
                    if observation.affected(low, high, observation.recovery_segments):
                        c.touch_known = False
                if not c.touch_known or c.problem:
                    self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                self._suspend_exit()
                self.contacts.append(c)
                self.active.append(c)
                new.append(c)
            if any(self.positions[low] <= self.positions[h] and self.positions[high] >= self.positions[l]
                   for l, h in affected):
                if c.first_masked_sample is None:
                    c.first_masked_sample = n
                    self._unresolve_candidate(c, 'masked_contact_boundary')
                    self._preserved_stops = self._stop_intervals()
                if c in new:
                    c.touch_known = False
                c.interrupted = 'masked_contact_boundary'
                c.side = 'unknown'
            observed.add(c.id)
            if c.last < n - 1 and c.release_start is not None:
                # A sub-confirmation clear interval cannot silently count as continuous support.
                self._preserved_stops = self._stop_intervals()
                c.problem = c.problem or "uncertain_short_clear"
                self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                if c.first_uncertain_sample is None:
                    c.first_uncertain_sample = c.last + 1
                self._identity_known = False
                for contact in self.contacts[c.id:]:
                    contact.side = "unknown"
            c.last, c.low, c.high = n, low, high
            c.peak_width_m = max(c.peak_width_m, self.positions[high] - self.positions[low])
            reliable = observation is None or observation.reliable(low, high)
            c.observed_samples += int(reliable and not c.interrupted)
            if reliable:
                c.last_reliable_sample = n
            if reliable:
                c.absent_samples = 0
                c.release_start = None
                c.candidate_since = None
                if c.edges and c.edges[-1][1] == n and c.edges[-1][2:] == [low, high]:
                    c.edges[-1][1] = n + 1
                else:
                    c.edges.append([n, n + 1, low, high])
            if observation is not None:
                c.has_unknown |= observation.affected(low, high, observation.unknown_segments) or bool(observation.edge(low, high, 1))
            if (not c.interrupted and n - c.start + 1 >= max(self.config.confirmation_ms, self.config.min_contact_time)
                    and c.observed_samples >= self.config.confirmation_ms):
                if not c.confirmed:
                    c.confirmed = True
                    c.confirmed_sample = n
                    c.candidate_outcome = "unresolved_group" if c.problem == "unresolved_coalescence" else "confirmed_contact"
                    if self.origin is None and c.touch_known and not c.problem:
                        self.origin = c.start / 1000
                        upper = c.edge_estimates.get('touch', [c.start, c.start])[1]
                        if (c.touch_known and self._duration_start_unknown_from is not None
                                and upper < self._duration_start_unknown_from):
                            self._duration_start_censored = False
            self._commit_contacts()
            endpoint = high_edge if self.direction > 0 else low_edge
            at_exit = self.direction and (self.positions[high] == endpoint or self.positions[low] == endpoint)
            if reliable:
                c.endpoint_run = c.endpoint_run + 1 if at_exit else 0
            if (reliable and c.confirmed and not c.problem and not c.interrupted
                    and c.id > self._exit_blocked_through_id
                    and c.endpoint_run >= self.config.confirmation_ms):
                self._exit_evidence = True
                self._exit_contact_id = c.id
        # Rolling within the same tracked contact does not revoke its confirmed
        # terminal-beam evidence. Earlier support may overlap, but a later
        # contact cannot inherit or reestablish the older contact's proof.
        if (new or (self._exit_contact_id is not None
                    and self._exit_contact_id != next((c.id for c in reversed(self.contacts)
                                                      if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}), None))
                or any(c.id == self._exit_contact_id and (c.problem or c.interrupted)
                       for c in self.active)):
            self._exit_evidence = False
        if len(new) > 1:
            self._identity_known = False
            for c in new:
                self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                c.side, c.problem = "unknown", "simultaneous_contacts"
        for c in list(self.active):
            if c.id not in observed:
                if not c.confirmed:
                    c.isolated_clear &= observation is None and self._local_clear(frame, c.low, c.high)
                if c.interrupted == 'local_unknown_timeout':
                    if observation.reliable(c.low, c.high):
                        self.active.remove(c)
                    continue
                c.endpoint_run = 0
                reliable = observation is None or observation.release_reliable(c.low, c.high, self.MATCH_MARGIN_M)
                edge = observation.edge(c.low, c.high, 0) if observation is not None else None
                if (observation is not None and observation.neighbour_unknown(
                        c.low, c.high, self.MATCH_MARGIN_M)):
                    edge = None
                if observation is not None and c.candidate_since is None:
                    c.candidate_since = n
                if c.release_start is None and (reliable or edge):
                    c.release_start = c.last + 1
                    if observation is not None and not edge and n > c.candidate_since:
                        left = c.last_reliable_sample
                        if left is None or n - left > 11:
                            self._preserved_stops = self._stop_intervals()
                            c.release_start = None
                            self._unresolve_candidate(c, 'local_unknown_timeout')
                            c.interrupted = 'local_unknown_timeout'
                            self.active.remove(c)
                            self._identity_known = False
                            continue
                        c.release_start = (left + n) / 2
                        c.edge_estimates['lift'] = [left, n]
                    if not edge and c.release_start < n:
                        self._phase_adjustments.append((c.release_start, n, -1, c.epoch))
                if edge:
                    c.release_start = edge.sample
                    c.edge_estimates['lift'] = [edge.left_sample, edge.right_sample]
                    if edge.sample < n:
                        self._phase_adjustments.append((edge.sample, n, -1, c.epoch))
                if reliable:
                    c.absent_samples += 1
                if c.absent_samples >= self.config.release_ms:
                    c.end = c.release_start if c.interrupted != 'masked_contact_boundary' else None
                    c.lift_known = not c.interrupted and self.positions[c.low] != low_edge and self.positions[c.high] != high_edge
                    if not c.confirmed:
                        excluded = (c.observed_samples == 1 and c.low == c.high and c.isolated_clear
                                    and not c.problem and not c.interrupted and not c.has_unknown)
                        previous_outcome = c.candidate_outcome
                        c.candidate_outcome = 'excluded_nonstep' if excluded else 'unresolved'
                        c.problem = c.problem or c.interrupted or ('excluded_nonstep' if excluded else 'short_contact')
                        if previous_outcome != 'unresolved':
                            self._record_candidate(c, c.candidate_outcome, c.problem, n)
                        if excluded:
                            self._exclude_nonstep(c.start, c.last + 1, c.epoch, c.clear_before_candidate)
                        else:
                            self._mark_unknown_start(c.start, c.edge_estimates.get('touch'))
                            self._identity_known = False
                            for later in self.contacts[c.id + 1:]:
                                later.side = 'unknown'
                    self.active.remove(c)
        self._commit_contacts()
        self._recovering = False
        held = sum(c.id not in observed and c.release_start is None
                   and c.candidate_since is not None and not c.interrupted for c in self.active)
        self._phase(n, -1 if masked_contact or any(c.id in observed and c.problem == 'unresolved_coalescence' for c in self.active)
                    or (observation is not None and observation.unresolved_segments) else occupancy + held)
        if occupancy:
            if not masked_contact:
                self.last_occupied = n
            self._clear_since = None
        elif observation is not None and observation.unresolved_segments:
            self._clear_since = None
        elif self.origin is not None:
            if self._clear_since is None:
                self._clear_since = n
            if (self.config.has_auto_stop and self._exit_evidence
                    and n - self._clear_since + 1 >= self.config.exit_clear_ms):
                self.finished_reason = "passage_complete"
        self._previous_frame = frame
        if self.origin is not None and n - self._last_visual >= 40:
            self._last_visual = n
            self.timeline.append({"timestamp_s": n / 1000 - self.origin,
                                  "segment_ids": tuple(s.segment_id for s in self.device.layout.segments),
                                  "contact_bits": list(frame.contact_bits), "positions_m": self.positions,
                                  "valid_bits": list(frame.valid_bits), "quality_flags": list(frame.quality_flags),
                                  "feet": [{"contact_id": c.id, "side": c.side, "label": c.label,
                                            "centroid_cm": (self.positions[c.low] + self.positions[c.high]) * 50,
                                            "length_cm": (self.positions[c.high] - self.positions[c.low]) * 100,
                                            "status": "confirmed" if c.confirmed and not c.problem and not c.interrupted else "candidate"}
                                           for c in self.active]})

    def _phase(self, n, count):
        if self.phases and self.phases[-1][1:] == [n, count, self.epoch]:
            self.phases[-1][1] = n + 1
        else:
            self.phases.append([n, n + 1, count, self.epoch])

    def _toe(self, c):
        if not self.direction:
            return metric(reason="direction_unknown")
        if c.problem or c.interrupted or not c.confirmed:
            return metric(reason=c.problem or c.interrupted or "short_contact")
        edge = 3 if self.direction > 0 else 2
        boundary = self.positions[-1] if self.direction > 0 else self.positions[0]
        if any(self.positions[r[edge]] == boundary for r in c.edges):
            return metric(reason="toe_clipped")
        # Weighted sliding platforms; adjacent pitch is read from the physical segment.
        candidates = []
        for i, row in enumerate(c.edges):
            values, duration = [], 0
            for r in c.edges[i:]:
                if values and r[0] != previous_end:
                    break
                pos = self.positions[r[edge]]
                pitch = self.device.layout.segments[r[edge] // 96].pitch_m
                if values and max(max(v for v, _ in values), pos) - min(min(v for v, _ in values), pos) > pitch + 1e-9:
                    break
                values.append((pos, r[1] - r[0]))
                previous_end = r[1]
                duration += r[1] - r[0]
                if duration >= self.config.toe_platform_ms:
                    ordered = sorted(values)
                    def kth(k):
                        total = 0
                        for v, weight in ordered:
                            total += weight
                            if total > k:
                                return v
                    candidates.append((kth((duration - 1) // 2) + kth(duration // 2)) / 2)
                    break
        if not candidates:
            return metric(reason="no_stable_toe_platform")
        return metric(max(candidates) if self.direction > 0 else min(candidates))

    def _support(self, start, end, epoch):
        uncertain = self._narrow_unknown + [(p['start'], p['last'] + 1, self.epoch)
                                           for p in self._narrow_candidates]
        if any(e == epoch and a < end and b > start for a, b, e in uncertain):
            return None, "unconfirmed_narrow_fragment"
        totals = {0: 0, 1: 0, 2: 0}
        cursor = start
        for a, b, count, e in self.phases:
            if b <= start or a >= end:
                continue
            lo, hi = max(start, a), min(end, b)
            if lo != cursor or e != epoch or count < 0:
                return None, "incomplete_observation"
            if count == 0 and b - a < self.config.release_ms:
                return None, "uncertain_short_clear"
            boundaries = sorted({lo, hi, *[x for left, right, _, ep in self._phase_adjustments
                                          if ep == epoch for x in (left, right) if lo < x < hi]})
            for left, right in zip(boundaries, boundaries[1:]):
                midpoint = (left + right) / 2
                inferred = count + sum(delta for a, b, delta, ep in self._phase_adjustments
                                       if ep == epoch and a <= midpoint < b)
                if not 0 <= inferred <= 2:
                    return None, 'incomplete_observation'
                totals[inferred] += right - left
            cursor = hi
        if cursor != end:
            return None, "incomplete_observation"
        return {k: v / 1000 for k, v in totals.items()}, None

    def _flight_release_reason(self, start, end, epoch, rows):
        # The last foot to leave can precede both contacts bounding this step.
        # Validate every transition into clear space, not just the adjacent foot.
        for a, b, count, e in self.phases:
            if count != 0 or e != epoch or b <= start or a >= end:
                continue
            lo, hi = max(start, a), min(end, b)
            boundaries = sorted({lo, hi, *[x for left, right, _, ep in self._phase_adjustments
                                          if ep == epoch for x in (left, right) if lo < x < hi]})
            if not any(sum(delta for left, right, delta, ep in self._phase_adjustments
                           if ep == epoch and left <= (u + v) / 2 < right) == 0
                       for u, v in zip(boundaries, boundaries[1:])):
                continue
            departures = [c for c in self.contacts if c.epoch == epoch and c.end is not None
                          and (c.end == a or any(left == c.end and right == a and delta == -1 and ep == epoch
                                                for left, right, delta, ep in self._phase_adjustments))]
            if not departures or any(not rows[c.id]["lift_s"]["valid"] for c in departures):
                return "lift_not_observed"
        return None

    def _temporal_problem(self, c, through_sample):
        # A later dropout cannot invalidate an already confirmed earlier event.
        if (c.problem == "uncertain_short_clear" and c.first_uncertain_sample is not None
                and through_sample < c.first_uncertain_sample
                and c.first_uncertain_sample - c.start >= max(self.config.confirmation_ms, self.config.min_contact_time)):
            return None
        return c.problem

    def _stop_intervals(self):
        stops = dict(self._preserved_stops)
        for c in self.contacts:
            end = c.end if c.end is not None else c.last + 1
            if c.end is None and c.last_reliable_sample is not None:
                end = c.last_reliable_sample + 1
            if not c.problem and not c.interrupted and end - c.start >= self.config.stop_threshold_s * 1000:
                stops[c.start] = max(stops.get(c.start, end), end)
        return sorted(stops.items())

    def summary(self):
        origin = self.origin or 0
        stops = self._stop_intervals()
        def barrier(cs, temporal=False):
            uncertain = self._narrow_barriers + [(p['start'], p['last'] + 1, self.epoch)
                                                for p in self._narrow_candidates]
            if any(e == cs[0].epoch and a < cs[-1].start and b > cs[0].start
                   for a, b, e in uncertain):
                return "unconfirmed_narrow_fragment"
            for c in cs:
                problem = self._temporal_problem(c, cs[-1].start) if temporal else c.problem
                if problem or not c.confirmed:
                    return problem or c.interrupted or "short_contact"
                if (c.first_masked_sample is not None and c.first_masked_sample <= cs[-1].start):
                    return "masked_contact_boundary"
            if len({c.epoch for c in cs}) != 1:
                return "continuity_break"
            if any(cs[0].start < b and cs[-1].start >= a for a, b in stops):
                return "stop_interval"
            return None
        rows = []
        for c in self.contacts:
            problem = c.problem or (None if c.confirmed else c.interrupted or "short_contact")
            touch = metric(c.start / 1000 - origin if c.touch_known else None,
                           self._temporal_problem(c, c.start) or (None if c.confirmed else c.interrupted or "short_contact")
                           or (None if c.touch_known else "touch_not_observed"))
            lift = metric(c.end / 1000 - origin if c.end is not None and c.lift_known else None,
                          problem or c.interrupted or (None if c.lift_known else "lift_not_observed"))
            reason = problem or c.interrupted or ("incomplete_contact" if not (touch["valid"] and lift["valid"]) else None)
            if any(c.start < b and (c.end or c.last + 1) > a for a, b in stops):
                reason = "stop_interval"
            rows.append({"id": c.id, "epoch": c.epoch, "label": c.label, "side": c.side,
                         "identity_source": "manual_first_foot_and_alternation" if c.side != "unknown" else "alternation_only",
                         "touch_s": touch, "lift_s": lift, "toe_m": self._toe(c),
                         "contact_s": metric((c.end - c.start) / 1000 if c.end is not None else None, reason),
                         "candidate_outcome": c.candidate_outcome,
                         "first_seen_sample": c.first_seen_sample,
                         "touch_sample": c.start if touch['valid'] and 'touch' not in c.edge_estimates else None,
                         "lift_sample": c.end if lift['valid'] and 'lift' not in c.edge_estimates else None,
                         "confirmed_sample": c.confirmed_sample})
        steps, cycles = [], []
        sequence = [c for c in self.contacts if c.candidate_outcome not in {'excluded_nonstep', 'associated_fragment'}]
        for i in range(1, len(sequence)):
            a, b = sequence[i - 1:i + 1]
            ar, br = rows[a.id], rows[b.id]
            reason = barrier([a, b])
            time_barrier = barrier([a, b], temporal=True)
            temporal = time_barrier or (None if ar["touch_s"]["valid"] and br["touch_s"]["valid"] else "touch_not_observed")
            dt = metric((b.start - a.start) / 1000, temporal)
            spatial = reason or (None if ar["toe_m"]["valid"] and br["toe_m"]["valid"] else "toe_unavailable")
            length = metric(abs(br["toe_m"]["value"] - ar["toe_m"]["value"]) if not spatial else None, spatial)
            speed = metric(length["value"] / dt["value"] if length["valid"] and dt["valid"] and dt["value"] > 0 else None,
                           reason or (None if length["valid"] and dt["valid"] and dt["value"] > 0 else "length_or_time_unavailable"))
            support, phase_reason = self._support(a.start, b.start, a.epoch)
            flight_reason = temporal or phase_reason
            if support and support[0] > 0:
                # Positive flight depends on release -> next touch, not on the
                # preceding stance's (possibly clipped) touch event.
                flight_reason = (time_barrier or phase_reason
                                 or (None if br["touch_s"]["valid"] else "touch_not_observed")
                                 or self._flight_release_reason(a.start, b.start, a.epoch, rows))
            flight = metric(support[0] if support else None, flight_reason)
            steps.append({"from_id": a.id, "to_id": b.id, "side": b.side,
                          "length_m": length, "time_s": dt, "speed_m_s": speed, "flight_s": flight})
            if i < 2:
                continue
            x, y, z = sequence[i - 2:i + 1]
            xr, zr = rows[x.id], rows[z.id]
            why = barrier([x, y, z], temporal=True)
            if x.label != z.label or x.label == y.label:
                why = why or "identity_uncertain"
            time_reason = why or (None if xr["touch_s"]["valid"] and zr["touch_s"]["valid"] else "touch_not_observed")
            support, phase_reason = self._support(x.start, z.start, x.epoch)
            phase_reason = time_reason or phase_reason
            if any(c.last + 1 <= z.start and not rows[c.id]['lift_s']['valid'] for c in (x, y)):
                phase_reason = phase_reason or "lift_not_observed"
            spatial_reason = barrier([x, y, z]) or why or (None if xr["toe_m"]["valid"] and zr["toe_m"]["valid"] else "toe_unavailable")
            cycles.append({"from_id": x.id, "to_id": z.id, "label": x.label, "side": x.side,
                           "duration_s": metric((z.start - x.start) / 1000, time_reason),
                           "length_m": metric(abs(zr["toe_m"]["value"] - xr["toe_m"]["value"]) if not spatial_reason else None, spatial_reason),
                           "contact_s": metric(xr["contact_s"]["value"], xr["contact_s"]["missing_reason"]),
                           "swing_s": metric((z.start - x.end) / 1000 if x.end is not None else None,
                                             time_reason or (None if xr["lift_s"]["valid"] else "lift_not_observed")),
                           **{name: metric(support[count] if support else None,
                                          phase_reason or (self._flight_release_reason(x.start, z.start, x.epoch, rows)
                                                           if count == 0 else None))
                              for name, count in (("flight_s", 0), ("single_support_s", 1), ("double_support_s", 2))}})
        def values(records, key):
            return [r[key]["value"] for r in records if r[key]["valid"]]
        def stats(records, keys):
            result = {}
            for key in keys:
                v = values(records, key)
                result[key] = {"count": len(v), "mean": sum(v) / len(v) if v else None}
            return result
        flight_cycles = [c for c in cycles if c["flight_s"]["valid"] and c["flight_s"]["value"] > 0]
        grouped = {"all": stats(cycles, ("duration_s", "length_m", "contact_s", "swing_s", "single_support_s", "double_support_s", "flight_s")),
                   "with_flight": stats(flight_cycles, ("duration_s", "length_m", "contact_s", "swing_s", "single_support_s", "double_support_s", "flight_s"))}
        sides = {}
        for key, records in (("step_length_m", steps), ("contact_s", rows)):
            field = "length_m" if key == "step_length_m" else key
            left, right = (values([r for r in records if r["side"] == side], field) for side in ("left", "right"))
            lm, rm = (sum(v) / len(v) if v else None for v in (left, right))
            eligible = len(left) >= 3 and len(right) >= 3 and lm + rm > 0
            sides[key] = {"left_count": len(left), "right_count": len(right), "left_mean": lm, "right_mean": rm,
                          "asymmetry_percent": metric(abs(lm - rm) / ((lm + rm) / 2) * 100 if eligible else None,
                                                       None if eligible else "insufficient_bilateral_samples")}
        lengths = values(steps, "length_m")
        timed = [s for s in steps if s["speed_m_s"]["valid"]]
        speed = sum(s["length_m"]["value"] for s in timed) / sum(s["time_s"]["value"] for s in timed) if timed else None
        end = self.last_occupied + 1 if self.last_occupied is not None else None
        if (self.last_occupied is not None and any(c.end is not None and 'lift' in c.edge_estimates
                                                 and c.end >= self.last_occupied for c in self.contacts)):
            end = max(c.end for c in self.contacts if c.end is not None and c.end >= self.last_occupied)
        duration = max(0, end / 1000 - origin) if self.origin is not None and end is not None else None
        if (self._duration_start_censored or
                (self._duration_censored and (self._duration_clear_upper is None
                                             or end is None or end < self._duration_clear_upper))):
            duration = None
        return {"segment_count": len(self.device.layout.segments), "nominal_length_m": len(self.device.layout.segments),
                "direction": self.direction, "duration_s": duration, "valid_steps": sum(s["time_s"]["valid"] for s in steps),
                "valid_cycles": sum(c["duration_s"]["valid"] for c in cycles), "step_lengths_m": lengths,
                "running_speed_m_s": speed, "contacts": rows, "steps": steps, "cycles": cycles,
                "record_count": len(rows), "confirmed_contacts": sum(c.confirmed for c in self.contacts),
                "valid_touches": sum(r['touch_s']['valid'] for r in rows),
                "valid_contact_durations": sum(r['contact_s']['valid'] for r in rows),
                "valid_step_lengths": sum(r['length_m']['valid'] for r in steps),
                "valid_step_speeds": len(timed),
                "valid_stride_lengths": sum(r['length_m']['valid'] for r in cycles),
                "valid_support_cycles": sum(all(r[k]['valid'] for k in ('flight_s', 'single_support_s', 'double_support_s')) for r in cycles),
                "candidate_decisions": list(self._candidate_decisions)
                    + [self._candidate_row(q, 'pending', 'awaiting_release_or_confirmation') for q in self._narrow_candidates]
                    + [self._candidate_row(c, 'pending', 'awaiting_release_or_confirmation') for c in self.active
                       if not c.confirmed and c.candidate_outcome == 'pending'],
                "groups": grouped, "sides": sides,
                "step_statistics": stats(steps, ("length_m", "time_s", "speed_m_s", "flight_s")),
                "flight_cycle_count": len(flight_cycles),
                "zero_flight_cycle_count": sum(c["flight_s"]["valid"] and c["flight_s"]["value"] == 0 for c in cycles),
                "unknown_flight_cycle_count": sum(not c["flight_s"]["valid"] for c in cycles),
                "stops": [{"start_s": a / 1000 - origin, "end_s": b / 1000 - origin} for a, b in stops],
                "issues": [{**x, "time_s": x["sample"] / 1000 - origin} for x in self.issues],
                "status": "出口证据不足，可手动结束" if self._clear_since is not None and not self._exit_evidence else "跑步中"}

    def build_report(self, reason, export_frames=(), export_timestamps=()):
        summary = self.summary()
        return OvergroundRunningReport(
            touch_count=summary['valid_touches'],
            lift_count=sum(r['lift_s']['valid'] for r in summary['contacts']),
            finish_reason=reason, running_summary=summary, visual_timeline=tuple(self.timeline),
            export_frames=export_frames, export_timestamps=export_timestamps,
            report_config_snapshot={**self.config.to_dict(), "device": self.device.snapshot(),
                                    "algorithm": "overground_running_v1.9", "spatial_reference": "toe_to_toe",
                                    "toe_method": "furthest_stable_leading_edge_platform_median",
                                    "readiness_stale_ms": 500, "data_timeout_ms": 1000,
                                    "tracking": {"direction_displacement_m": self.DIRECTION_DISPLACEMENT_M,
                                                 "cluster_gap_m": self.CLUSTER_GAP_M,
                                                 "match_margin_m": self.MATCH_MARGIN_M,
                                                 "max_cluster_width_m": self.MAX_CLUSTER_WIDTH_M,
                                                 "narrow_candidate_width_m": self.NARROW_CANDIDATE_WIDTH_M,
                                                 "narrow_candidate_scope": "local_candidate_evidence_before_identity",
                                                 "fragment_association": "unique_existing_envelope_with_match_margin"},
                                    "real_world_validation": "pending"})
