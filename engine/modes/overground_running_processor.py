"""Optical overground running, device-clock timing and toe-to-toe geometry.

A blocked beam is an optical proxy, not a measurement of ground reaction force.
Unobserved events never become zeros, and short candidates remain sequence barriers.
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


class OvergroundRunningProcessor:
    name = "overground_running"
    display_mode = "地面跑步"
    DIRECTION_DISPLACEMENT_M = .15
    CLUSTER_GAP_M = .04
    MATCH_MARGIN_M = .035
    MAX_CLUSTER_WIDTH_M = .45

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
        self._ambiguous = False
        self._last_visual = -100
        self._phase_adjustments = []
        self._duration_censored = False
        self._duration_clear_upper = None

    def break_continuity(self, code, frame_index=None):
        self._preserved_stops = self._stop_intervals()
        self.issues.append({"code": code, "sample": self.last_sample, "frame_index": frame_index})
        if self.origin is not None:
            self.timeline.append({"timestamp_s": (self.last_sample + 1) / 1000 - self.origin,
                                  "positions_m": self.positions, "contact_bits": [0] * len(self.positions),
                                  "valid_bits": [0] * len(self.positions), "feet": [], "quality_flags": [code]})
        for c in self.active:
            c.interrupted = code
        self.active.clear()
        self.epoch += 1
        self._identity_known = False
        self._recovering = True
        self._last_label = "B"
        self._clear_since = None
        self._exit_evidence = False

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
        if (len(frame.contact_bits) != len(self.positions) or len(frame.valid_bits) != len(self.positions)
                or (observation is None and not all(frame.valid_bits))
                or any(x != "frame_gap" for x in frame.quality_flags)):
            self.break_continuity("invalid_sample", frame.frame_index)
            return
        if masked_contact:
            if not self._masked_contact_uncertain:
                self.break_continuity("masked_contact_boundary", frame.frame_index)
            self._masked_contact_uncertain = True
            return
        self._masked_contact_uncertain = False
        if observation is not None:
            if observation.unresolved_segments:
                self._duration_censored = True
                self._duration_clear_upper = None
            if (self._duration_censored and self._duration_clear_upper is None
                    and b'\x01' not in frame.contact_bits and b'\x00' not in frame.valid_bits):
                self._duration_clear_upper = n
            for c in list(self.active):
                if observation.affected(c.low, c.high):
                    self._preserved_stops = self._stop_intervals()
                    c.interrupted = 'local_unknown_timeout'
                    self.active.remove(c)
                    self._identity_known = False
            for c in list(self.active):
                if (c.interrupted != 'local_unknown_timeout' and ((not c.confirmed and c.has_unknown
                     and n - c.start >= max(self.config.min_contact_time, self.config.confirmation_ms) + 10)
                        or (c.candidate_since is not None
                            and n - c.candidate_since >= self.config.release_ms + 10))):
                    self._preserved_stops = self._stop_intervals()
                    c.interrupted = 'local_unknown_timeout'
                    self._identity_known = False
        if b'\x01' in frame.contact_bits:
            self.last_occupied = n
        groups = self._groups(frame.contact_bits)
        if observation is not None:
            groups = observation.associate_fragments(groups, self.active)
        else:
            groups = self._associate_inner_fragments(groups)
        matches, used = [], set()
        ambiguous = len(groups) > 2
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
            if not self._ambiguous:
                self.break_continuity("ambiguous_contacts", frame.frame_index)
            self._ambiguous = True
            self._phase(n, -1)
            return
        self._ambiguous = False
        low_edge, high_edge = self.positions[0], self.positions[-1]
        observed = set()
        new = []
        for low, high, c in matches:
            if c is None:
                self._last_label = "A" if self._last_label == "B" else "B"
                side = {"Left": "left", "Right": "right"}.get(self.config.starting_foot, "unknown")
                if not self._identity_known:
                    side = "unknown"
                elif self._last_label == "B" and side != "unknown":
                    side = "right" if side == "left" else "left"
                boundary = self.positions[low] == low_edge or self.positions[high] == high_edge
                c = Contact(len(self.contacts), self.epoch, self._last_label, side, n, n, low, high,
                            not self._recovering and not boundary)
                if observation is not None:
                    edge = observation.edge(low, high, 1)
                    if edge:
                        c.start = edge.sample
                        c.edge_estimates['touch'] = [edge.left_sample, edge.right_sample]
                        if c.start < n:
                            self._phase_adjustments.append((c.start, n, 1, c.epoch))
                    if observation.affected(low, high, observation.recovery_segments):
                        c.touch_known = False
                self._exit_evidence = False
                self.contacts.append(c)
                self.active.append(c)
                new.append(c)
            observed.add(c.id)
            if c.last < n - 1 and c.release_start is not None:
                # A sub-confirmation clear interval cannot silently count as continuous support.
                self._preserved_stops = self._stop_intervals()
                c.problem = c.problem or "uncertain_short_clear"
                if c.first_uncertain_sample is None:
                    c.first_uncertain_sample = c.last + 1
                self._identity_known = False
                for affected in self.contacts[c.id:]:
                    affected.side = "unknown"
            c.last, c.low, c.high = n, low, high
            reliable = observation is None or observation.reliable(low, high)
            c.observed_samples += int(reliable and c.interrupted != 'local_unknown_timeout')
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
                    if self.origin is None and not c.problem:
                        self.origin = c.start / 1000
                    prior = [x for x in self.contacts[:c.id] if x.confirmed and x.epoch == c.epoch and not x.problem]
                    if any(x.label == c.label and x.last >= c.start for x in prior):
                        c.problem = "identity_uncertain"
                        c.side = "unknown"
                        self._identity_known = False
                    if prior and c.touch_known and not c.problem:
                        prev = prior[-1]
                        delta = (self.positions[low] + self.positions[high]
                                 - self.positions[prev.low] - self.positions[prev.high]) / 2
                        if abs(delta) >= self.DIRECTION_DISPLACEMENT_M:
                            if self.direction and delta * self.direction < 0:
                                c.problem = "turn_detected"
                                self.finished_reason = "turn_detected"
                            elif prev.touch_known:
                                self.direction = 1 if delta > 0 else -1
            endpoint = high_edge if self.direction > 0 else low_edge
            at_exit = self.direction and (self.positions[high] == endpoint or self.positions[low] == endpoint)
            if reliable:
                c.endpoint_run = c.endpoint_run + 1 if at_exit else 0
            if c.confirmed and c.endpoint_run >= self.config.confirmation_ms:
                self._exit_evidence = True
        if groups and not any(c.id in observed and c.confirmed
                              and c.endpoint_run >= self.config.confirmation_ms for c in self.active):
            self._exit_evidence = False
        if len(new) > 1:
            self._identity_known = False
            for c in new:
                c.side, c.problem = "unknown", "simultaneous_contacts"
        for c in list(self.active):
            if c.id not in observed:
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
                    c.end = c.release_start
                    c.lift_known = self.positions[c.low] != low_edge and self.positions[c.high] != high_edge
                    if not c.confirmed:
                        c.problem = c.problem or "short_contact"
                        self._identity_known = False
                        # Already observed overlapping contacts also lose the manual anchor.
                        for later in self.contacts[c.id + 1:]:
                            later.side = "unknown"
                    self.active.remove(c)
        self._recovering = False
        held = sum(c.id not in observed and c.release_start is None
                   and c.candidate_since is not None and not c.interrupted for c in self.active)
        self._phase(n, -1 if observation is not None and observation.unresolved_segments else len(groups) + held)
        if groups:
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
            for c in cs:
                problem = self._temporal_problem(c, cs[-1].start) if temporal else c.problem
                if problem or not c.confirmed:
                    return problem or "short_contact"
            if len({c.epoch for c in cs}) != 1:
                return "continuity_break"
            if any(cs[0].start < b and cs[-1].start >= a for a, b in stops):
                return "stop_interval"
            return None
        rows = []
        for c in self.contacts:
            problem = c.problem or (None if c.confirmed else "short_contact")
            touch = metric(c.start / 1000 - origin if c.touch_known else None,
                           self._temporal_problem(c, c.start) or (None if c.confirmed else "short_contact")
                           or (None if c.touch_known else "touch_not_observed"))
            lift = metric(c.end / 1000 - origin if c.end is not None and c.lift_known else None,
                          problem or c.interrupted or (None if c.lift_known else "lift_not_observed"))
            reason = problem or c.interrupted or ("incomplete_contact" if not (touch["valid"] and lift["valid"]) else None)
            if any(c.start < b and (c.end or c.last + 1) > a for a, b in stops):
                reason = "stop_interval"
            rows.append({"id": c.id, "epoch": c.epoch, "label": c.label, "side": c.side,
                         "identity_source": "manual_first_foot_and_alternation" if c.side != "unknown" else "alternation_only",
                         "touch_s": touch, "lift_s": lift, "toe_m": self._toe(c),
                         "contact_s": metric((c.end - c.start) / 1000 if c.end is not None else None, reason)})
        steps, cycles = [], []
        for i in range(1, len(self.contacts)):
            a, b = self.contacts[i - 1:i + 1]
            ar, br = rows[i - 1:i + 1]
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
            x, y, z = self.contacts[i - 2:i + 1]
            xr, zr = rows[i - 2], rows[i]
            why = barrier([x, y, z], temporal=True)
            if x.label != z.label or x.label == y.label:
                why = why or "identity_uncertain"
            time_reason = why or (None if xr["touch_s"]["valid"] and zr["touch_s"]["valid"] else "touch_not_observed")
            support, phase_reason = self._support(x.start, z.start, x.epoch)
            phase_reason = time_reason or phase_reason
            if any(self.contacts[k].last + 1 <= z.start and not rows[k]["lift_s"]["valid"]
                   for k in (i - 2, i - 1)):
                phase_reason = phase_reason or "lift_not_observed"
            spatial_reason = barrier([x, y, z]) or why or (None if xr["toe_m"]["valid"] and zr["toe_m"]["valid"] else "toe_unavailable")
            cycles.append({"from_id": x.id, "to_id": z.id, "label": x.label, "side": x.side,
                           "duration_s": metric((z.start - x.start) / 1000, time_reason),
                           "length_m": metric(abs(zr["toe_m"]["value"] - xr["toe_m"]["value"]) if not spatial_reason else None, spatial_reason),
                           "contact_s": metric(xr["contact_s"]["value"], why or xr["contact_s"]["missing_reason"]),
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
        if (self._duration_censored and (self._duration_clear_upper is None
                                        or end is None or end < self._duration_clear_upper)):
            duration = None
        return {"segment_count": len(self.device.layout.segments), "nominal_length_m": len(self.device.layout.segments),
                "direction": self.direction, "duration_s": duration, "valid_steps": sum(s["time_s"]["valid"] for s in steps),
                "valid_cycles": sum(c["duration_s"]["valid"] for c in cycles), "step_lengths_m": lengths,
                "running_speed_m_s": speed, "contacts": rows, "steps": steps, "cycles": cycles,
                "groups": grouped, "sides": sides,
                "step_statistics": stats(steps, ("length_m", "time_s", "speed_m_s", "flight_s")),
                "flight_cycle_count": len(flight_cycles),
                "zero_flight_cycle_count": sum(c["flight_s"]["valid"] and c["flight_s"]["value"] == 0 for c in cycles),
                "unknown_flight_cycle_count": sum(not c["flight_s"]["valid"] for c in cycles),
                "stops": [{"start_s": a / 1000 - origin, "end_s": b / 1000 - origin} for a, b in stops],
                "issues": [{**x, "time_s": x["sample"] / 1000 - origin} for x in self.issues],
                "status": "出口证据不足，可手动结束" if self._clear_since is not None and not self._exit_evidence else "跑步中"}

    def build_report(self, reason, export_frames=(), export_timestamps=()):
        return OvergroundRunningReport(
            touch_count=sum(c.confirmed for c in self.contacts),
            lift_count=sum(c.confirmed and c.end is not None for c in self.contacts),
            finish_reason=reason, running_summary=self.summary(), visual_timeline=tuple(self.timeline),
            export_frames=export_frames, export_timestamps=export_timestamps,
            report_config_snapshot={**self.config.to_dict(), "device": self.device.snapshot(),
                                    "algorithm": "overground_running_v1.4", "spatial_reference": "toe_to_toe",
                                    "toe_method": "furthest_stable_leading_edge_platform_median",
                                    "readiness_stale_ms": 500, "data_timeout_ms": 1000,
                                    "tracking": {"direction_displacement_m": self.DIRECTION_DISPLACEMENT_M,
                                                 "cluster_gap_m": self.CLUSTER_GAP_M,
                                                 "match_margin_m": self.MATCH_MARGIN_M,
                                                 "max_cluster_width_m": self.MAX_CLUSTER_WIDTH_M,
                                                 "fragment_association": "unique_existing_envelope_with_match_margin"},
                                    "real_world_validation": "pending"})
